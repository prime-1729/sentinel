import pytest
import os
import sqlite3
import pandas as pd
from src.telemetry_store import TelemetryStore

def test_store_initialization():
    """
    Test that the store initializes and sets SQLite features.
    """
    store = TelemetryStore(db_path=":memory:")
    assert store.conn is not None
    
    # Check journal mode is WAL (in-memory db might remain in memory mode, but check no errors)
    res = store.conn.execute("PRAGMA foreign_keys").fetchone()
    assert res[0] == 1 # foreign keys ON
    store.close()

def test_mission_lifecycle():
    """
    Test create_mission, get_mission, and complete_mission.
    """
    store = TelemetryStore(db_path=":memory:")
    
    # Verify missing mission
    assert store.get_mission("nonexistent") is None
    
    # Create mission
    store.create_mission("test_mission_01", "drone_1")
    mission = store.get_mission("test_mission_01")
    assert mission is not None
    assert mission["mission_id"] == "test_mission_01"
    assert mission["drone_id"] == "drone_1"
    assert mission["status"] == "ACTIVE"
    assert mission["start_time"] is not None
    assert mission["end_time"] is None
    
    # Complete mission
    store.complete_mission("test_mission_01")
    mission = store.get_mission("test_mission_01")
    assert mission["status"] == "COMPLETED"
    assert mission["end_time"] is not None
    
    store.close()

def test_ingest_dataframes():
    """
    Test the ingestion of structured pandas DataFrames.
    """
    store = TelemetryStore(db_path=":memory:")
    
    telemetry = {
        'positions': pd.DataFrame([
            {'timestamp': 1000.0, 'lat': 12.345, 'lon': 67.890, 'alt_metres': 50.0, 'relative_alt': 48.0, 'vx': 1.5, 'vy': -0.5, 'vz': 0.1},
            {'timestamp': 1001.0, 'lat': 12.346, 'lon': 67.891, 'alt_metres': 51.0, 'relative_alt': 49.0, 'vx': 1.6, 'vy': -0.4, 'vz': 0.2}
        ]),
        'battery': pd.DataFrame([
            {'timestamp': 1000.0, 'voltage': 16.8, 'current': 12.5, 'remaining_pct': 99.0}
        ]),
        'attitude': pd.DataFrame([
            {'timestamp': 1000.0, 'roll_deg': 2.5, 'pitch_deg': -1.2, 'yaw_deg': 180.0}
        ]),
        'hud': pd.DataFrame([
            {'timestamp': 1000.0, 'airspeed': 10.2, 'groundspeed': 10.5, 'altitude': 50.0, 'climb_rate': 0.5, 'throttle_pct': 60}
        ])
    }
    
    counts = store.ingest_dataframes(telemetry, drone_id="drone_test", mission_id="mission_df_test")
    
    assert counts['positions'] == 2
    assert counts['battery'] == 1
    assert counts['attitude'] == 1
    assert counts['hud'] == 1
    
    # Query to verify positions data
    positions = store.query("SELECT * FROM positions ORDER BY timestamp ASC")
    assert len(positions) == 2
    assert positions[0]['drone_id'] == "drone_test"
    assert positions[0]['mission_id'] == "mission_df_test"
    assert positions[0]['lat'] == 12.345
    assert positions[1]['relative_alt'] == 49.0
    
    # Query to verify battery data
    battery = store.query("SELECT * FROM battery")
    assert len(battery) == 1
    assert battery[0]['voltage'] == 16.8
    assert battery[0]['remaining_pct'] == 99.0
    
    # Query to verify attitude data
    attitude = store.query("SELECT * FROM attitude")
    assert len(attitude) == 1
    assert attitude[0]['roll_deg'] == 2.5
    assert attitude[0]['pitch_deg'] == -1.2
    
    # Query to verify hud data
    hud = store.query("SELECT * FROM hud")
    assert len(hud) == 1
    assert hud[0]['airspeed'] == 10.2
    assert hud[0]['throttle_pct'] == 60
    
    # Mission should have been auto-created
    mission = store.get_mission("mission_df_test")
    assert mission is not None
    assert mission["drone_id"] == "drone_test"
    
    store.close()

def test_ingest_anomalies():
    """
    Test inserting anomaly events.
    """
    store = TelemetryStore(db_path=":memory:")
    
    anomalies = [
        {
            'timestamp': 1005.0,
            'event_type': 'LowBattery',
            'severity': 'WARNING',
            'detail': 'Battery dropped below 30%',
            'recommendation': 'Monitor voltage level'
        },
        {
            'timestamp': 1010.0,
            'event_type': 'LowBattery',
            'severity': 'CRITICAL',
            'detail': 'Battery dropped below 20%',
            'recommendation': 'Initiate RTL'
        }
    ]
    
    inserted = store.ingest_anomalies(anomalies, drone_id="drone_test", mission_id="mission_anomaly_test")
    assert inserted == 2
    
    events = store.query("SELECT * FROM anomaly_events ORDER BY timestamp ASC")
    assert len(events) == 2
    assert events[0]['event_type'] == 'LowBattery'
    assert events[0]['severity'] == 'WARNING'
    assert events[1]['severity'] == 'CRITICAL'
    assert events[1]['recommendation'] == 'Initiate RTL'
    
    store.close()
