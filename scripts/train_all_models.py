#!/usr/bin/env python3
"""
Offline Training Pipeline for SENTINEL Intelligence Models.

This script trains:
1. Isolation Forest (Layer 1) - on normal data only
2. LSTM Autoencoder (Layer 2) - on normal data only
3. Domain Classifier (Layer 3) - on all data (supervised)
"""

import os
import sys
import numpy as np
import argparse
import logging
from typing import Dict, Any

# Add project root to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

try:
    from intelligence.ml_models.isolation_forest import MLAnomalyDetector
    from intelligence.ml_models.lstm_autoencoder import LSTMAutoencoder
    from intelligence.ml_models.domain_classifier import DomainClassifier
except ImportError as e:
    print(f"Error importing models: {e}")
    sys.exit(1)

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger("train_pipeline")

def create_mock_data(num_samples: int = 1000, n_features: int = 56):
    """Create mock data for pipeline testing if real data isn't available."""
    # Normal data
    X_normal = np.random.normal(0, 1, (num_samples, n_features))
    
    # Anomaly data
    X_anomaly = np.random.normal(3, 2, (num_samples // 5, n_features))
    
    # Generate mock labels for anomalies
    domains = ["propulsion", "power", "navigation", "dynamics", "ew"]
    y_anomaly = np.random.choice(domains, size=num_samples // 5)
    
    return X_normal, X_anomaly, y_anomaly

def train_pipeline(
    data_dir: str = "data/training/",
    output_dir: str = "data/models/",
    mock_data: bool = True
) -> Dict[str, Any]:
    
    os.makedirs(output_dir, exist_ok=True)
    results = {}
    
    logger.info("=== Starting SENTINEL Offline Training Pipeline ===")
    
    # 1. Load data
    if mock_data:
        logger.info("Using mock data for training...")
        X_normal, X_anomaly, y_anomaly = create_mock_data(n_features=25)
        feature_names = [f"feat_{i}" for i in range(25)]
    else:
        logger.error("Real data loading not fully implemented. Use --mock")
        return {}
        
    # 2. Train Isolation Forest (Layer 1)
    logger.info("\n--- Training Layer 1: Isolation Forest ---")
    if_model = MLAnomalyDetector()
    # Mock the internal logic just for saving since we didn't mock the dataframe logic fully
    if_model.is_trained = True
    from sklearn.ensemble import IsolationForest
    from sklearn.preprocessing import StandardScaler
    if_model.model = IsolationForest().fit(X_normal)
    if_model.scaler = StandardScaler().fit(X_normal)
    if_model.feature_names = feature_names
    if_model.optimal_threshold = -0.5
    
    if_path = os.path.join(output_dir, "isolation_forest.joblib")
    if_model.save(if_path)
    logger.info(f"Saved IF model to {if_path}")
    results["isolation_forest"] = "success"
    
    # 3. Train LSTM Autoencoder (Layer 2)
    logger.info("\n--- Training Layer 2: LSTM Autoencoder ---")
    try:
        # Create sequences for LSTM (num_samples, seq_len, features)
        seq_len = 10
        n_samples = len(X_normal) - seq_len
        X_seq = np.zeros((n_samples, seq_len, X_normal.shape[1]))
        for i in range(n_samples):
            X_seq[i] = X_normal[i:i+seq_len]
            
        lstm = LSTMAutoencoder(sequence_length=seq_len, n_features=X_normal.shape[1])
        lstm.train(X_seq, epochs=2) # Just 2 epochs for mock
        
        lstm_path = os.path.join(output_dir, "lstm_ae.onnx")
        lstm.export_onnx(lstm_path)
        logger.info(f"Saved LSTM-AE to {lstm_path}")
        results["lstm_ae"] = "success"
    except Exception as e:
        logger.error(f"LSTM-AE training failed: {e}")
        results["lstm_ae"] = f"failed: {e}"
        
    # 4. Train Domain Classifier (Layer 3)
    logger.info("\n--- Training Layer 3: Domain Classifier ---")
    try:
        dc = DomainClassifier()
        dc.train(X_anomaly, y_anomaly, feature_names)
        
        dc_path = os.path.join(output_dir, "domain_classifier.joblib")
        dc.save(dc_path)
        logger.info(f"Saved Domain Classifier to {dc_path}")
        results["domain_classifier"] = "success"
    except Exception as e:
        logger.error(f"Domain Classifier training failed: {e}")
        results["domain_classifier"] = f"failed: {e}"
        
    logger.info("\n=== Training Pipeline Complete ===")
    return results

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--mock", action="store_true", help="Use mock data", default=True)
    args = parser.parse_args()
    
    train_pipeline(mock_data=args.mock)
