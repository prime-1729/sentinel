"""
ML-based anomaly detection for drone telemetry using Isolation Forest.

This module provides a pattern-based anomaly detection layer that learns
"normal" flight behavior from telemetry data and flags statistical outliers.
It supplements (does not replace) the threshold-based detectors in anomaly.py.

Architecture:
    Layer 1 (anomaly.py) — Deterministic threshold detectors for hard engineering limits
    Layer 2 (this module) — ML pattern detector for contextual/multivariate anomalies

Model: scikit-learn IsolationForest
    - Unsupervised: trains on normal flight data only
    - Fast: <1s training, <1ms inference per row
    - CPU-only: no GPU required
    - Explainable: anomaly scores indicate degree of abnormality

References:
    - RADD framework (arxiv): hybrid rule+IF achieves >93% detection
    - ArduPilot SITL telemetry used as "normal" training baseline
"""

import os
import time
import math
import numpy as np
import pandas as pd
import joblib
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler
from typing import List, Dict, Any, Optional
from dataclasses import dataclass


# Features to extract from each telemetry stream.
# Excludes raw lat/lon (position-dependent), uses velocity instead.
POSITION_FEATURES = ['relative_alt', 'vx', 'vy', 'vz']
BATTERY_FEATURES = ['voltage', 'current', 'remaining_pct']
ATTITUDE_FEATURES = ['roll_deg', 'pitch_deg', 'yaw_deg']
HUD_FEATURES = ['airspeed', 'groundspeed', 'climb_rate', 'throttle_pct']

ALL_RAW_FEATURES = POSITION_FEATURES + BATTERY_FEATURES + ATTITUDE_FEATURES + HUD_FEATURES
ROLLING_WINDOW = 10  # readings for rolling statistics


def _merge_telemetry_streams(telemetry: Dict[str, pd.DataFrame]) -> pd.DataFrame:
    """
    Merge separate telemetry DataFrames into a single time-aligned matrix.
    Uses nearest-timestamp merge (asof join) since streams arrive at
    slightly different rates.
    """
    # Start with positions as the time base (highest frequency)
    base = telemetry['positions'][['timestamp'] + [f for f in POSITION_FEATURES if f in telemetry['positions'].columns]].copy()
    base = base.sort_values('timestamp').reset_index(drop=True)

    for key, features in [('battery', BATTERY_FEATURES), ('attitude', ATTITUDE_FEATURES), ('hud', HUD_FEATURES)]:
        if key in telemetry and not telemetry[key].empty:
            stream = telemetry[key][['timestamp'] + [f for f in features if f in telemetry[key].columns]].copy()
            stream = stream.sort_values('timestamp').reset_index(drop=True)
            base = pd.merge_asof(base, stream, on='timestamp', direction='nearest')

    return base


def _engineer_features(merged: pd.DataFrame) -> pd.DataFrame:
    """
    Create rolling window features to capture temporal context.
    
    For each raw feature, generates:
    - *_mean: rolling mean over ROLLING_WINDOW readings (smoothed value)
    - *_std: rolling std over ROLLING_WINDOW readings (volatility/instability)
    - *_rate: rate of change / first derivative (trend direction)
    """
    result = pd.DataFrame()
    result['timestamp'] = merged['timestamp']

    feature_cols = [c for c in merged.columns if c in ALL_RAW_FEATURES]

    for col in feature_cols:
        # Raw value
        result[col] = merged[col]
        # Rolling mean — smoothed signal
        result[f'{col}_mean'] = merged[col].rolling(window=ROLLING_WINDOW, min_periods=1).mean()
        # Rolling std — instability indicator
        result[f'{col}_std'] = merged[col].rolling(window=ROLLING_WINDOW, min_periods=1).std().fillna(0)
        # Rate of change — first derivative
        result[f'{col}_rate'] = merged[col].diff().fillna(0)

    return result


def _get_feature_columns(df: pd.DataFrame) -> List[str]:
    """Return all feature columns (everything except timestamp)."""
    return [c for c in df.columns if c != 'timestamp']


