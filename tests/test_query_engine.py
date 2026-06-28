"""
Tests for SENTINEL Phase 2: Query Engine + Reasoning Engine.

Uses in-memory SQLite with synthetic data — no real tlog files needed.
Synthetic mission simulates a realistic flight with known anomalies
so we can verify query results deterministically.
"""

import pytest
import time
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from telemetry_store import TelemetryStore
from query_engine import QueryEngine, QueryIntent, QueryType, QueryResult, haversine_metres
from reasoning import ReasoningEngine


# ─── Fixtures ────────────────────────────────────────────────

MISSION_ID = "test_mission_001"
DRONE_ID = "drone_0"
BASE_TS = 1700000000.0  # fixed base timestamp for deterministic tests


@pytest.fixture
def populated_store():
    """
    Create an in-memory TelemetryStore with a synthetic mission.
    
    Simulates ~25s of flight with:
    - 100 position readings (small circle pattern)
    - 100 battery readings (gradual discharge, one stress event at row 50)
    - 100 attitude readings (one extreme attitude at row 70)
    - 100 HUD readings (normal flight)
    - 10 anomaly events of mixed types
    """
    store = TelemetryStore(db_path=":memory:")
    store.create_mission(MISSION_ID, DRONE_ID)

    import math

    # Positions — small circle around a point, 0.25s apart
    positions = []
    center_lat, center_lon = -35.3632, 149.1652  # SITL default
    for i in range(100):
        angle = (i / 100) * 2 * math.pi
        positions.append((
            DRONE_ID, MISSION_ID, BASE_TS + i * 0.25,
            center_lat + 0.0001 * math.sin(angle),
            center_lon + 0.0001 * math.cos(angle),
            584.0 + i * 0.1,  # alt_metres: gradual climb
            10.0 + i * 0.1,   # relative_alt
            1.0 * math.cos(angle), 1.0 * math.sin(angle), -0.1  # vx, vy, vz
        ))
    with store.conn:
        store.conn.executemany(
            "INSERT INTO positions (drone_id, mission_id, timestamp, lat, lon, "
            "alt_metres, relative_alt, vx, vy, vz) VALUES (?,?,?,?,?,?,?,?,?,?)",
            positions
        )

    # Battery — gradual discharge, stress event at row 50
    battery = []
    for i in range(100):
        voltage = 16.8 - (i * 0.02)  # slow discharge
        if i == 50:
            voltage = 15.5  # sudden drop = stress event
        battery.append((
            DRONE_ID, MISSION_ID, BASE_TS + i * 0.25,
            voltage,
            10.0 + (i * 0.05),  # current slowly increasing
            100.0 - (i * 0.5)   # remaining_pct: 100 → 50
        ))
    with store.conn:
        store.conn.executemany(
            "INSERT INTO battery (drone_id, mission_id, timestamp, voltage, "
            "current, remaining_pct) VALUES (?,?,?,?,?,?)",
            battery
        )

    # Attitude — one extreme event at row 70
    attitude = []
    for i in range(100):
        roll = 5.0 + (i * 0.1)
        pitch = 3.0
        if i == 70:
            roll = 55.0   # exceeds ANGLE_MAX (45°)
            pitch = 50.0
        attitude.append((
            DRONE_ID, MISSION_ID, BASE_TS + i * 0.25,
            roll, pitch, 180.0 + i
        ))
    with store.conn:
        store.conn.executemany(
            "INSERT INTO attitude (drone_id, mission_id, timestamp, "
            "roll_deg, pitch_deg, yaw_deg) VALUES (?,?,?,?,?,?)",
            attitude
        )

    # HUD — normal flight data
    hud = []
    for i in range(100):
        hud.append((
            DRONE_ID, MISSION_ID, BASE_TS + i * 0.25,
            5.0, 4.5, 10.0 + i * 0.1, 0.5, 45.0  # airspeed, gs, alt, climb, throttle
        ))
    with store.conn:
        store.conn.executemany(
            "INSERT INTO hud (drone_id, mission_id, timestamp, airspeed, "
            "groundspeed, altitude, climb_rate, throttle_pct) VALUES (?,?,?,?,?,?,?,?)",
            hud
        )

    # Anomaly events — 10 mixed events
    anomaly_data = [
        (DRONE_ID, MISSION_ID, BASE_TS + 5, "BatteryStress", "HIGH",
         "Voltage dropped 0.8V", "Inspect battery"),
        (DRONE_ID, MISSION_ID, BASE_TS + 6, "LowBattery", "HIGH",
         "Battery at 18%", "Prepare RTL"),
        (DRONE_ID, MISSION_ID, BASE_TS + 10, "RapidDescent", "CRITICAL",
         "Altitude dropped 3.2m", "Check motors"),
        (DRONE_ID, MISSION_ID, BASE_TS + 10.5, "ExtremeAttitude", "CRITICAL",
         "Roll: 55° Pitch: 50°", "Review tuning"),
        (DRONE_ID, MISSION_ID, BASE_TS + 12, "SignalDegraded", "MEDIUM",
         "RSSI: 45/254", "Monitor connection"),
        (DRONE_ID, MISSION_ID, BASE_TS + 13, "SignalDegraded", "CRITICAL",
         "RSSI: 15/254", "Initiate RTL"),
        (DRONE_ID, MISSION_ID, BASE_TS + 15, "GPSGlitch", "HIGH",
         "HDOP: 3.5", "Switch to AltHold"),
        (DRONE_ID, MISSION_ID, BASE_TS + 16, "GPSGlitch", "CRITICAL",
         "HDOP: 5.2", "Prepare for RTL failure"),
        (DRONE_ID, MISSION_ID, BASE_TS + 20, "IdleDrift", "MEDIUM",
         "Drone stationary for 8 readings", "Check nav"),
        (DRONE_ID, MISSION_ID, BASE_TS + 22, "BatteryStress", "HIGH",
         "Voltage dropped 0.6V", "Inspect battery"),
    ]
    with store.conn:
        store.conn.executemany(
            "INSERT INTO anomaly_events (drone_id, mission_id, timestamp, "
            "event_type, severity, detail, recommendation) VALUES (?,?,?,?,?,?,?)",
            anomaly_data
        )

    yield store
    store.close()


