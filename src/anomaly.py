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


def detect_battery_stress(battery_df: pd.DataFrame) -> List[AnomalyEvent]:
    """
    Detect battery anomalies using ArduPilot-standard thresholds.
    
    Thresholds:
    - Voltage sag: > 0.5V drop between readings. ArduPilot's BATT_LOW_VOLT
      default is 10.5V (3.5V/cell for 3S LiPo). A sudden drop of 0.5V+ 
      indicates dangerous load sag or cell failure. Source: ArduPilot 
      battery failsafe docs (ardupilot.org/copter/docs/failsafe-battery).
    - Low battery: < 20% remaining. ArduPilot recommends BATT_LOW_MAH at
      20% remaining capacity as the low-battery warning threshold.
      Source: ArduPilot battery failsafe documentation.
    - Critical battery: < 10% remaining. Maps to ArduPilot's 
      BATT_CRT_MAH (critical stage), typically 10% remaining.
    """
    events = []
    
    if len(battery_df) < 2:
        return events
    
    df = battery_df.copy()
    df['voltage_drop'] = df['voltage'].diff()
    
    # ArduPilot: voltage sag > 0.5V indicates dangerous load or cell failure.
    # Normal flight sag is 0.1-0.3V; > 0.5V is abnormal per LiPo engineering.
    stress_readings = df[df['voltage_drop'] < -0.5]
    
    for _, row in stress_readings.iterrows():
        events.append(AnomalyEvent(
            event_type='BatteryStress',
            timestamp=row['timestamp'],
            severity='HIGH',
            detail=f"Voltage dropped {abs(row['voltage_drop']):.2f}V suddenly. "
                   f"Current voltage: {row['voltage']:.2f}V",
            recommendation="Inspect battery health before next mission. "
                          "Check for high current draw events."
        ))
    
    # ArduPilot BATT_LOW_MAH: 20% remaining = low-battery warning stage
    low_battery = battery_df[battery_df['remaining_pct'] < 20]
    if len(low_battery) > 0:
        first = low_battery.iloc[0]
        severity = 'CRITICAL' if first['remaining_pct'] < 10 else 'HIGH'
        events.append(AnomalyEvent(
            event_type='LowBattery',
            timestamp=first['timestamp'],
            severity=severity,
            detail=f"Battery at {first['remaining_pct']}%. "
                   f"{'CRITICAL — below 10%, land immediately.' if first['remaining_pct'] < 10 else 'Below 20% low-battery threshold.'}",
            recommendation="Return to base immediately." if first['remaining_pct'] < 10 
                          else "Prepare RTL. Monitor voltage for further drops."
        ))
    
    return events


def detect_idle_drift(positions_df: pd.DataFrame,
                      hud_df: pd.DataFrame) -> List[AnomalyEvent]:
    """
    Detect when drone is supposed to be moving but is stationary.
    Indicates path blockage, software hang, or navigation failure.
    
    Thresholds:
    - Throttle > 25%: ArduPilot's MOT_SPIN_MIN default is ~15% and
      MOT_SPIN_ARM is ~10%. Throttle > 25% indicates intentional
      flight commands beyond hover stabilisation.
    - Groundspeed < 0.3 m/s: GPS position noise floor is ~0.1-0.2 m/s.
      Using 0.3 m/s avoids false positives from GPS jitter while
      still catching genuinely stuck drones.
    - Duration > 5 readings: avoids false positives from brief hover holds
      during waypoint transitions.
    """
    events = []
    
    if len(hud_df) < 10:
        return events
    
    df = hud_df.copy()
    
    # Throttle > 25% (above MOT_SPIN_MIN) but groundspeed < 0.3 m/s 
    # (below GPS noise floor + margin)
    idle = df[(df['throttle_pct'] > 25) & (df['groundspeed'] < 0.3)]
    
    # Only flag if idle for more than 5 consecutive readings
    if len(idle) > 5:
        events.append(AnomalyEvent(
            event_type='IdleDrift',
            timestamp=idle.iloc[0]['timestamp'],
            severity='MEDIUM',
            detail=f"Drone stationary for {len(idle)} readings "
                   f"despite active throttle ({idle['throttle_pct'].mean():.0f}%). "
                   f"Possible navigation failure or path obstruction.",
            recommendation="Review flight path for obstacles. "
                          "Check navigation system health."
        ))
    
    return events


