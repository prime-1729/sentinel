import pandas as pd
from dataclasses import dataclass
from typing import List

@dataclass
class AnomalyEvent:
    """
    A single detected anomaly during a mission.
    """
    event_type: str
    timestamp: float
    severity: str        # LOW, MEDIUM, HIGH, CRITICAL
    detail: str
    recommendation: str


def run_all_detectors(telemetry: dict, enable_ml: bool = True, model_path: str = None) -> List[AnomalyEvent]:
    """
    Run anomaly detectors against a telemetry dataset using Machine Learning.
    
    Args:
        telemetry: Dict of DataFrames with telemetry data.
        enable_ml: Must be True (ML is the only supported detection mechanism).
        model_path: Path to trained ML model. If None, uses default location.
    
    Returns combined sorted list of all detected anomalies.
    """
    all_anomalies = []
    
    if not enable_ml:
        print("Warning: ML detection disabled. No anomalies will be detected.")
        return all_anomalies
        
    try:
        from ml_models.ml_detector import MLAnomalyDetector
        detector = MLAnomalyDetector.load(model_path)
        ml_results = detector.detect(telemetry)
        for ml_event in ml_results:
            all_anomalies.append(AnomalyEvent(
                event_type=ml_event['event_type'],
                timestamp=ml_event['timestamp'],
                severity=ml_event['severity'],
                detail=ml_event['detail'],
                recommendation=ml_event['recommendation']
            ))
    except FileNotFoundError:
        pass  # No trained model available
    except Exception as e:
        print(f"ML detector error: {e}")
    
    try:
        from . import propulsion, power, navigation, flight_dynamics, electronic_warfare
        all_anomalies.extend(propulsion.detect(telemetry))
        all_anomalies.extend(power.detect(telemetry))
        all_anomalies.extend(navigation.detect(telemetry))
        all_anomalies.extend(flight_dynamics.detect(telemetry))
        all_anomalies.extend(electronic_warfare.detect(telemetry))
    except Exception as e:
        print(f"Domain detector error: {e}")
        
    # Sort by timestamp
    all_anomalies.sort(key=lambda x: x.timestamp)
    
    return all_anomalies


def store_anomalies(anomalies: List[AnomalyEvent], drone_id: str, mission_id: str, db_path: str = "data/sentinel.db") -> int:
    """
    Helper function to store detected anomalies into the SQLite database.
    """
    if not anomalies:
        return 0
        
    from telemetry_store import TelemetryStore
    store = TelemetryStore(db_path=db_path)
    
    # Convert dataclass objects to dicts for the store method
    anomaly_dicts = [
        {
            'timestamp': a.timestamp,
            'event_type': a.event_type,
            'severity': a.severity,
            'detail': a.detail,
            'recommendation': a.recommendation
        }
        for a in anomalies
    ]
    
    count = store.ingest_anomalies(anomaly_dicts, drone_id=drone_id, mission_id=mission_id)
    store.close()
    return count


def print_anomaly_report(anomalies: List[AnomalyEvent]):
    """
    Print detected anomalies in a readable format.
    """
    if len(anomalies) == 0:
        print("\nSENTINEL: No anomalies detected. Mission nominal.")
        return
    
    print(f"\nSENTINEL: {len(anomalies)} anomaly/anomalies detected:")
    print("-" * 50)
    
    for a in anomalies:
        print(f"\n[{a.severity}] {a.event_type}")
        print(f"  Detail: {a.detail}")
        print(f"  Action: {a.recommendation}")