@pytest.fixture
def engine(populated_store):
    """QueryEngine backed by the populated in-memory store."""
    qe = QueryEngine.__new__(QueryEngine)
    qe.store = populated_store
    qe.reasoning = ReasoningEngine()
    return qe


# ─── Haversine ───────────────────────────────────────────────

def test_haversine_known_distance():
    """Validate Haversine against known coordinate pair.
    SITL home (-35.3632, 149.1652) to a point ~111m north."""
    d = haversine_metres(-35.3632, 149.1652, -35.3622, 149.1652)
    assert 110 < d < 115  # ~111m for 0.001° latitude


def test_haversine_same_point():
    """Same coordinates should return 0 distance."""
    d = haversine_metres(-35.3632, 149.1652, -35.3632, 149.1652)
    assert d == 0.0


# ─── Mission Summary ────────────────────────────────────────

def test_mission_summary_returns_all_fields(engine):
    """Mission summary should contain all expected keys."""
    result = engine.execute(QueryIntent(
        query_type=QueryType.MISSION_SUMMARY,
        mission_id=MISSION_ID
    ))
    assert result.success is True
    assert result.confidence == "HIGH"
    s = result.summary
    expected_keys = [
        "mission_id", "status", "duration_seconds", "position_readings",
        "max_altitude_m", "total_distance_m", "battery_start_pct",
        "battery_end_pct", "voltage_min", "voltage_max",
        "avg_groundspeed_ms", "total_anomalies", "anomaly_breakdown"
    ]
    for k in expected_keys:
        assert k in s, f"Missing key: {k}"
    assert s["position_readings"] == 100
    assert s["total_anomalies"] == 10