class MLAnomalyDetector:
    """
    Isolation Forest-based anomaly detector for drone telemetry.
    
    Trains on "normal" flight data to learn baseline behavior patterns.
    At inference time, scores new telemetry and flags statistical outliers
    as potential anomalies.
    
    Usage:
        # Training
        detector = MLAnomalyDetector()
        detector.train(telemetry_dict)
        detector.save('data/ml_model.joblib')
        
        # Inference
        detector = MLAnomalyDetector.load('data/ml_model.joblib')
        anomalies = detector.detect(telemetry_dict)
    """

    DEFAULT_MODEL_PATH = "data/ml_model.joblib"

    def __init__(self, contamination: str = 'auto', n_estimators: int = 100, random_state: int = 42):
        """
        Initialize the detector.

        Args:
            contamination: Expected fraction of anomalies in training data.
                          'auto' uses scikit-learn's heuristic. Use a float
                          (e.g., 0.01) if you know the approximate anomaly rate.
            n_estimators: Number of isolation trees in the forest.
            random_state: Random seed for reproducibility.
        """
        self.contamination = contamination
        self.n_estimators = n_estimators
        self.random_state = random_state
        self.model: Optional[IsolationForest] = None
        self.scaler: Optional[StandardScaler] = None
        self.feature_names: Optional[List[str]] = None
        self.is_trained = False

    def train(self, telemetry: Dict[str, pd.DataFrame]) -> Dict[str, Any]:
        """
        Train the Isolation Forest on telemetry data assumed to be "normal."

        Args:
            telemetry: Dict of DataFrames with keys 'positions', 'battery',
                      'attitude', 'hud' (standard SENTINEL format).

        Returns:
            Dict with training statistics (rows, features, time).
        """
        start = time.time()

        # Merge and engineer features
        merged = _merge_telemetry_streams(telemetry)
        featured = _engineer_features(merged)
        self.feature_names = _get_feature_columns(featured)
        X = featured[self.feature_names].values

        # Remove rows with NaN (from rolling window warmup)
        valid_mask = ~np.isnan(X).any(axis=1)
        X = X[valid_mask]

        # Scale features to zero mean, unit variance
        self.scaler = StandardScaler()
        X_scaled = self.scaler.fit_transform(X)

        # Train Isolation Forest
        self.model = IsolationForest(
            n_estimators=self.n_estimators,
            contamination=self.contamination,
            random_state=self.random_state,
            n_jobs=-1  # use all CPU cores
        )
        self.model.fit(X_scaled)
        self.is_trained = True

        elapsed = time.time() - start
        stats = {
            'rows_trained': len(X_scaled),
            'features': len(self.feature_names),
            'training_time_seconds': round(elapsed, 2),
            'feature_names': self.feature_names
        }
        return stats

    def train_from_tlog(self, filepath: str, drone_id: str = "drone_0") -> Dict[str, Any]:
        """
        Convenience method: parse a .tlog file and train the model.
        """
        from telemetry import extract_telemetry_from_file
        telemetry = extract_telemetry_from_file(filepath)
        return self.train(telemetry)

    def detect(self, telemetry: Dict[str, pd.DataFrame], percentile_threshold: float = 3.0) -> List[Dict[str, Any]]:
        """
        Run anomaly detection on new telemetry data.

        Args:
            telemetry: Dict of DataFrames (same format as training).
            percentile_threshold: Flag the bottom N% of scores as anomalies.
                                 Default 3.0 means the most anomalous 3% of
                                 readings are flagged. Lower = fewer, more
                                 confident detections.

        Returns:
            List of anomaly event dicts with timestamp, score, and 
            top contributing features.
        """
        if not self.is_trained:
            return []

        merged = _merge_telemetry_streams(telemetry)
        featured = _engineer_features(merged)

        # Ensure we have the same features as training
        missing = [f for f in self.feature_names if f not in featured.columns]
        for col in missing:
            featured[col] = 0.0

        X = featured[self.feature_names].values
        timestamps = featured['timestamp'].values

        # Handle NaN
        valid_mask = ~np.isnan(X).any(axis=1)
        X_valid = X[valid_mask]
        ts_valid = timestamps[valid_mask]

        if len(X_valid) == 0:
            return []

        X_scaled = self.scaler.transform(X_valid)

        # Get anomaly scores (more negative = more anomalous)
        scores = self.model.decision_function(X_scaled)

        # Adaptive threshold: flag the bottom percentile_threshold% of scores
        score_cutoff = np.percentile(scores, percentile_threshold)

        # Compute severity tiers from score distribution
        p1 = np.percentile(scores, 1.0)   # bottom 1% = CRITICAL
        p2 = np.percentile(scores, 2.0)   # bottom 2% = HIGH

        anomalies = []
        for i in range(len(X_valid)):
            if scores[i] <= score_cutoff:
                # Find top contributing features by deviation from mean
                deviations = np.abs(X_scaled[i])
                top_indices = np.argsort(deviations)[-3:][::-1]  # top 3
                top_features = [
                    f"{self.feature_names[idx]} ({deviations[idx]:.1f}σ)"
                    for idx in top_indices
                ]

                anomalies.append({
                    'timestamp': float(ts_valid[i]),
                    'event_type': 'MLAnomaly',
                    'severity': 'CRITICAL' if scores[i] <= p1 else 'HIGH' if scores[i] <= p2 else 'MEDIUM',
                    'score': round(float(scores[i]), 4),
                    'detail': f"ML anomaly detected (score: {scores[i]:.4f}, "
                             f"cutoff: {score_cutoff:.4f}). "
                             f"Top deviations: {', '.join(top_features)}",
                    'recommendation': "Review telemetry around this timestamp. "
                                    "Pattern deviates from learned normal baseline."
                })

        return anomalies

    def save(self, path: str = None) -> str:
        """Save the trained model, scaler, and feature names to disk."""
        if not self.is_trained:
            raise RuntimeError("Model not trained yet. Call train() first.")

        path = path or self.DEFAULT_MODEL_PATH
        model_dir = os.path.dirname(path)
        if model_dir and not os.path.exists(model_dir):
            os.makedirs(model_dir, exist_ok=True)

        payload = {
            'model': self.model,
            'scaler': self.scaler,
            'feature_names': self.feature_names,
            'contamination': self.contamination,
            'n_estimators': self.n_estimators
        }
        joblib.dump(payload, path)
        return path

    @classmethod
    def load(cls, path: str = None) -> 'MLAnomalyDetector':
        """Load a trained model from disk."""
        path = path or cls.DEFAULT_MODEL_PATH
        if not os.path.exists(path):
            raise FileNotFoundError(f"No trained model found at {path}. Run train_model.py first.")

        payload = joblib.load(path)
        detector = cls(
            contamination=payload['contamination'],
            n_estimators=payload['n_estimators']
        )
        detector.model = payload['model']
        detector.scaler = payload['scaler']
        detector.feature_names = payload['feature_names']
        detector.is_trained = True
        return detector
