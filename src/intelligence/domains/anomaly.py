import os
import time
import pandas as pd
import numpy as np
import logging
from dataclasses import dataclass
from typing import List, Dict, Any, Optional

logger = logging.getLogger("sentinel.intelligence.anomaly")

@dataclass
class AnomalyEvent:
    """A single detected anomaly during a mission."""
    event_type: str
    timestamp: float
    severity: str        # LOW, MEDIUM, HIGH, CRITICAL
    detail: str
    recommendation: str
    domain: str = "unknown"

class AnomalyPipeline:
    """
    Two-layer ML anomaly detection pipeline.
    Layer 1: Isolation Forest (fast triage)
    Layer 2: LSTM Autoencoder (deep temporal confirmation)
    Layer 3: Domain Classifier (fault identification)
    """
    def __init__(self, models_dir: str = "data/models"):
        self.models_dir = models_dir
        self.if_model = None
        self.lstm_model = None
        self.domain_model = None
        self.load_models()
        
        from .propulsion import PropulsionDetector
        from .power import PowerDetector
        from .navigation import NavigationDetector
        from .flight_dynamics import FlightDynamicsDetector
        from .electronic_warfare import EWDetector
        
        self.domain_detectors = [
            PropulsionDetector(),
            PowerDetector(),
            NavigationDetector(),
            FlightDynamicsDetector(),
            EWDetector()
        ]
        
    def load_models(self):
        try:
            from ..ml_models.isolation_forest import MLAnomalyDetector
            if_path = os.path.join(self.models_dir, "isolation_forest.joblib")
            if os.path.exists(if_path):
                self.if_model = MLAnomalyDetector.load(if_path)
                logger.info("Loaded Isolation Forest (Layer 1)")
        except Exception as e:
            logger.error(f"Failed to load Layer 1 model: {e}")
            
        try:
            from ..ml_models.lstm_autoencoder import LSTMAutoencoder
            lstm_path = os.path.join(self.models_dir, "lstm_ae.onnx")
            if os.path.exists(lstm_path):
                self.lstm_model = LSTMAutoencoder.load_onnx(lstm_path)
                logger.info("Loaded LSTM Autoencoder (Layer 2)")
        except Exception as e:
            logger.error(f"Failed to load Layer 2 model: {e}")
            
        try:
            from ..ml_models.domain_classifier import DomainClassifier
            dc_path = os.path.join(self.models_dir, "domain_classifier.joblib")
            if os.path.exists(dc_path):
                self.domain_model = DomainClassifier.load(dc_path)
                logger.info("Loaded Domain Classifier (Layer 3)")
        except Exception as e:
            logger.error(f"Failed to load Layer 3 model: {e}")

    def _extract_features_for_timestamp(self, telemetry: dict, timestamp: float) -> Optional[np.ndarray]:
        """Extract a single feature vector for the given timestamp."""
        # Simple helper to get the closest row to the timestamp
        try:
            # We assume IF model has feature engineering logic we can reuse
            from ..ml_models.isolation_forest import _merge_telemetry_streams, _engineer_features
            merged = _merge_telemetry_streams(telemetry)
            featured = _engineer_features(merged)
            
            # Find closest row
            idx = (np.abs(featured['timestamp'] - timestamp)).idxmin()
            
            if self.domain_model and self.domain_model.feature_names:
                row = featured.iloc[idx]
                features = np.zeros(len(self.domain_model.feature_names))
                for i, name in enumerate(self.domain_model.feature_names):
                    if name in row:
                        features[i] = row[name]
                return features
            return None
        except Exception:
            return None

    def _extract_sequence_for_timestamp(self, telemetry: dict, timestamp: float, seq_length: int = 30) -> Optional[np.ndarray]:
        """Extract a sequence of features leading up to the timestamp for LSTM."""
        try:
            from ..ml_models.isolation_forest import _merge_telemetry_streams, _engineer_features
            merged = _merge_telemetry_streams(telemetry)
            featured = _engineer_features(merged)
            
            # Find closest row
            idx = (np.abs(featured['timestamp'] - timestamp)).idxmin()
            # We want seq_length rows ending at idx
            start_idx = max(0, idx - seq_length + 1)
            
            if self.lstm_model and self.lstm_model.n_features:
                # We need exactly seq_length. If not enough data, pad it or return None.
                if idx - start_idx + 1 < seq_length:
                    return None
                    
                seq_df = featured.iloc[start_idx:idx+1]
                # Assuming the features are the first n_features columns (excluding timestamp if not used, but let's assume all numeric cols)
                # Or better, if we have domain model features we could use those, but LSTM might use different features.
                # Let's just grab the first n_features numeric columns.
                numeric_cols = seq_df.select_dtypes(include=[np.number]).columns
                if len(numeric_cols) >= self.lstm_model.n_features:
                    seq_features = seq_df[numeric_cols[:self.lstm_model.n_features]].values
                    # Shape: (1, seq_length, n_features) for batch size 1
                    return np.expand_dims(seq_features, axis=0)
            return None
        except Exception:
            return None

    def run(self, telemetry: Dict[str, pd.DataFrame]) -> List[AnomalyEvent]:
        anomalies = []
        
        # 0. Physics-based domain detectors
        domain_anomalies = []
        if hasattr(self, 'domain_detectors'):
            for detector in self.domain_detectors:
                try:
                    domain_anomalies.extend(detector.detect(telemetry))
                except Exception as e:
                    logger.error(f"Domain detector {detector.__class__.__name__} failed: {e}")
                    
        anomalies.extend(domain_anomalies)
        
        # Layer 1: Isolation Forest
        if not self.if_model:
            return anomalies
            
        layer1_events = self.if_model.detect(telemetry)
        
        if not layer1_events:
            return anomalies
            
        logger.warning(f"Layer 1 flagged {len(layer1_events)} anomalies. Running deeper analysis.")
        
        # We only need to run Layer 2 / Layer 3 on the anomalous timestamps
        for event in layer1_events:
            confirmed = False
            severity = event['severity']
            detail = event['detail']
            recommendation = event['recommendation']
            
            # Layer 2: LSTM Confirmation (if available)
            if self.lstm_model:
                seq = self._extract_sequence_for_timestamp(telemetry, event['timestamp'], seq_length=self.lstm_model.sequence_length)
                if seq is not None:
                    # detect() returns a list of results per batch element
                    lstm_results = self.lstm_model.detect(seq)
                    if lstm_results and lstm_results[0]['is_anomaly']:
                        confirmed = True
                        detail += f" | LSTM confirmed (MSE: {lstm_results[0]['reconstruction_error']:.4f})"
                    else:
                        confirmed = False
                else:
                    # If we can't extract sequence, default to True based on Layer 1
                    confirmed = True
            else:
                # If no Layer 2, rely on Layer 1
                confirmed = True
                
            if confirmed:
                domain = "unknown"
                
                # Layer 3: Domain Classification
                if self.domain_model:
                    features = self._extract_features_for_timestamp(telemetry, event['timestamp'])
                    if features is not None:
                        classification = self.domain_model.classify(features)
                        domain = classification['domain']
                        conf = classification['confidence']
                        
                        if conf > 0.6:
                            detail += f" | Fault identified as: {domain.upper()} (conf: {conf:.2f})"
                            # Let the autonomous reaction engine handle specific actions based on the domain.
                            # We keep the specific recommendation from the detector.
                
                anomalies.append(AnomalyEvent(
                    event_type=f"{domain.capitalize()}Anomaly" if domain != "unknown" else event['event_type'],
                    timestamp=event['timestamp'],
                    severity=severity,
                    detail=detail,
                    recommendation=recommendation,
                    domain=domain
                ))
                
        return anomalies

# Global instance for easy importing
_pipeline = None

def run_all_detectors(telemetry: dict) -> List[AnomalyEvent]:
    global _pipeline
    if _pipeline is None:
        _pipeline = AnomalyPipeline()
        
    return _pipeline.run(telemetry)