def test_mission_summary_nonexistent(engine):
    """Querying a non-existent mission should fail gracefully."""
    result = engine.execute(QueryIntent(
        query_type=QueryType.MISSION_SUMMARY,
        mission_id="does_not_exist"
    ))
    assert result.success is False
    assert "mission_not_found" in result.data_gaps


# ─── Anomaly Summary ────────────────────────────────────────

def test_anomaly_summary_all_types(engine):
    """Without filter, should return all 10 anomaly events."""
    result = engine.execute(QueryIntent(
        query_type=QueryType.ANOMALY_SUMMARY,
        mission_id=MISSION_ID
    ))
    assert result.success is True
    assert result.summary["total_events"] == 10
    assert "BatteryStress" in result.summary["by_type"]
    assert "SignalDegraded" in result.summary["by_type"]


def test_anomaly_summary_filters_by_type(engine):
    """Filter by event_type should return only matching events."""
    result = engine.execute(QueryIntent(
        query_type=QueryType.ANOMALY_SUMMARY,
        mission_id=MISSION_ID,
        anomaly_type="BatteryStress"
    ))
    assert result.success is True
    assert result.summary["total_events"] == 2
    assert result.summary["filter"] == "BatteryStress"


def test_anomaly_summary_no_match(engine):
    """Filter for non-existent type should return empty with data_gaps."""
    result = engine.execute(QueryIntent(
        query_type=QueryType.ANOMALY_SUMMARY,
        mission_id=MISSION_ID,
        anomaly_type="MotorImbalance"
    ))
    assert result.success is True
    assert result.summary["total_events"] == 0
    assert "no_anomalies_found" in result.data_gaps


# ─── Time Window ─────────────────────────────────────────────

def test_time_window_returns_data(engine):
    """Time window query should return data within the range."""
    result = engine.execute(QueryIntent(
        query_type=QueryType.TIME_WINDOW,
        time_start=BASE_TS,
        time_end=BASE_TS + 10,
        drone_id=DRONE_ID
    ))
    assert result.success is True
    assert result.summary["position_count"] > 0
    assert result.summary["battery_count"] > 0


def test_time_window_empty(engine):
    """Empty window should succeed but with empty data."""
    result = engine.execute(QueryIntent(
        query_type=QueryType.TIME_WINDOW,
        time_start=BASE_TS + 9999,
        time_end=BASE_TS + 10000,
        drone_id=DRONE_ID
    ))
    assert result.success is True
    assert result.summary["position_count"] == 0
    assert result.confidence == "LOW"


def test_time_window_missing_params(engine):
    """Missing time params should fail gracefully."""
    result = engine.execute(QueryIntent(
        query_type=QueryType.TIME_WINDOW,
        drone_id=DRONE_ID
    ))
    assert result.success is False
    assert "missing_time_range" in result.data_gaps


# ─── Battery Profile ────────────────────────────────────────

def test_battery_profile_computes_discharge(engine):
    """Battery profile should compute discharge rate and voltage quartiles."""
    result = engine.execute(QueryIntent(
        query_type=QueryType.BATTERY_PROFILE,
        mission_id=MISSION_ID
    ))
    assert result.success is True
    s = result.summary
    assert s["readings"] == 100
    assert s["start_pct"] == 100.0
    assert s["end_pct"] == 50.5
    assert s["discharge_pct_per_min"] > 0
    assert len(s["voltage_quartiles"]) == 4
    assert "health_assessment" in s


def test_battery_profile_no_data(engine):
    """Battery profile for non-existent mission should fail."""
    result = engine.execute(QueryIntent(
        query_type=QueryType.BATTERY_PROFILE,
        mission_id="no_such_mission"
    ))
    assert result.success is False
    assert "no_battery_data" in result.data_gaps


# ─── Waypoint Analysis ──────────────────────────────────────

def test_waypoint_analysis_no_planned_route(engine):
    """Waypoint analysis without planned route should report data gap."""
    result = engine.execute(QueryIntent(
        query_type=QueryType.WAYPOINT_ANALYSIS,
        mission_id=MISSION_ID,
        waypoint_id=0
    ))
    assert result.success is False
    assert "no_planned_route" in result.data_gaps