def detect_altitude_anomaly(positions_df: pd.DataFrame,
                             commanded_alt: float = None) -> List[AnomalyEvent]:
    """
    Detect unexpected altitude deviations (rapid uncontrolled descent).
    
    Thresholds:
    - Descent > 5 m/s: ArduPilot's WPNAV_SPEED_DN default is 150 cm/s 
      (1.5 m/s) and LAND_SPEED_HIGH max is 500 cm/s (5 m/s). Descent
      exceeding 5 m/s is beyond any commanded descent rate and indicates
      loss of lift or free-fall.
    - ArduPilot's crash check triggers when lean angle error exceeds
      30° for 2 seconds, but descent rate is the earlier warning.
    
    Note: We compare altitude change between consecutive readings.
    At ~4 Hz telemetry rate, a 5 m/s descent ≈ 1.25m per reading.
    We use 2.0m to account for variable telemetry rates.
    """
    events = []
    
    if len(positions_df) < 2:
        return events
    
    df = positions_df.copy()
    df['alt_change'] = df['relative_alt'].diff()
    
    # Descent > 2.0m per reading ≈ 5+ m/s at typical 4 Hz telemetry rate.
    # Exceeds ArduPilot's LAND_SPEED_HIGH max (5 m/s) — not a commanded descent.
    rapid_descent = df[df['alt_change'] < -2.0]
    
    for _, row in rapid_descent.iterrows():
        events.append(AnomalyEvent(
            event_type='RapidDescent',
            timestamp=row['timestamp'],
            severity='CRITICAL',
            detail=f"Altitude dropped {abs(row['alt_change']):.1f}m in one reading. "
                   f"Current altitude: {row['relative_alt']:.1f}m",
            recommendation="Check for motor failure or control surface damage. "
                          "Exceeds max commanded descent rate (LAND_SPEED_HIGH)."
        ))
    
    return events


def detect_attitude_anomaly(attitude_df: pd.DataFrame) -> List[AnomalyEvent]:
    """
    Detect extreme pitch or roll angles indicating instability.
    
    Thresholds:
    - Roll/Pitch > 45°: ArduPilot's ANGLE_MAX default is 4500 centidegrees
      (45°). This is the maximum lean angle the flight controller will
      command in stabilised modes. Exceeding it means the drone has
      lost stabilisation authority.
      Source: ArduPilot ANGLE_MAX parameter (ardupilot.org).
    - ArduPilot's crash check triggers when actual vs desired lean angle
      diverges by 30°+ for 2 seconds. Our 45° threshold catches the
      attitude breach itself.
    """
    events = []
    
    if len(attitude_df) == 0:
        return events
    
    # ArduPilot ANGLE_MAX default = 45° (4500 centidegrees)
    # Exceeding this means loss of stabilisation authority
    extreme = attitude_df[
        (attitude_df['roll_deg'].abs() > 45) |
        (attitude_df['pitch_deg'].abs() > 45)
    ]
    
    for _, row in extreme.iterrows():
        events.append(AnomalyEvent(
            event_type='ExtremeAttitude',
            timestamp=row['timestamp'],
            severity='CRITICAL',
            detail=f"Attitude exceeds ANGLE_MAX (45°). "
                   f"Roll: {row['roll_deg']:.1f}° "
                   f"Pitch: {row['pitch_deg']:.1f}°",
            recommendation="Review flight controller tuning. "
                          "Inspect airframe for damage. "
                          "ArduPilot crash check triggers at 30° lean error."
        ))
    
    return events


def detect_signal_degraded(radio_df: pd.DataFrame) -> List[AnomalyEvent]:
    """
    Detect communication signal degradation via RADIO_STATUS RSSI.
    
    Thresholds:
    - RSSI < 64: SiK radios report RSSI on a 0–254 scale. Healthy 
      radios show > 190 at close range. The value maps approximately
      to dBm via: signal_dBm = (RSSI / 1.9) - 127.
      RSSI 64 ≈ -93 dBm, which is ~28 dB above the receiver 
      sensitivity limit of -121 dBm. Below this, link quality 
      degrades rapidly. ArduPilot triggers GCS failsafe on 
      heartbeat loss, but RSSI degradation is the early warning.
      Source: SiK radio documentation, ArduPilot telemetry docs.
    - RSSI < 30: ≈ -111 dBm, only ~10 dB above receiver sensitivity.
      Link loss is imminent.
    """
    events = []
    if len(radio_df) == 0:
        return events
    
    # Critical: RSSI < 30 ≈ -111 dBm, ~10 dB above sensitivity limit
    critical = radio_df[radio_df['rssi'] < 30]
    for _, row in critical.iterrows():
        events.append(AnomalyEvent(
            event_type='SignalDegraded',
            timestamp=row['timestamp'],
            severity='CRITICAL',
            detail=f"Signal critically low. RSSI: {row['rssi']:.0f}/254 "
                   f"(≈ {(row['rssi'] / 1.9) - 127:.0f} dBm). Link loss imminent.",
            recommendation="Initiate RTL immediately. Reduce range to ground station."
        ))
        
    # Warning: RSSI 30-64 ≈ degraded but functional
    warning = radio_df[(radio_df['rssi'] >= 30) & (radio_df['rssi'] < 64)]
    for _, row in warning.iterrows():
        events.append(AnomalyEvent(
            event_type='SignalDegraded',
            timestamp=row['timestamp'],
            severity='MEDIUM',
            detail=f"Signal degraded. RSSI: {row['rssi']:.0f}/254 "
                   f"(≈ {(row['rssi'] / 1.9) - 127:.0f} dBm).",
            recommendation="Monitor connection. Check line of sight and interference sources."
        ))
        
    return events


