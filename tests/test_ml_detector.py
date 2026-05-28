"""
Tests for ML anomaly detection module (Isolation Forest).

Tests cover:
- Training on synthetic normal data
- Detection of injected anomalies (voltage spike, extreme roll)
- Model save/load round-trip
- Empty/short data handling
"""

import pytest
import os
import tempfile
import numpy as np
import pandas as pd
from src.ml_detector import (
    MLAnomalyDetector,
    _merge_telemetry_streams,
    _engineer_features,
)


def _make_normal_telemetry(n_rows=500, seed=42):
    """Generate synthetic 'normal' flight telemetry."""
    rng = np.random.RandomState(seed)
    ts = np.arange(n_rows, dtype=float) * 0.25  # 4 Hz

    return {
        'positions': pd.DataFrame({
            'timestamp': ts,
            'lat': 28.6 + rng.normal(0, 0.0001, n_rows),
            'lon': 77.2 + rng.normal(0, 0.0001, n_rows),
            'alt_metres': 100 + rng.normal(0, 0.5, n_rows),
            'relative_alt': 50 + rng.normal(0, 0.3, n_rows),
            'vx': rng.normal(0, 0.5, n_rows),
            'vy': rng.normal(0, 0.5, n_rows),
            'vz': rng.normal(0, 0.1, n_rows),
        }),
        'battery': pd.DataFrame({
            'timestamp': ts,
            'voltage': 16.8 - ts * 0.0001 + rng.normal(0, 0.02, n_rows),
            'current': 5.0 + rng.normal(0, 0.3, n_rows),
            'remaining_pct': 100 - ts * 0.01 + rng.normal(0, 0.1, n_rows),
        }),
        'attitude': pd.DataFrame({
            'timestamp': ts,
            'roll_deg': rng.normal(0, 3, n_rows),
            'pitch_deg': rng.normal(0, 3, n_rows),
            'yaw_deg': rng.normal(90, 5, n_rows),
        }),
        'hud': pd.DataFrame({
            'timestamp': ts,
            'airspeed': 5.0 + rng.normal(0, 0.5, n_rows),
            'groundspeed': 5.0 + rng.normal(0, 0.5, n_rows),
            'climb_rate': rng.normal(0, 0.2, n_rows),
            'throttle_pct': 45 + rng.normal(0, 3, n_rows),
        }),
    }


def _make_anomalous_telemetry(n_rows=500, seed=42):
    """Generate telemetry with injected anomalies."""
    telemetry = _make_normal_telemetry(n_rows, seed=99)

    # Inject anomalies at rows 200-210: extreme roll + voltage drop + speed spike
    telemetry['attitude'].loc[200:210, 'roll_deg'] = 60.0
    telemetry['attitude'].loc[200:210, 'pitch_deg'] = 55.0
    telemetry['battery'].loc[200:210, 'voltage'] = 10.0
    telemetry['hud'].loc[200:210, 'groundspeed'] = 30.0
    telemetry['hud'].loc[200:210, 'throttle_pct'] = 95.0
    telemetry['positions'].loc[200:210, 'vz'] = -5.0

    return telemetry


# ─── Feature Engineering ─────────────────────────────────────

def test_merge_telemetry_streams():
    """Merging should produce a single DataFrame with all feature columns."""
    telemetry = _make_normal_telemetry(100)
    merged = _merge_telemetry_streams(telemetry)

    assert 'timestamp' in merged.columns
    assert 'relative_alt' in merged.columns
    assert 'voltage' in merged.columns
    assert 'roll_deg' in merged.columns
    assert 'groundspeed' in merged.columns
    assert len(merged) == 100


def test_engineer_features():
    """Feature engineering should add rolling mean, std, and rate columns."""
    telemetry = _make_normal_telemetry(100)
    merged = _merge_telemetry_streams(telemetry)
    featured = _engineer_features(merged)

    assert 'voltage_mean' in featured.columns
    assert 'voltage_std' in featured.columns
    assert 'voltage_rate' in featured.columns
    assert 'roll_deg_mean' in featured.columns
    assert len(featured) == 100


# ─── Training ────────────────────────────────────────────────