def test_waypoint_analysis_with_route(engine):
    """Waypoint analysis with planned route should compute deviation."""
    # Use positions near our circular flight path
    planned = [
        {"lat": -35.3632, "lon": 149.1652},   # center — should be close
        {"lat": -35.3700, "lon": 149.1700},    # far away — large deviation
    ]
    result = engine.execute(QueryIntent(
        query_type=QueryType.WAYPOINT_ANALYSIS,
        mission_id=MISSION_ID,
        waypoint_id=0,
        parameters={"planned_route": planned}
    ))
    assert result.success is True
    # Center of our circle should have small deviation
    assert result.summary["deviation_metres"] < 20


# ─── Route Deviation ────────────────────────────────────────

def test_route_deviation_no_planned_route(engine):
    """Route deviation without planned route should report data gap."""
    result = engine.execute(QueryIntent(
        query_type=QueryType.ROUTE_DEVIATION,
        mission_id=MISSION_ID
    ))
    assert result.success is False
    assert "no_planned_route" in result.data_gaps


def test_route_deviation_with_route(engine):
    """Route deviation should compute per-waypoint metrics."""
    planned = [
        {"lat": -35.3632, "lon": 149.1652},
        {"lat": -35.3633, "lon": 149.1653},
    ]
    result = engine.execute(QueryIntent(
        query_type=QueryType.ROUTE_DEVIATION,
        mission_id=MISSION_ID,
        parameters={"planned_route": planned}
    ))
    assert result.success is True
    assert result.summary["total_waypoints"] == 2
    assert len(result.summary["per_waypoint"]) == 2
    assert "mean_deviation_m" in result.summary


# ─── Reasoning Engine ───────────────────────────────────────

class TestReasoningEngine:
    """Unit tests for each named correlation rule."""

    def setup_method(self):
        self.engine = ReasoningEngine()

    def test_signal_induced_deviation_triggers(self):
        """deviation > 20m + SignalDegraded → fires."""
        ctx = {
            "anomalies": [{"event_type": "SignalDegraded", "severity": "CRITICAL"}],
            "deviation_metres": 35.0,
            "avg_throttle": 50,
        }
        results = self.engine.evaluate(ctx)
        names = [r.rule_name for r in results]
        assert "signal_induced_deviation" in names

    def test_battery_forced_descent_triggers(self):
        """RapidDescent + BatteryStress → fires."""
        ctx = {
            "anomalies": [
                {"event_type": "RapidDescent", "severity": "CRITICAL"},
                {"event_type": "BatteryStress", "severity": "HIGH"},
            ],
            "deviation_metres": 0,
            "avg_throttle": 50,
        }
        results = self.engine.evaluate(ctx)
        names = [r.rule_name for r in results]
        assert "battery_forced_descent" in names

    def test_motor_failure_pattern_triggers(self):
        """ExtremeAttitude + RapidDescent + throttle > 70% → fires."""
        ctx = {
            "anomalies": [
                {"event_type": "ExtremeAttitude", "severity": "CRITICAL"},
                {"event_type": "RapidDescent", "severity": "CRITICAL"},
            ],
            "deviation_metres": 0,
            "avg_throttle": 85,
        }
        results = self.engine.evaluate(ctx)
        names = [r.rule_name for r in results]
        assert "motor_failure_pattern" in names

    def test_gps_position_error_triggers(self):
        """deviation > 20m + GPSGlitch + no SignalDegraded → fires."""
        ctx = {
            "anomalies": [{"event_type": "GPSGlitch", "severity": "HIGH"}],
            "deviation_metres": 30.0,
            "avg_throttle": 50,
        }
        results = self.engine.evaluate(ctx)
        names = [r.rule_name for r in results]
        assert "gps_position_error" in names

    def test_environmental_drift_triggers(self):
        """deviation > 20m + no anomalies → fires."""
        ctx = {
            "anomalies": [],
            "deviation_metres": 25.0,
            "avg_throttle": 50,
        }
        results = self.engine.evaluate(ctx)
        names = [r.rule_name for r in results]
        assert "environmental_drift" in names

    def test_no_rules_fire_when_nominal(self):
        """Clean context with no anomalies and small deviation → nothing fires."""
        ctx = {
            "anomalies": [],
            "deviation_metres": 5.0,
            "avg_throttle": 50,
        }
        results = self.engine.evaluate(ctx)
        assert len(results) == 0

    def test_multiple_rules_can_fire(self):
        """Overlapping conditions can trigger multiple rules."""
        ctx = {
            "anomalies": [
                {"event_type": "ExtremeAttitude", "severity": "CRITICAL"},
                {"event_type": "RapidDescent", "severity": "CRITICAL"},
                {"event_type": "BatteryStress", "severity": "HIGH"},
            ],
            "deviation_metres": 0,
            "avg_throttle": 80,
        }
        results = self.engine.evaluate(ctx)
        names = [r.rule_name for r in results]
        # Both battery_forced_descent and motor_failure_pattern should fire
        assert "battery_forced_descent" in names
        assert "motor_failure_pattern" in names
        assert len(results) >= 2


