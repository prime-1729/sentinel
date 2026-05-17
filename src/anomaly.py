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
    Detect sudden voltage drops indicating battery stress.
    Real indicator of battery degradation or high current draw.
    """
    events = []
    
    if len(battery_df) < 2:
        return events
    
    df = battery_df.copy()
    df['voltage_drop'] = df['voltage'].diff()
    
    # Flag drops greater than 0.2V between readings
    stress_readings = df[df['voltage_drop'] < -0.2]
    
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
    
    # Flag low battery
    low_battery = battery_df[battery_df['remaining_pct'] < 20]
    if len(low_battery) > 0:
        first = low_battery.iloc[0]
        events.append(AnomalyEvent(
            event_type='LowBattery',
            timestamp=first['timestamp'],
            severity='CRITICAL',
            detail=f"Battery below 20%. Current: {first['remaining_pct']}%",
            recommendation="Return to base immediately."
        ))
    
    return events


def detect_idle_drift(positions_df: pd.DataFrame,
                      hud_df: pd.DataFrame) -> List[AnomalyEvent]:
    """
    Detect when drone is supposed to be moving but is stationary.
    Indicates path blockage, software hang, or navigation failure.
    """
    events = []
    
    if len(hud_df) < 10:
        return events
    
    df = hud_df.copy()
    
    # Find periods where throttle is active but groundspeed is zero
    # Throttle > 30% means drone is trying to do something
    # Groundspeed < 0.1 means it is not moving
    idle = df[(df['throttle_pct'] > 30) & (df['groundspeed'] < 0.1)]
    
    # Only flag if idle for more than 5 consecutive readings
    if len(idle) > 5:
        events.append(AnomalyEvent(
            event_type='IdleDrift',
            timestamp=idle.iloc[0]['timestamp'],
            severity='MEDIUM',
            detail=f"Drone stationary for {len(idle)} seconds "
                   f"despite active throttle ({idle['throttle_pct'].mean():.0f}%). "
                   f"Possible navigation failure or path obstruction.",
            recommendation="Review flight path for obstacles. "
                          "Check navigation system health."
        ))
    
    return events


def detect_altitude_anomaly(positions_df: pd.DataFrame,
                             commanded_alt: float = None) -> List[AnomalyEvent]:
    """
    Detect unexpected altitude deviations.
    """
    events = []
    
    if len(positions_df) < 2:
        return events
    
    df = positions_df.copy()
    df['alt_change'] = df['relative_alt'].diff()
    
    # Detect rapid uncontrolled descent (more than 3m per reading)
    rapid_descent = df[df['alt_change'] < -3.0]
    
    for _, row in rapid_descent.iterrows():
        events.append(AnomalyEvent(
            event_type='RapidDescent',
            timestamp=row['timestamp'],
            severity='CRITICAL',
            detail=f"Altitude dropped {abs(row['alt_change']):.1f}m suddenly. "
                   f"Current altitude: {row['relative_alt']:.1f}m",
            recommendation="Check for motor failure or control surface damage."
        ))
    
    return events


def detect_attitude_anomaly(attitude_df: pd.DataFrame) -> List[AnomalyEvent]:
    """
    Detect extreme pitch or roll angles indicating instability.
    """
    events = []
    
    if len(attitude_df) == 0:
        return events
    
    # Flag rolls or pitches beyond 45 degrees
    extreme = attitude_df[
        (attitude_df['roll_deg'].abs() > 45) |
        (attitude_df['pitch_deg'].abs() > 45)
    ]
    
    for _, row in extreme.iterrows():
        events.append(AnomalyEvent(
            event_type='ExtremeAttitude',
            timestamp=row['timestamp'],
            severity='CRITICAL',
            detail=f"Extreme attitude detected. "
                   f"Roll: {row['roll_deg']:.1f}° "
                   f"Pitch: {row['pitch_deg']:.1f}°",
            recommendation="Review flight controller tuning. "
                          "Inspect airframe for damage."
        ))
    
    return events


def run_all_detectors(telemetry: dict) -> List[AnomalyEvent]:
    """
    Run all anomaly detectors against a telemetry dataset.
    Returns combined sorted list of all detected anomalies.
    """
    all_anomalies = []
    
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
    
    # Sort by timestamp
    all_anomalies.sort(key=lambda x: x.timestamp)
    
    return all_anomalies


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