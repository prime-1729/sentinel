"""
SENTINEL Query Engine — Structured query execution against SQLite telemetry store.

Takes a QueryIntent dataclass, queries the TelemetryStore, runs the reasoning
engine for cross-stream correlations, and returns a QueryResult with evidence.
No LLM involved — pure deterministic engineering.
"""

import math
from enum import Enum
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional

from telemetry_store import TelemetryStore
from reasoning import ReasoningEngine


# ─── Data Models ─────────────────────────────────────────────

SCHEMA_REGISTRY = {
    "positions": {
        "columns": {
            "lat": "GPS latitude (degrees)",
            "lon": "GPS longitude (degrees)",
            "alt_metres": "Absolute altitude (metres above sea level)",
            "relative_alt": "Altitude above takeoff point (metres)",
            "vx": "Velocity X component (m/s, North)",
            "vy": "Velocity Y component (m/s, East)",
            "vz": "Velocity Z component (m/s, Down)",
            "timestamp": "UNIX timestamp",
            "drone_id": "Drone identifier",
            "mission_id": "Mission identifier",
        },
        "description": "GPS position and velocity from GLOBAL_POSITION_INT"
    },
    "battery": {
        "columns": {
            "voltage": "Battery terminal voltage (V)",
            "current": "Current draw (A)",
            "remaining_pct": "Remaining capacity (%)",
            "timestamp": "UNIX timestamp",
            "drone_id": "Drone identifier",
            "mission_id": "Mission identifier",
        },
        "description": "Battery state from BATTERY_STATUS"
    },
    "attitude": {
        "columns": {
            "roll_deg": "Roll angle in degrees",
            "pitch_deg": "Pitch angle in degrees",
            "yaw_deg": "Yaw angle in degrees",
            "timestamp": "UNIX timestamp",
            "drone_id": "Drone identifier",
            "mission_id": "Mission identifier",
        },
        "description": "Orientation angles from ATTITUDE"
    },
    "hud": {
        "columns": {
            "airspeed": "Airspeed (m/s)",
            "groundspeed": "Groundspeed (m/s)",
            "altitude": "Altitude (m)",
            "climb_rate": "Climb rate (m/s)",
            "throttle_pct": "Throttle percentage",
            "timestamp": "UNIX timestamp",
            "drone_id": "Drone identifier",
            "mission_id": "Mission identifier",
        },
        "description": "Key flight metrics from VFR_HUD"
    },
    "anomaly_events": {
        "columns": {
            "event_type": "Type of anomaly (e.g., BatteryStress, GPSGlitch)",
            "severity": "Severity (LOW, MEDIUM, HIGH, CRITICAL)",
            "detail": "Explanation of anomaly",
            "recommendation": "Suggested action",
            "timestamp": "UNIX timestamp",
            "drone_id": "Drone identifier",
            "mission_id": "Mission identifier",
        },
        "description": "Detected anomaly events"
    },
    "missions": {
        "columns": {
            "mission_id": "Mission identifier",
            "drone_id": "Drone identifier",
            "start_time": "Mission start UNIX timestamp",
            "end_time": "Mission end UNIX timestamp",
            "status": "Mission status (ACTIVE, COMPLETED, etc)",
            "planned_route": "Planned route JSON"
        },
        "description": "Mission metadata"
    }
}


class QueryType(Enum):
    WAYPOINT_ANALYSIS = "waypoint_analysis"
    TIME_WINDOW = "time_window"
    ANOMALY_SUMMARY = "anomaly_summary"
    ROUTE_DEVIATION = "route_deviation"
    BATTERY_PROFILE = "battery_profile"
    MISSION_SUMMARY = "mission_summary"
    ATTRIBUTE_QUERY = "attribute_query"


@dataclass
class QueryIntent:
    """Structured representation of an operator's question."""
    query_type: QueryType
    drone_id: Optional[str] = None
    mission_id: Optional[str] = None
    time_start: Optional[float] = None
    time_end: Optional[float] = None
    waypoint_id: Optional[int] = None
    anomaly_type: Optional[str] = None
    parameters: Optional[dict] = None


