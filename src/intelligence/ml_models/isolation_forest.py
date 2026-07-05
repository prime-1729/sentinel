"""
Isolation Forest for anomaly detection (Layer 1).
Refactored to use learned thresholds instead of hardcoded percentiles.
"""

import os
import time
import numpy as np
import pandas as pd
import joblib
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler
from typing import List, Dict, Any, Optional

POSITION_FEATURES = ['relative_alt', 'vx', 'vy', 'vz']
BATTERY_FEATURES = ['voltage', 'current', 'remaining_pct']
ATTITUDE_FEATURES = ['roll_deg', 'pitch_deg', 'yaw_deg']
HUD_FEATURES = ['airspeed', 'groundspeed', 'climb_rate', 'throttle_pct']
MOTOR_FEATURES = ['rpm_1', 'rpm_2', 'rpm_3', 'rpm_4', 'cur_1', 'cur_2', 'cur_3', 'cur_4']
VIBRATION_FEATURES = ['vibration_x', 'vibration_y', 'vibration_z']

ALL_RAW_FEATURES = POSITION_FEATURES + BATTERY_FEATURES + ATTITUDE_FEATURES + HUD_FEATURES + MOTOR_FEATURES + VIBRATION_FEATURES
ROLLING_WINDOW = 10

def _merge_telemetry_streams(telemetry: Dict[str, pd.DataFrame]) -> pd.DataFrame:
    base = telemetry['positions'][['timestamp'] + [f for f in POSITION_FEATURES if f in telemetry['positions'].columns]].copy()
    base = base.sort_values('timestamp').reset_index(drop=True)

    for key, features in [('battery', BATTERY_FEATURES), ('attitude', ATTITUDE_FEATURES), ('hud', HUD_FEATURES), ('motors', MOTOR_FEATURES), ('vibration', VIBRATION_FEATURES)]:
        if key in telemetry and not telemetry[key].empty:
            stream = telemetry[key][['timestamp'] + [f for f in features if f in telemetry[key].columns]].copy()
            stream = stream.sort_values('timestamp').reset_index(drop=True)
            base = pd.merge_asof(base, stream, on='timestamp', direction='nearest')

    return base

def _engineer_features(merged: pd.DataFrame) -> pd.DataFrame:
    result = pd.DataFrame()
    result['timestamp'] = merged['timestamp']

    feature_cols = [c for c in merged.columns if c in ALL_RAW_FEATURES]

    for col in feature_cols:
        result[col] = merged[col]
        result[f'{col}_mean'] = merged[col].rolling(window=ROLLING_WINDOW, min_periods=1).mean()
        result[f'{col}_std'] = merged[col].rolling(window=ROLLING_WINDOW, min_periods=1).std().fillna(0)
        result[f'{col}_rate'] = merged[col].diff().fillna(0)
        
    # Cross-sensor correlation features
    if 'throttle_pct' in merged.columns and 'climb_rate' in merged.columns:
        result['throttle_climb_interaction'] = merged['throttle_pct'] * merged['climb_rate']
        
    if 'rpm_1' in merged.columns and 'rpm_2' in merged.columns and 'rpm_3' in merged.columns and 'rpm_4' in merged.columns:
        result['rpm_symmetry_x'] = (merged['rpm_1'] + merged['rpm_2']) - (merged['rpm_3'] + merged['rpm_4'])
        result['rpm_symmetry_y'] = (merged['rpm_1'] + merged['rpm_4']) - (merged['rpm_2'] + merged['rpm_3'])
        
    # GPS Integrity features
    if 'hdop' in merged.columns and 'vdop' in merged.columns:
        result['gps_integrity'] = merged['hdop'] + merged['vdop']
    elif 'satellites_visible' in merged.columns:
        result['gps_integrity'] = 1.0 / (merged['satellites_visible'] + 1)
        
    return result

def _get_feature_columns(df: pd.DataFrame) -> List[str]:
    return [c for c in df.columns if c != 'timestamp']

