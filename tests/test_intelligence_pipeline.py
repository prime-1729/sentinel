import pytest
import pandas as pd
import numpy as np
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
from intelligence.domains.anomaly import AnomalyPipeline
from intelligence.domains.propulsion import PropulsionDetector

def test_anomaly_pipeline_init():
    pipeline = AnomalyPipeline(models_dir="/tmp/nonexistent")
    assert len(pipeline.domain_detectors) == 5
    assert not pipeline.if_model
    assert not pipeline.lstm_model
    
def test_propulsion_detector():
    detector = PropulsionDetector()
    
    # Normal motors
    normal_telemetry = {
        "motors": pd.DataFrame({
            "timestamp": [1.0],
            "rpm_1": [5000], "rpm_2": [5000], "rpm_3": [5000], "rpm_4": [5000],
            "cur_1": [5.0], "cur_2": [5.0], "cur_3": [5.0], "cur_4": [5.0]
        })
    }
    anomalies = detector.detect(normal_telemetry)
    assert len(anomalies) == 0
    
    # Faulted motors
    faulted_telemetry = {
        "motors": pd.DataFrame({
            "timestamp": [1.0],
            "rpm_1": [2000], "rpm_2": [6000], "rpm_3": [6000], "rpm_4": [6000],
            "cur_1": [2.0], "cur_2": [6.0], "cur_3": [6.0], "cur_4": [6.0]
        })
    }
    anomalies = detector.detect(faulted_telemetry)
    assert len(anomalies) > 0
    assert any(a.domain == "propulsion" for a in anomalies)