@dataclass
class QueryResult:
    """Structured response from the query engine."""
    success: bool
    summary: Dict[str, Any] = field(default_factory=dict)
    evidence: List[Dict[str, Any]] = field(default_factory=list)
    confidence: str = "LOW"
    data_gaps: List[str] = field(default_factory=list)
    correlations: List[Dict[str, Any]] = field(default_factory=list)


# ─── Utilities ───────────────────────────────────────────────

def haversine_metres(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Great-circle distance between two GPS coordinates in metres.
    Uses the Haversine formula with Earth radius R = 6,371,000 m.
    """
    R = 6_371_000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


# ─── Query Engine ────────────────────────────────────────────

class QueryEngine:
    """
    Executes structured queries against the SENTINEL telemetry store.
    
    Each query type maps to a handler that runs SQL, computes derived
    metrics, and optionally runs the reasoning engine for correlations.
    """

    def __init__(self, db_path: str = "data/sentinel.db"):
        self.store = TelemetryStore(db_path=db_path)
        self.reasoning = ReasoningEngine()

    def execute(self, intent: QueryIntent) -> QueryResult:
        """Dispatch to the appropriate handler based on query type."""
        handlers = {
            QueryType.MISSION_SUMMARY: self._mission_summary,
            QueryType.ANOMALY_SUMMARY: self._summarise_anomalies,
            QueryType.TIME_WINDOW: self._query_time_window,
            QueryType.BATTERY_PROFILE: self._battery_profile,
            QueryType.WAYPOINT_ANALYSIS: self._analyse_waypoint,
            QueryType.ROUTE_DEVIATION: self._analyse_route_deviation,
            QueryType.ATTRIBUTE_QUERY: self._attribute_query,
        }
        handler = handlers.get(intent.query_type)
        if handler is None:
            return QueryResult(
                success=False,
                summary={"error": f"Unknown query type: {intent.query_type}"},
                confidence="LOW",
                data_gaps=[f"unsupported_query_type:{intent.query_type.value}"]
            )
        try:
            return handler(intent)
        except Exception as e:
            return QueryResult(
                success=False,
                summary={"error": str(e)},
                confidence="LOW",
                data_gaps=["query_execution_error"]
            )

    def close(self):
        """Close the underlying database connection."""
        self.store.close()

    # ─── Handlers ────────────────────────────────────────────

    def _mission_summary(self, intent: QueryIntent) -> QueryResult:
        """Full mission overview: duration, flight stats, battery, anomalies."""
        mid = intent.mission_id
        data_gaps = []

        mission = self.store.get_mission(mid)
        if not mission:
            return QueryResult(success=False, summary={"error": "Mission not found"},
                               data_gaps=["mission_not_found"])

        # Position stats
        pos = self.store.query(
            "SELECT MIN(timestamp) as t_start, MAX(timestamp) as t_end, "
            "MIN(relative_alt) as min_alt, MAX(relative_alt) as max_alt, "
            "COUNT(*) as count FROM positions WHERE mission_id = ?", (mid,)
        )
        pos_row = pos[0] if pos else {}

        # Compute total flight distance
        all_pos = self.store.query(
            "SELECT lat, lon FROM positions WHERE mission_id = ? ORDER BY timestamp", (mid,)
        )
        total_distance = 0.0
        for i in range(1, len(all_pos)):
            total_distance += haversine_metres(
                all_pos[i-1]['lat'], all_pos[i-1]['lon'],
                all_pos[i]['lat'], all_pos[i]['lon']
            )

        # Battery stats
        bat = self.store.query(
            "SELECT MIN(voltage) as v_min, MAX(voltage) as v_max, "
            "MIN(remaining_pct) as pct_min, MAX(remaining_pct) as pct_max, "
            "COUNT(*) as count FROM battery WHERE mission_id = ?", (mid,)
        )
        bat_row = bat[0] if bat else {}

        # Battery start/end
        bat_first = self.store.query(
            "SELECT voltage, remaining_pct FROM battery WHERE mission_id = ? "
            "ORDER BY timestamp ASC LIMIT 1", (mid,)
        )
        bat_last = self.store.query(
            "SELECT voltage, remaining_pct FROM battery WHERE mission_id = ? "
            "ORDER BY timestamp DESC LIMIT 1", (mid,)
        )

        # HUD stats
        hud = self.store.query(
            "SELECT AVG(groundspeed) as avg_gs, MAX(groundspeed) as max_gs, "
            "MAX(climb_rate) as max_climb, AVG(throttle_pct) as avg_throttle, "
            "COUNT(*) as count FROM hud WHERE mission_id = ?", (mid,)
        )
        hud_row = hud[0] if hud else {}

        # Anomaly counts
        anomalies = self.store.query(
            "SELECT event_type, severity, COUNT(*) as count "
            "FROM anomaly_events WHERE mission_id = ? "
            "GROUP BY event_type, severity ORDER BY count DESC", (mid,)
        )
        total_anomalies = sum(a['count'] for a in anomalies)

        # Track data gaps
        if pos_row.get('count', 0) == 0:
            data_gaps.append("no_position_data")
        if bat_row.get('count', 0) == 0:
            data_gaps.append("no_battery_data")
        if hud_row.get('count', 0) == 0:
            data_gaps.append("no_hud_data")

        # Determine confidence
        confidence = "HIGH" if not data_gaps else "MEDIUM"

        duration = 0
        if pos_row.get('t_start') and pos_row.get('t_end'):
            duration = pos_row['t_end'] - pos_row['t_start']

        summary = {
            "mission_id": mid,
            "status": mission.get("status", "UNKNOWN"),
            "duration_seconds": round(duration, 1),
            "position_readings": pos_row.get('count', 0),
            "max_altitude_m": round(pos_row.get('max_alt', 0) or 0, 1),
            "min_altitude_m": round(pos_row.get('min_alt', 0) or 0, 1),
            "total_distance_m": round(total_distance, 1),
            "battery_start_pct": bat_first[0]['remaining_pct'] if bat_first else None,
            "battery_end_pct": bat_last[0]['remaining_pct'] if bat_last else None,
            "voltage_min": round(bat_row.get('v_min', 0) or 0, 2),
            "voltage_max": round(bat_row.get('v_max', 0) or 0, 2),
            "avg_groundspeed_ms": round(hud_row.get('avg_gs', 0) or 0, 1),
            "max_groundspeed_ms": round(hud_row.get('max_gs', 0) or 0, 1),
            "avg_throttle_pct": round(hud_row.get('avg_throttle', 0) or 0, 1),
            "total_anomalies": total_anomalies,
            "anomaly_breakdown": anomalies,
        }

        evidence = [{"type": "mission_metadata", **mission}]
        if anomalies:
            evidence.append({"type": "anomaly_counts", "data": anomalies})

        return QueryResult(
            success=True, summary=summary, evidence=evidence,
            confidence=confidence, data_gaps=data_gaps, correlations=[]
        )

    def _summarise_anomalies(self, intent: QueryIntent) -> QueryResult:
        """Filtered anomaly listing with timeline and severity distribution."""
        mid = intent.mission_id
        atype = intent.anomaly_type

        if atype:
            rows = self.store.query(
                "SELECT * FROM anomaly_events WHERE mission_id = ? AND event_type = ? "
                "ORDER BY timestamp", (mid, atype)
            )
        else:
            rows = self.store.query(
                "SELECT * FROM anomaly_events WHERE mission_id = ? ORDER BY timestamp", (mid,)
            )

        # Group by type and severity
        by_type = {}
        for r in rows:
            et = r['event_type']
            if et not in by_type:
                by_type[et] = {"count": 0, "severities": {}, "first": r['timestamp'], "last": r['timestamp']}
            by_type[et]["count"] += 1
            sev = r['severity']
            by_type[et]["severities"][sev] = by_type[et]["severities"].get(sev, 0) + 1
            if r['timestamp'] < by_type[et]["first"]:
                by_type[et]["first"] = r['timestamp']
            if r['timestamp'] > by_type[et]["last"]:
                by_type[et]["last"] = r['timestamp']

        summary = {
            "mission_id": mid,
            "filter": atype or "all",
            "total_events": len(rows),
            "by_type": by_type,
        }

        return QueryResult(
            success=True, summary=summary, evidence=rows,
            confidence="HIGH" if rows else "LOW",
            data_gaps=[] if rows else ["no_anomalies_found"]
        )

    def _query_time_window(self, intent: QueryIntent) -> QueryResult:
        """All telemetry in a time range for a specific drone."""
        t_start = intent.time_start
        t_end = intent.time_end
        drone = intent.drone_id
        data_gaps = []

        if t_start is None or t_end is None:
            return QueryResult(success=False, summary={"error": "time_start and time_end required"},
                               data_gaps=["missing_time_range"])

        base_where = "timestamp BETWEEN ? AND ?"
        params = (t_start, t_end)
        if drone:
            base_where += " AND drone_id = ?"
            params = (t_start, t_end, drone)

        positions = self.store.query(f"SELECT * FROM positions WHERE {base_where} ORDER BY timestamp", params)
        battery = self.store.query(f"SELECT * FROM battery WHERE {base_where} ORDER BY timestamp", params)
        attitude = self.store.query(f"SELECT * FROM attitude WHERE {base_where} ORDER BY timestamp", params)
        hud_data = self.store.query(f"SELECT * FROM hud WHERE {base_where} ORDER BY timestamp", params)
        anomalies = self.store.query(f"SELECT * FROM anomaly_events WHERE {base_where} ORDER BY timestamp", params)

        if not positions:
            data_gaps.append("no_position_data_in_window")
        if not battery:
            data_gaps.append("no_battery_data_in_window")

        # Build reasoning context and evaluate
        avg_throttle = 0
        if hud_data:
            avg_throttle = sum(h.get('throttle_pct', 0) for h in hud_data) / len(hud_data)

        context = {
            "anomalies": anomalies,
            "deviation_metres": 0,
            "avg_throttle": avg_throttle,
            "time_window": (t_start, t_end),
            "positions": positions,
            "battery": battery,
        }
        correlations = [
            {"rule": c.rule_name, "conclusion": c.conclusion,
             "confidence": c.confidence, "evidence": c.evidence}
            for c in self.reasoning.evaluate(context)
        ]

        summary = {
            "time_start": t_start,
            "time_end": t_end,
            "drone_id": drone,
            "position_count": len(positions),
            "battery_count": len(battery),
            "attitude_count": len(attitude),
            "hud_count": len(hud_data),
            "anomaly_count": len(anomalies),
        }

        return QueryResult(
            success=True, summary=summary,
            evidence=anomalies,
            confidence="HIGH" if positions else "LOW",
            data_gaps=data_gaps, correlations=correlations
        )

    def _battery_profile(self, intent: QueryIntent) -> QueryResult:
        """Battery voltage curve, discharge rate, and stress events."""
        mid = intent.mission_id
        data_gaps = []

        rows = self.store.query(
            "SELECT * FROM battery WHERE mission_id = ? ORDER BY timestamp", (mid,)
        )
        if not rows:
            return QueryResult(success=False, summary={"error": "No battery data"},
                               data_gaps=["no_battery_data"])

        first = rows[0]
        last = rows[-1]
        duration_s = last['timestamp'] - first['timestamp']

        # Discharge rate (% per minute)
        discharge_pct = (first['remaining_pct'] or 0) - (last['remaining_pct'] or 0)
        discharge_rate = (discharge_pct / (duration_s / 60)) if duration_s > 0 else 0

        # Voltage stats per quartile
        n = len(rows)
        q_size = max(1, n // 4)
        quartiles = []
        for i in range(4):
            start_idx = i * q_size
            end_idx = min((i + 1) * q_size, n)
            q_rows = rows[start_idx:end_idx]
            if q_rows:
                voltages = [r['voltage'] for r in q_rows if r['voltage'] is not None]
                if voltages:
                    quartiles.append({
                        "quartile": i + 1,
                        "voltage_min": round(min(voltages), 2),
                        "voltage_max": round(max(voltages), 2),
                        "voltage_mean": round(sum(voltages) / len(voltages), 2),
                    })

        # Stress events from anomaly table
        stress = self.store.query(
            "SELECT * FROM anomaly_events WHERE mission_id = ? "
            "AND event_type IN ('BatteryStress', 'LowBattery') ORDER BY timestamp", (mid,)
        )

        # Health assessment
        if discharge_rate > 10:
            health = "POOR — discharge rate exceeds 10%/min"
        elif discharge_rate > 5:
            health = "FAIR — elevated discharge rate"
        elif stress:
            health = "FAIR — stress events detected"
        else:
            health = "GOOD — normal discharge profile"

        summary = {
            "mission_id": mid,
            "readings": n,
            "duration_seconds": round(duration_s, 1),
            "start_voltage": first['voltage'],
            "end_voltage": last['voltage'],
            "start_pct": first['remaining_pct'],
            "end_pct": last['remaining_pct'],
            "discharge_pct_per_min": round(discharge_rate, 2),
            "voltage_quartiles": quartiles,
            "stress_events": len(stress),
            "health_assessment": health,
        }

        evidence = stress if stress else []
        return QueryResult(
            success=True, summary=summary, evidence=evidence,
            confidence="HIGH", data_gaps=data_gaps
        )

    def _analyse_waypoint(self, intent: QueryIntent) -> QueryResult:
        """Analyse a specific waypoint: deviation, correlated anomalies, battery state."""
        mid = intent.mission_id
        wp_id = intent.waypoint_id
        data_gaps = []

        # Get planned route from parameters or mission table
        planned_route = None
        if intent.parameters and "planned_route" in intent.parameters:
            planned_route = intent.parameters["planned_route"]
        else:
            mission = self.store.get_mission(mid)
            if mission and mission.get("planned_route"):
                import json
                try:
                    planned_route = json.loads(mission["planned_route"])
                except (json.JSONDecodeError, TypeError):
                    pass

        if not planned_route:
            data_gaps.append("no_planned_route")
            return QueryResult(
                success=False,
                summary={"error": "No planned route available", "waypoint_id": wp_id},
                data_gaps=data_gaps
            )

        if wp_id is None or wp_id < 0 or wp_id >= len(planned_route):
            return QueryResult(
                success=False,
                summary={"error": f"Invalid waypoint_id: {wp_id}", "total_waypoints": len(planned_route)},
                data_gaps=["invalid_waypoint_id"]
            )

        wp = planned_route[wp_id]
        wp_lat, wp_lon = wp["lat"], wp["lon"]

        # Get all positions for this mission
        positions = self.store.query(
            "SELECT * FROM positions WHERE mission_id = ? ORDER BY timestamp", (mid,)
        )
        if not positions:
            data_gaps.append("no_position_data")
            return QueryResult(success=False, summary={"error": "No position data"},
                               data_gaps=data_gaps)

        # Find closest actual position to the planned waypoint
        min_dist = float('inf')
        closest_pos = None
        for p in positions:
            d = haversine_metres(wp_lat, wp_lon, p['lat'], p['lon'])
            if d < min_dist:
                min_dist = d
                closest_pos = p

        deviation = min_dist
        closest_ts = closest_pos['timestamp']

        # Get anomalies in ±30s window around closest approach
        window_start = closest_ts - 30
        window_end = closest_ts + 30
        anomalies = self.store.query(
            "SELECT * FROM anomaly_events WHERE mission_id = ? "
            "AND timestamp BETWEEN ? AND ? ORDER BY timestamp",
            (mid, window_start, window_end)
        )

        # Battery state at waypoint
        bat = self.store.query(
            "SELECT * FROM battery WHERE mission_id = ? "
            "AND timestamp BETWEEN ? AND ? ORDER BY timestamp",
            (mid, closest_ts - 5, closest_ts + 5)
        )

        # HUD data for throttle context
        hud_data = self.store.query(
            "SELECT * FROM hud WHERE mission_id = ? "
            "AND timestamp BETWEEN ? AND ? ORDER BY timestamp",
            (mid, window_start, window_end)
        )
        avg_throttle = 0
        if hud_data:
            avg_throttle = sum(h.get('throttle_pct', 0) for h in hud_data) / len(hud_data)

        # Run reasoning engine
        context = {
            "anomalies": anomalies,
            "deviation_metres": deviation,
            "avg_throttle": avg_throttle,
            "time_window": (window_start, window_end),
            "positions": [closest_pos],
            "battery": bat,
        }
        corr_results = self.reasoning.evaluate(context)
        correlations = [
            {"rule": c.rule_name, "conclusion": c.conclusion,
             "confidence": c.confidence, "evidence": c.evidence}
            for c in corr_results
        ]

        # Determine cause if deviation is significant
        cause = None
        if deviation > 10:
            cause = self._determine_cause(anomalies, deviation, avg_throttle)

        summary = {
            "waypoint_id": wp_id,
            "planned_lat": wp_lat,
            "planned_lon": wp_lon,
            "actual_lat": closest_pos['lat'],
            "actual_lon": closest_pos['lon'],
            "deviation_metres": round(deviation, 1),
            "closest_timestamp": closest_ts,
            "anomalies_in_window": len(anomalies),
            "battery_at_waypoint": bat[0] if bat else None,
            "probable_cause": cause,
        }

        confidence = "HIGH" if deviation < 5 or correlations else "MEDIUM"
        evidence = [{"type": "waypoint_position", "planned": wp, "actual": dict(closest_pos)}]
        evidence.extend(anomalies)

        return QueryResult(
            success=True, summary=summary, evidence=evidence,
            confidence=confidence, data_gaps=data_gaps, correlations=correlations
        )

    def _analyse_route_deviation(self, intent: QueryIntent) -> QueryResult:
        """Planned vs actual route comparison with per-waypoint deviation."""
        mid = intent.mission_id
        data_gaps = []

        # Get planned route
        planned_route = None
        if intent.parameters and "planned_route" in intent.parameters:
            planned_route = intent.parameters["planned_route"]
        else:
            mission = self.store.get_mission(mid)
            if mission and mission.get("planned_route"):
                import json
                try:
                    planned_route = json.loads(mission["planned_route"])
                except (json.JSONDecodeError, TypeError):
                    pass

        if not planned_route:
            data_gaps.append("no_planned_route")
            return QueryResult(
                success=False,
                summary={"error": "No planned route available"},
                data_gaps=data_gaps
            )

        positions = self.store.query(
            "SELECT * FROM positions WHERE mission_id = ? ORDER BY timestamp", (mid,)
        )
        if not positions:
            data_gaps.append("no_position_data")
            return QueryResult(success=False, summary={"error": "No position data"},
                               data_gaps=data_gaps)

        # Per-waypoint deviation
        wp_deviations = []
        worst_deviation = 0
        worst_wp = 0

        for i, wp in enumerate(planned_route):
            min_dist = float('inf')
            closest_ts = 0
            for p in positions:
                d = haversine_metres(wp['lat'], wp['lon'], p['lat'], p['lon'])
                if d < min_dist:
                    min_dist = d
                    closest_ts = p['timestamp']

            wp_deviations.append({
                "waypoint_id": i,
                "planned_lat": wp['lat'],
                "planned_lon": wp['lon'],
                "deviation_metres": round(min_dist, 1),
                "closest_timestamp": closest_ts,
            })

            if min_dist > worst_deviation:
                worst_deviation = min_dist
                worst_wp = i

        mean_deviation = sum(w['deviation_metres'] for w in wp_deviations) / len(wp_deviations) if wp_deviations else 0

        # Get anomalies near worst deviation point for reasoning
        worst_ts = wp_deviations[worst_wp]['closest_timestamp'] if wp_deviations else 0
        anomalies = self.store.query(
            "SELECT * FROM anomaly_events WHERE mission_id = ? "
            "AND timestamp BETWEEN ? AND ? ORDER BY timestamp",
            (mid, worst_ts - 30, worst_ts + 30)
        )

        hud_data = self.store.query(
            "SELECT * FROM hud WHERE mission_id = ? "
            "AND timestamp BETWEEN ? AND ? ORDER BY timestamp",
            (mid, worst_ts - 30, worst_ts + 30)
        )
        avg_throttle = 0
        if hud_data:
            avg_throttle = sum(h.get('throttle_pct', 0) for h in hud_data) / len(hud_data)

        context = {
            "anomalies": anomalies,
            "deviation_metres": worst_deviation,
            "avg_throttle": avg_throttle,
            "time_window": (worst_ts - 30, worst_ts + 30),
            "positions": positions,
            "battery": [],
        }
        corr_results = self.reasoning.evaluate(context)
        correlations = [
            {"rule": c.rule_name, "conclusion": c.conclusion,
             "confidence": c.confidence, "evidence": c.evidence}
            for c in corr_results
        ]

        summary = {
            "mission_id": mid,
            "total_waypoints": len(planned_route),
            "mean_deviation_m": round(mean_deviation, 1),
            "max_deviation_m": round(worst_deviation, 1),
            "worst_waypoint_id": worst_wp,
            "per_waypoint": wp_deviations,
        }

        confidence = "HIGH" if worst_deviation < 20 else ("MEDIUM" if correlations else "LOW")

        return QueryResult(
            success=True, summary=summary, evidence=wp_deviations,
            confidence=confidence, data_gaps=data_gaps, correlations=correlations
        )

    # ─── Cause Analysis ─────────────────────────────────────

    def _determine_cause(
        self,
        anomalies: List[Dict[str, Any]],
        deviation: float,
        avg_throttle: float
    ) -> Dict[str, Any]:
        """
        Deterministic decision tree for probable cause analysis.
        Checks anomalies in priority order and returns the most
        likely cause with confidence level.
        
        Priority: signal → battery → motor/attitude → GPS → environmental
        """
        causes = []

        has_signal = any(a.get('event_type') == 'SignalDegraded' for a in anomalies)
        has_signal_crit = any(
            a.get('event_type') == 'SignalDegraded' and a.get('severity') == 'CRITICAL'
            for a in anomalies
        )
        has_battery = any(a.get('event_type') == 'BatteryStress' for a in anomalies)
        has_descent = any(a.get('event_type') == 'RapidDescent' for a in anomalies)
        has_attitude = any(a.get('event_type') == 'ExtremeAttitude' for a in anomalies)
        has_gps = any(a.get('event_type') == 'GPSGlitch' for a in anomalies)
        has_motor = any(a.get('event_type') == 'MotorImbalance' for a in anomalies)

        # 1. Signal — highest priority
        if has_signal_crit:
            causes.append({"cause": "Communication link failure", "confidence": "HIGH"})
        elif has_signal:
            causes.append({"cause": "Signal interference", "confidence": "MEDIUM"})

        # 2. Battery + descent
        if has_battery and has_descent:
            causes.append({"cause": "Battery-induced altitude loss", "confidence": "HIGH"})
        elif has_battery:
            causes.append({"cause": "Battery stress — monitor", "confidence": "MEDIUM"})

        # 3. Attitude + descent (motor failure)
        if has_motor:
            causes.append({"cause": "Hardware motor/ESC failure or severe airframe imbalance", "confidence": "HIGH"})
        elif has_attitude and has_descent:
            causes.append({"cause": "Possible motor/airframe failure", "confidence": "HIGH"})
        elif has_attitude:
            causes.append({"cause": "Attitude instability", "confidence": "MEDIUM"})

        # 4. GPS error
        if has_gps and not has_signal:
            causes.append({"cause": "GPS accuracy issue", "confidence": "MEDIUM"})

        # 5. No anomalies — environmental
        if not anomalies:
            causes.append({"cause": "Environmental factors (wind/turbulence)", "confidence": "LOW"})

        # Return highest confidence cause, or first one
        if not causes:
            return {"cause": "Undetermined", "confidence": "LOW"}

        # Sort: HIGH > MEDIUM > LOW
        priority = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
        causes.sort(key=lambda c: priority.get(c["confidence"], 3))
        return {"primary": causes[0], "alternatives": causes[1:] if len(causes) > 1 else []}

    def get_schema(self) -> Dict[str, Any]:
        """Return the schema registry for LLM context."""
        return SCHEMA_REGISTRY

    def _build_dynamic_sql(self, params: dict) -> tuple[str, list]:
        """Safely build SQL and parameters list from structured intent."""
        table = params.get("table")
        if not table or table not in SCHEMA_REGISTRY:
            raise ValueError(f"Unknown table: {table}")
        
        valid_columns = set(SCHEMA_REGISTRY[table]["columns"].keys())
        cols = params.get("columns", [])
        for c in cols:
            if c not in valid_columns:
                raise ValueError(f"Unknown column: {c} in table {table}")
        
        select_clause = "*"
        if cols:
            select_clause = ", ".join(cols)
            
        aggregations = params.get("aggregations", [])
        if aggregations:
            agg_parts = []
            for agg in aggregations:
                func = agg.get("func", "").upper()
                col = agg.get("column")
                if func not in {"AVG", "MIN", "MAX", "COUNT", "SUM"}:
                    raise ValueError(f"Unsupported aggregation: {func}")
                if col and col not in valid_columns:
                    raise ValueError(f"Unknown column for aggregation: {col}")
                
                if col:
                    agg_parts.append(f"{func}({col})")
                else:
                    agg_parts.append(f"{func}(*)")
            select_clause = ", ".join(agg_parts)
            
        sql = f"SELECT {select_clause} FROM {table} WHERE 1=1"
        sql_params = []
        
        filters = params.get("filters", [])
        for f in filters:
            col = f.get("column")
            op = f.get("op")
            val = f.get("value")
            
            if col not in valid_columns:
                raise ValueError(f"Unknown column in filter: {col}")
            if op not in {"=", "!=", ">", "<", ">=", "<=", "LIKE", "IN"}:
                raise ValueError(f"Unsupported operator: {op}")
            
            if op == "IN" and isinstance(val, list):
                placeholders = ",".join(["?"] * len(val))
                sql += f" AND {col} IN ({placeholders})"
                sql_params.extend(val)
            else:
                sql += f" AND {col} {op} ?"
                sql_params.append(val)
                
        if "time_start" in params and "time_end" in params:
            if "timestamp" in valid_columns:
                sql += " AND timestamp BETWEEN ? AND ?"
                sql_params.extend([params["time_start"], params["time_end"]])
                
        group_by = params.get("group_by")
        if group_by:
            if group_by not in valid_columns:
                raise ValueError(f"Unknown column in GROUP BY: {group_by}")
            sql += f" GROUP BY {group_by}"
            
        order_by = params.get("order_by")
        if order_by:
            if order_by not in valid_columns:
                raise ValueError(f"Unknown column in ORDER BY: {order_by}")
            sql += f" ORDER BY {order_by}"
            if params.get("order_desc", False):
                sql += " DESC"
                
        limit = params.get("limit")
        if limit:
            try:
                limit_val = int(limit)
                sql += f" LIMIT {limit_val}"
            except ValueError:
                pass
                
        return sql, sql_params

    def _attribute_query(self, intent: QueryIntent) -> QueryResult:
        """Handle dynamic attribute queries safely."""
        params = intent.parameters or {}
        
        # Override time range if present in top level intent
        if intent.time_start and intent.time_end:
            params["time_start"] = intent.time_start
            params["time_end"] = intent.time_end
            
        # Add mission/drone filters if provided in intent
        filters = params.get("filters", [])
        if intent.mission_id:
            filters.append({"column": "mission_id", "op": "=", "value": intent.mission_id})
        if intent.drone_id:
            filters.append({"column": "drone_id", "op": "=", "value": intent.drone_id})
        params["filters"] = filters
        
        try:
            sql, sql_params = self._build_dynamic_sql(params)
            evidence = self.store.query(sql, tuple(sql_params))
            return QueryResult(
                success=True,
                summary={"query_executed": sql, "rows_returned": len(evidence)},
                evidence=evidence,
                confidence="HIGH"
            )
        except Exception as e:
            return QueryResult(
                success=False,
                summary={"error": str(e)},
                data_gaps=[f"invalid_query:{str(e)}"],
                confidence="LOW"
            )
