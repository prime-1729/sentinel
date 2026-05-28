import pytest
import pandas as pd
from src.anomaly import detect_signal_degraded, detect_gps_glitch, detect_battery_stress, detect_altitude_anomaly, detect_attitude_anomaly

# ─── Signal Degradation (RSSI) ───────────────────────────────

def test_signal_degraded_critical():
    """RSSI < 30 should fire a CRITICAL event (~10 dB above sensitivity limit)."""
    data = pd.DataFrame([
        {'timestamp': 100.0, 'rssi': 20.0},  # CRITICAL: < 30
    ])
    anomalies = detect_signal_degraded(data)
    assert len(anomalies) == 1
    assert anomalies[0].severity == 'CRITICAL'
    assert 'Link loss imminent' in anomalies[0].detail

def test_signal_degraded_warning():
    """RSSI 30-64 should fire a MEDIUM warning event."""
    data = pd.DataFrame([
        {'timestamp': 100.0, 'rssi': 45.0},  # MEDIUM: 30-64 range
    ])
    anomalies = detect_signal_degraded(data)
    assert len(anomalies) == 1
    assert anomalies[0].severity == 'MEDIUM'

def test_signal_healthy_no_alert():
    """RSSI >= 64 is healthy — no alerts should fire."""
    data = pd.DataFrame([
        {'timestamp': 100.0, 'rssi': 190.0},  # Healthy signal
    ])
    anomalies = detect_signal_degraded(data)
    assert len(anomalies) == 0

# ─── GPS Glitch (HDOP) ───────────────────────────────────────

def test_gps_glitch_critical():
    """EPH > 400 (HDOP > 4.0) should fire a CRITICAL event."""
    data = pd.DataFrame([
        {'timestamp': 200.0, 'eph': 450.0},  # HDOP 4.5 = CRITICAL
    ])
    anomalies = detect_gps_glitch(data)
    assert len(anomalies) == 1
    assert anomalies[0].severity == 'CRITICAL'
    assert 'Navigation unreliable' in anomalies[0].detail

def test_gps_glitch_warning():
    """EPH 201-400 (HDOP 2.0-4.0) should fire a HIGH warning."""
    data = pd.DataFrame([
        {'timestamp': 200.0, 'eph': 250.0},  # HDOP 2.5 = HIGH
    ])
    anomalies = detect_gps_glitch(data)
    assert len(anomalies) == 1
    assert anomalies[0].severity == 'HIGH'
    assert 'HDOP: 2.50' in anomalies[0].detail

def test_gps_healthy_no_alert():
    """EPH <= 200 (HDOP <= 2.0) is within ArduPilot's GPS_HDOP_GOOD — no alerts."""
    data = pd.DataFrame([
        {'timestamp': 200.0, 'eph': 140.0},  # HDOP 1.4 = ArduPilot default good
    ])
    anomalies = detect_gps_glitch(data)
    assert len(anomalies) == 0

# ─── Battery Stress ──────────────────────────────────────────

def test_battery_stress_voltage_sag():
    """Voltage drop > 0.5V should fire BatteryStress (ArduPilot LiPo sag threshold)."""
    data = pd.DataFrame([
        {'timestamp': 100.0, 'voltage': 16.8, 'remaining_pct': 95},
        {'timestamp': 101.0, 'voltage': 16.1, 'remaining_pct': 93},  # 0.7V drop = stress
    ])
    anomalies = detect_battery_stress(data)
    stress = [a for a in anomalies if a.event_type == 'BatteryStress']
    assert len(stress) == 1
    assert stress[0].severity == 'HIGH'

def test_battery_normal_sag_no_alert():
    """Voltage drop of 0.3V is normal flight sag — should NOT fire."""
    data = pd.DataFrame([
        {'timestamp': 100.0, 'voltage': 16.8, 'remaining_pct': 95},
        {'timestamp': 101.0, 'voltage': 16.5, 'remaining_pct': 94},  # 0.3V = normal sag
    ])
    anomalies = detect_battery_stress(data)
    stress = [a for a in anomalies if a.event_type == 'BatteryStress']
    assert len(stress) == 0

def test_battery_low_warning():
    """Battery 15% should fire HIGH (ArduPilot BATT_LOW_MAH = 20%)."""
    data = pd.DataFrame([
        {'timestamp': 100.0, 'voltage': 14.0, 'remaining_pct': 15},
        {'timestamp': 101.0, 'voltage': 13.9, 'remaining_pct': 14},
    ])
    anomalies = detect_battery_stress(data)
    low = [a for a in anomalies if a.event_type == 'LowBattery']
    assert len(low) == 1
    assert low[0].severity == 'HIGH'

def test_battery_critical():
    """Battery < 10% should fire CRITICAL (ArduPilot BATT_CRT_MAH)."""
    data = pd.DataFrame([
        {'timestamp': 100.0, 'voltage': 13.0, 'remaining_pct': 8},
        {'timestamp': 101.0, 'voltage': 12.9, 'remaining_pct': 7},
    ])
    anomalies = detect_battery_stress(data)
    low = [a for a in anomalies if a.event_type == 'LowBattery']
    assert len(low) == 1
    assert low[0].severity == 'CRITICAL'

# ─── Rapid Descent ───────────────────────────────────────────

def test_rapid_descent_fires():
    """Altitude drop > 2.0m per reading should fire CRITICAL 
    (exceeds ArduPilot LAND_SPEED_HIGH max of 5 m/s)."""
    data = pd.DataFrame([
        {'timestamp': 100.0, 'relative_alt': 50.0},
        {'timestamp': 101.0, 'relative_alt': 47.5},  # -2.5m = CRITICAL
    ])
    anomalies = detect_altitude_anomaly(data)
    assert len(anomalies) == 1
    assert anomalies[0].severity == 'CRITICAL'
    assert 'LAND_SPEED_HIGH' in anomalies[0].recommendation

def test_normal_descent_no_alert():
    """Altitude drop of 1.0m is within normal commanded descent — no alert."""
    data = pd.DataFrame([
        {'timestamp': 100.0, 'relative_alt': 50.0},
        {'timestamp': 101.0, 'relative_alt': 49.0},  # -1.0m = normal
    ])
    anomalies = detect_altitude_anomaly(data)
    assert len(anomalies) == 0

# ─── Extreme Attitude ────────────────────────────────────────

def test_extreme_attitude_fires():
    """Roll/Pitch > 45° should fire CRITICAL (ArduPilot ANGLE_MAX = 4500 centi-deg)."""
    data = pd.DataFrame([
        {'timestamp': 100.0, 'roll_deg': 50.0, 'pitch_deg': 10.0},
    ])
    anomalies = detect_attitude_anomaly(data)
    assert len(anomalies) == 1
    assert anomalies[0].severity == 'CRITICAL'
    assert 'ANGLE_MAX' in anomalies[0].detail

def test_normal_attitude_no_alert():
    """Roll/Pitch within 45° is within ArduPilot ANGLE_MAX — no alert."""
    data = pd.DataFrame([
        {'timestamp': 100.0, 'roll_deg': 30.0, 'pitch_deg': 25.0},
    ])
    anomalies = detect_attitude_anomaly(data)
    assert len(anomalies) == 0

# ─── Edge Cases ──────────────────────────────────────────────

def test_detectors_with_empty_df():
    """Verify that all detectors gracefully handle empty DataFrames."""
    data = pd.DataFrame()
    assert len(detect_signal_degraded(data)) == 0
    assert len(detect_gps_glitch(data)) == 0