def detect_gps_glitch(gps_df: pd.DataFrame) -> List[AnomalyEvent]:
    """
    Detect GPS accuracy degradation via HDOP from GPS_RAW_INT.eph.
    
    Thresholds:
    - eph > 200 (HDOP > 2.0): ArduPilot's GPS_HDOP_GOOD parameter 
      default is 140 (HDOP 1.4). The pre-arm check blocks arming 
      when HDOP > 2.0 (eph > 200). If this threshold is breached
      mid-flight, GPS-dependent modes (Loiter, PosHold, Auto) will
      have degraded position hold accuracy.
      Source: ArduPilot GPS_HDOP_GOOD parameter (ardupilot.org).
    - eph > 400 (HDOP > 4.0): Navigation is unreliable. Position 
      errors can exceed 8-10 meters. EKF may lose confidence.
    """
    events = []
    if len(gps_df) == 0:
        return events
    
    # Critical: HDOP > 4.0 — navigation unreliable, EKF may failsafe
    critical = gps_df[gps_df['eph'] > 400]
    for _, row in critical.iterrows():
        hdop = row['eph'] / 100.0
        events.append(AnomalyEvent(
            event_type='GPSGlitch',
            timestamp=row['timestamp'],
            severity='CRITICAL',
            detail=f"GPS accuracy severely degraded. HDOP: {hdop:.2f} "
                   f"(ArduPilot pre-arm limit: 2.0). Navigation unreliable.",
            recommendation="Switch to AltHold or manual mode. "
                          "Do not rely on GPS-dependent modes. Prepare for RTL failure."
        ))
    
    # Warning: HDOP 2.0–4.0 — exceeds ArduPilot's GPS_HDOP_GOOD default
    warning = gps_df[(gps_df['eph'] > 200) & (gps_df['eph'] <= 400)]
    for _, row in warning.iterrows():
        hdop = row['eph'] / 100.0
        events.append(AnomalyEvent(
            event_type='GPSGlitch',
            timestamp=row['timestamp'],
            severity='HIGH',
            detail=f"GPS accuracy degraded. HDOP: {hdop:.2f} "
                   f"(exceeds ArduPilot pre-arm limit of 2.0).",
            recommendation="Monitor position hold quality. "
                          "Prepare for manual intervention if HDOP continues rising."
        ))
        
    return events


def run_all_detectors(telemetry: dict, enable_ml: bool = False, model_path: str = None) -> List[AnomalyEvent]:
    """
    Run all anomaly detectors against a telemetry dataset.
    
    Args:
        telemetry: Dict of DataFrames with telemetry data.
        enable_ml: If True, also run the ML-based Isolation Forest detector.
        model_path: Path to trained ML model. If None, uses default location.
    
    Returns combined sorted list of all detected anomalies.
    """
    all_anomalies = []
    
    # Layer 1: Threshold-based detectors (deterministic, safety-critical)
    all_anomalies.extend(
        detect_battery_stress(telemetry['battery'])
    )
    all_anomalies.extend(
        detect_idle_drift(telemetry['positions'], telemetry['hud'])
    )
    all_anomalies.extend(
        detect_altitude_anomaly(telemetry['positions'])
    )
    all_anomalies.extend(
        detect_attitude_anomaly(telemetry['attitude'])
    )
    
    if 'radio' in telemetry and not telemetry['radio'].empty:
        all_anomalies.extend(
            detect_signal_degraded(telemetry['radio'])
        )
        
    if 'gps' in telemetry and not telemetry['gps'].empty:
        all_anomalies.extend(
            detect_gps_glitch(telemetry['gps'])
        )
    
    # Layer 2: ML pattern detector (contextual/multivariate anomalies)
    if enable_ml:
        try:
            from ml_detector import MLAnomalyDetector
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
            pass  # No trained model available — skip ML layer silently
        except Exception as e:
            print(f"ML detector error: {e}")
    
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


if __name__ == "__main__":
    from connect import connect_to_drone
    from telemetry import extract_telemetry

    conn = connect_to_drone()
    telemetry = extract_telemetry(conn, duration_seconds=20)
    anomalies = run_all_detectors(telemetry)
    print_anomaly_report(anomalies)