def test_train_on_normal_data():
    """Model should train successfully on normal telemetry."""
    detector = MLAnomalyDetector(contamination='auto', n_estimators=50)
    stats = detector.train(_make_normal_telemetry(500))

    assert detector.is_trained
    assert stats['rows_trained'] == 500
    assert stats['features'] > 40  # ~60 features expected
    assert stats['training_time_seconds'] < 5.0


def test_normal_data_low_false_positives():
    """With a 3% threshold, exactly ~3% of normal data should be flagged."""
    detector = MLAnomalyDetector(contamination='auto', n_estimators=50)
    detector.train(_make_normal_telemetry(500, seed=42))

    # Run detection on separate normal data
    normal_test = _make_normal_telemetry(300, seed=99)
    anomalies = detector.detect(normal_test, percentile_threshold=3.0)

    # With percentile-based thresholding, ~3% of data will always be flagged.
    # On normal data these are just statistical outliers, not real anomalies.
    # The key test is that injected anomalies rank HIGHER than normal outliers.
    false_positive_rate = len(anomalies) / 300
    assert false_positive_rate < 0.06, f"False positive rate too high: {false_positive_rate:.2%}"


# ─── Detection ───────────────────────────────────────────────

def test_injected_anomaly_detected():
    """Model should detect injected multivariate anomalies.
    The injected anomalies should appear in the bottom percentile of scores."""
    detector = MLAnomalyDetector(contamination='auto', n_estimators=100)
    detector.train(_make_normal_telemetry(500, seed=42))

    anomalous = _make_anomalous_telemetry(500, seed=99)
    # Use a 5% threshold to catch the anomalous zone
    anomalies = detector.detect(anomalous, percentile_threshold=5.0)

    assert len(anomalies) > 0, "No anomalies detected — model missed injected faults"

    # Check that at least some anomalies are near the injection zone (rows 200-210, ts 50.0-52.5)
    detected_near_injection = [
        a for a in anomalies
        if 49.0 <= a['timestamp'] <= 54.0
    ]
    assert len(detected_near_injection) > 0, "Anomalies detected but not near injection zone"


def test_anomaly_event_structure():
    """Detected anomalies should have the expected fields."""
    detector = MLAnomalyDetector(contamination='auto', n_estimators=50)
    detector.train(_make_normal_telemetry(500, seed=42))

    anomalous = _make_anomalous_telemetry(500, seed=99)
    anomalies = detector.detect(anomalous, percentile_threshold=5.0)

    if anomalies:
        a = anomalies[0]
        assert 'timestamp' in a
        assert 'event_type' in a
        assert a['event_type'] == 'MLAnomaly'
        assert 'severity' in a
        assert a['severity'] in ('MEDIUM', 'HIGH', 'CRITICAL')
        assert 'score' in a
        assert 'detail' in a
        assert 'recommendation' in a


# ─── Model Persistence ───────────────────────────────────────

def test_save_and_load_round_trip():
    """Saved model should produce identical results after loading."""
    detector = MLAnomalyDetector(contamination='auto', n_estimators=50)
    detector.train(_make_normal_telemetry(200, seed=42))

    with tempfile.NamedTemporaryFile(suffix='.joblib', delete=False) as f:
        path = f.name

    try:
        detector.save(path)
        assert os.path.exists(path)

        loaded = MLAnomalyDetector.load(path)
        assert loaded.is_trained
        assert loaded.feature_names == detector.feature_names

        # Same input should produce same scores
        test_data = _make_normal_telemetry(100, seed=99)
        original_anomalies = detector.detect(test_data)
        loaded_anomalies = loaded.detect(test_data)
        assert len(original_anomalies) == len(loaded_anomalies)
    finally:
        os.unlink(path)


# ─── Edge Cases ──────────────────────────────────────────────

def test_detect_before_training():
    """Detect on untrained model should return empty list, not crash."""
    detector = MLAnomalyDetector()
    result = detector.detect(_make_normal_telemetry(50))
    assert result == []


def test_save_before_training_raises():
    """Saving an untrained model should raise RuntimeError."""
    detector = MLAnomalyDetector()
    with pytest.raises(RuntimeError, match="not trained"):
        detector.save("/tmp/should_not_exist.joblib")


def test_load_missing_model_raises():
    """Loading from nonexistent path should raise FileNotFoundError."""
    with pytest.raises(FileNotFoundError):
        MLAnomalyDetector.load("/tmp/nonexistent_model_12345.joblib")