class MLAnomalyDetector:
    DEFAULT_MODEL_PATH = "data/models/isolation_forest.joblib"

    def __init__(self, n_estimators: int = 100, random_state: int = 42):
        self.n_estimators = n_estimators
        self.random_state = random_state
        self.model: Optional[IsolationForest] = None
        self.scaler: Optional[StandardScaler] = None
        self.feature_names: Optional[List[str]] = None
        self.optimal_threshold: float = -0.5 # Default fallback
        self.is_trained = False

    def train(self, telemetry: Dict[str, pd.DataFrame], val_telemetry: Optional[Dict[str, pd.DataFrame]] = None) -> Dict[str, Any]:
        start = time.time()

        merged = _merge_telemetry_streams(telemetry)
        featured = _engineer_features(merged)
        self.feature_names = _get_feature_columns(featured)
        X = featured[self.feature_names].values

        valid_mask = ~np.isnan(X).any(axis=1)
        X = X[valid_mask]

        self.scaler = StandardScaler()
        X_scaled = self.scaler.fit_transform(X)

        self.model = IsolationForest(
            n_estimators=self.n_estimators,
            random_state=self.random_state,
            n_jobs=-1
        )
        self.model.fit(X_scaled)
        
        # Learn threshold from validation set (or use training data scores if no val set)
        if val_telemetry is None:
            scores = self.model.decision_function(X_scaled)
            self.optimal_threshold = float(np.percentile(scores, 3.0)) # 3% fallback if no val data
        else:
            val_merged = _merge_telemetry_streams(val_telemetry)
            val_featured = _engineer_features(val_merged)
            
            missing = [f for f in self.feature_names if f not in val_featured.columns]
            for col in missing:
                val_featured[col] = 0.0
                
            X_val = val_featured[self.feature_names].values
            valid_mask = ~np.isnan(X_val).any(axis=1)
            X_val_valid = X_val[valid_mask]
            
            if len(X_val_valid) > 0:
                X_val_scaled = self.scaler.transform(X_val_valid)
                val_scores = self.model.decision_function(X_val_scaled)
                # Since val_telemetry is presumably normal, we use its lower bound
                self.optimal_threshold = float(np.percentile(val_scores, 1.0))
            else:
                scores = self.model.decision_function(X_scaled)
                self.optimal_threshold = float(np.percentile(scores, 3.0))

        self.is_trained = True

        elapsed = time.time() - start
        return {
            'rows_trained': len(X_scaled),
            'features': len(self.feature_names),
            'training_time_seconds': round(elapsed, 2),
            'optimal_threshold': self.optimal_threshold
        }

    def score(self, telemetry: Dict[str, pd.DataFrame]) -> np.ndarray:
        """Returns raw anomaly scores for each timestamp. More negative = more anomalous."""
        if not self.is_trained:
            return np.array([])
            
        merged = _merge_telemetry_streams(telemetry)
        featured = _engineer_features(merged)

        missing = [f for f in self.feature_names if f not in featured.columns]
        for col in missing:
            featured[col] = 0.0

        X = featured[self.feature_names].values
        valid_mask = ~np.isnan(X).any(axis=1)
        X_valid = X[valid_mask]

        if len(X_valid) == 0:
            return np.array([])

        X_scaled = self.scaler.transform(X_valid)
        return self.model.decision_function(X_scaled)

    def detect(self, telemetry: Dict[str, pd.DataFrame]) -> List[Dict[str, Any]]:
        """Run detection using the learned optimal threshold."""
        if not self.is_trained:
            return []

        merged = _merge_telemetry_streams(telemetry)
        featured = _engineer_features(merged)

        missing = [f for f in self.feature_names if f not in featured.columns]
        for col in missing:
            featured[col] = 0.0

        X = featured[self.feature_names].values
        timestamps = featured['timestamp'].values

        valid_mask = ~np.isnan(X).any(axis=1)
        X_valid = X[valid_mask]
        ts_valid = timestamps[valid_mask]

        if len(X_valid) == 0:
            return []

        X_scaled = self.scaler.transform(X_valid)
        scores = self.model.decision_function(X_scaled)

        anomalies = []
        for i in range(len(X_valid)):
            if scores[i] <= self.optimal_threshold:
                deviations = np.abs(X_scaled[i])
                top_indices = np.argsort(deviations)[-3:][::-1]
                top_features = [f"{self.feature_names[idx]} ({deviations[idx]:.1f}σ)" for idx in top_indices]

                anomalies.append({
                    'timestamp': float(ts_valid[i]),
                    'event_type': 'IsolationForestAnomaly',
                    'severity': 'HIGH',
                    'score': float(scores[i]),
                    'detail': f"IF score: {scores[i]:.4f} (thresh: {self.optimal_threshold:.4f}). Deviations: {', '.join(top_features)}",
                    'recommendation': "Layer 1 triggered. Forward to Layer 2 for confirmation."
                })

        return anomalies

    def save(self, path: str = None) -> str:
        if not self.is_trained:
            raise RuntimeError("Model not trained yet.")

        path = path or self.DEFAULT_MODEL_PATH
        model_dir = os.path.dirname(path)
        if model_dir and not os.path.exists(model_dir):
            os.makedirs(model_dir, exist_ok=True)

        payload = {
            'model': self.model,
            'scaler': self.scaler,
            'feature_names': self.feature_names,
            'optimal_threshold': self.optimal_threshold,
            'n_estimators': self.n_estimators
        }
        joblib.dump(payload, path)
        return path

    @classmethod
    def load(cls, path: str = None) -> 'MLAnomalyDetector':
        path = path or cls.DEFAULT_MODEL_PATH
        payload = joblib.load(path)
        detector = cls(n_estimators=payload['n_estimators'])
        detector.model = payload['model']
        detector.scaler = payload['scaler']
        detector.feature_names = payload['feature_names']
        detector.optimal_threshold = payload.get('optimal_threshold', -0.5)
        detector.is_trained = True
        return detector