# ─── Attribute Query (Dynamic SQL) ──────────────────────────

class TestAttributeQuery:
    """Tests for the dynamic SQL builder."""

    def test_select_columns(self, engine):
        result = engine.execute(QueryIntent(
            query_type=QueryType.ATTRIBUTE_QUERY,
            parameters={
                "table": "battery",
                "columns": ["voltage", "current"],
                "limit": 5
            }
        ))
        assert result.success is True
        assert len(result.evidence) == 5
        assert "voltage" in result.evidence[0]
        assert "current" in result.evidence[0]
        assert "remaining_pct" not in result.evidence[0]

    def test_with_filter(self, engine):
        result = engine.execute(QueryIntent(
            query_type=QueryType.ATTRIBUTE_QUERY,
            parameters={
                "table": "battery",
                "columns": ["voltage"],
                "filters": [{"column": "voltage", "op": "<", "value": 16.0}]
            }
        ))
        assert result.success is True
        for row in result.evidence:
            assert row["voltage"] < 16.0

    def test_aggregation(self, engine):
        result = engine.execute(QueryIntent(
            query_type=QueryType.ATTRIBUTE_QUERY,
            parameters={
                "table": "battery",
                "aggregations": [{"func": "MIN", "column": "voltage"}]
            }
        ))
        assert result.success is True
        assert len(result.evidence) == 1
        # The key returned by SQLite might be 'MIN(voltage)' or similar
        row = result.evidence[0]
        val = list(row.values())[0]
        assert val <= 15.5  # We know 15.5 is our min in the fixture

    def test_time_range(self, engine):
        result = engine.execute(QueryIntent(
            query_type=QueryType.ATTRIBUTE_QUERY,
            time_start=BASE_TS,
            time_end=BASE_TS + 5,
            parameters={
                "table": "positions",
                "columns": ["timestamp"]
            }
        ))
        assert result.success is True
        for row in result.evidence:
            assert BASE_TS <= row["timestamp"] <= BASE_TS + 5

    def test_invalid_table_rejected(self, engine):
        result = engine.execute(QueryIntent(
            query_type=QueryType.ATTRIBUTE_QUERY,
            parameters={
                "table": "users",  # doesn't exist
            }
        ))
        assert result.success is False
        assert "Unknown table" in result.summary["error"]

    def test_invalid_column_rejected(self, engine):
        result = engine.execute(QueryIntent(
            query_type=QueryType.ATTRIBUTE_QUERY,
            parameters={
                "table": "battery",
                "columns": ["password"],  # doesn't exist
            }
        ))
        assert result.success is False
        assert "Unknown column" in result.summary["error"]

    def test_schema_registry(self, engine):
        schema = engine.get_schema()
        assert "battery" in schema
        assert "positions" in schema
        assert "voltage" in schema["battery"]["columns"]
