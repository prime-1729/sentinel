#!/usr/bin/env python3
"""
Train the ML anomaly detection model from a .tlog flight log.

Usage:
    python scripts/train_model.py --tlog data/test_mission.tlog
    python scripts/train_model.py --tlog data/test_mission.tlog --output data/ml_model.joblib
"""

import argparse
import sys
import os

# Add project root to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from ml_detector import MLAnomalyDetector


def main():
    parser = argparse.ArgumentParser(description='Train SENTINEL ML anomaly detector')
    parser.add_argument('--tlog', required=True, help='Path to .tlog file for training')
    parser.add_argument('--output', default='data/ml_model.joblib', help='Path to save trained model')
    parser.add_argument('--contamination', default='auto', help='Expected anomaly fraction (default: auto)')
    parser.add_argument('--estimators', type=int, default=100, help='Number of isolation trees (default: 100)')
    args = parser.parse_args()

    if not os.path.exists(args.tlog):
        print(f"Error: tlog file not found: {args.tlog}")
        sys.exit(1)

    print(f"SENTINEL ML Model Training")
    print(f"{'='*50}")
    print(f"  Input:         {args.tlog}")
    print(f"  Output:        {args.output}")
    print(f"  Contamination: {args.contamination}")
    print(f"  Estimators:    {args.estimators}")
    print()

    contamination = args.contamination if args.contamination == 'auto' else float(args.contamination)

    detector = MLAnomalyDetector(
        contamination=contamination,
        n_estimators=args.estimators
    )

    print("Parsing tlog and extracting telemetry...")
    stats = detector.train_from_tlog(args.tlog)

    print(f"\nTraining complete:")
    print(f"  Rows trained:   {stats['rows_trained']:,}")
    print(f"  Features:       {stats['features']}")
    print(f"  Training time:  {stats['training_time_seconds']:.2f}s")

    model_path = detector.save(args.output)
    model_size = os.path.getsize(model_path) / (1024 * 1024)
    print(f"\nModel saved:")
    print(f"  Path: {model_path}")
    print(f"  Size: {model_size:.2f} MB")
    print(f"\nDone. Use MLAnomalyDetector.load('{model_path}') to load the model.")


if __name__ == '__main__':
    main()
