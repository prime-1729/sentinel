import json
from typing import Dict, Any, List
from telemetry_store import TelemetryStore

def query_sql(sql: str) -> Dict[str, Any]:
    """
    Execute a read-only SQL query against the SENTINEL telemetry database.
    Useful for ad-hoc queries, aggregation, and specific metric lookups.
    """
    # Guard against destructive queries
    if any(kw in sql.upper() for kw in ["INSERT", "UPDATE", "DELETE", "DROP", "ALTER"]):
        return {"error": "Only read-only SELECT queries are allowed."}
        
    store = TelemetryStore()
    try:
        results = store.query(sql)
        # Prevent massive result sets from blowing up the context window
        if len(results) > 100:
            return {
                "warning": f"Result set too large ({len(results)} rows). Returning first 100.",
                "rows": results[:100]
            }
        return {"rows": results}
    except Exception as e:
        return {"error": str(e)}
    finally:
        store.close()

def get_flight_path(mission_id: str, sample_rate: int = 20) -> Dict[str, Any]:
    """
    Get a sampled position timeline for a mission. 
    Returns lat, lon, alt, and timestamp to understand drone movement.
    """
    store = TelemetryStore()
    try:
        sql = """
            SELECT timestamp, lat, lon, relative_alt, vx, vy, vz
            FROM positions 
            WHERE mission_id = ? 
            ORDER BY timestamp ASC
        """
        rows = store.query(sql, (mission_id,))
        if not rows:
            return {"error": f"No position data found for mission {mission_id}"}
            
        sampled = rows[::sample_rate]
        # Always include the last point to show where it ended up
        if rows[-1] not in sampled:
            sampled.append(rows[-1])
            
        return {
            "total_points": len(rows),
            "sampled_points": len(sampled),
            "path": sampled
        }
    except Exception as e:
        return {"error": str(e)}
    finally:
        store.close()

def get_anomalies(mission_id: str, event_type: str = None) -> Dict[str, Any]:
    """
    Get all detected anomalies for a mission, optionally filtered by type.
    Returns timestamps, severity, and details.
    """
    store = TelemetryStore()
    try:
        sql = """
            SELECT timestamp, event_type, severity, detail
            FROM anomaly_events
            WHERE mission_id = ?
        """
        params = [mission_id]
        
        if event_type:
            sql += " AND event_type = ?"
            params.append(event_type)
            
        sql += " ORDER BY timestamp ASC"
        
        rows = store.query(sql, tuple(params))
        return {
            "count": len(rows),
            "events": rows
        }
    except Exception as e:
        return {"error": str(e)}
    finally:
        store.close()

def get_mission_stats(mission_id: str) -> Dict[str, Any]:
    """
    Get high-level summary statistics for a mission (duration, max alt, min battery).
    """
    store = TelemetryStore()
    try:
        stats = {}
        
        # Duration
        pos_rows = store.query(
            "SELECT MIN(timestamp) as start, MAX(timestamp) as end FROM positions WHERE mission_id = ?", 
            (mission_id,)
        )
        if pos_rows and pos_rows[0]['start'] and pos_rows[0]['end']:
            stats['duration_seconds'] = round(pos_rows[0]['end'] - pos_rows[0]['start'], 1)
            
        # Max Altitude
        alt_rows = store.query(
            "SELECT MAX(relative_alt) as max_alt FROM positions WHERE mission_id = ?",
            (mission_id,)
        )
        if alt_rows and alt_rows[0]['max_alt'] is not None:
            stats['max_altitude_metres'] = round(alt_rows[0]['max_alt'], 1)
            
        # Min Battery
        batt_rows = store.query(
            "SELECT MIN(remaining_pct) as min_batt FROM battery WHERE mission_id = ?",
            (mission_id,)
        )
        if batt_rows and batt_rows[0]['min_batt'] is not None:
            stats['min_battery_pct'] = round(batt_rows[0]['min_batt'], 1)
            
        # Anomaly Summary
        anom_rows = store.query(
            "SELECT event_type, COUNT(*) as count FROM anomaly_events WHERE mission_id = ? GROUP BY event_type",
            (mission_id,)
        )
        stats['anomaly_counts'] = {r['event_type']: r['count'] for r in anom_rows}
        
        return stats
    except Exception as e:
        return {"error": str(e)}
    finally:
        store.close()

# The definitions that we will pass to Ollama's tool calling API
OLLAMA_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "query_sql",
            "description": "Execute a read-only SQL query against the SENTINEL telemetry database. Use this to lookup specific metrics not covered by other tools. Tables: positions, battery, attitude, hud, anomaly_events, missions.",
            "parameters": {
                "type": "object",
                "properties": {
                    "sql": {
                        "type": "string", 
                        "description": "The exact SQL SELECT query to execute. Example: SELECT MAX(groundspeed) FROM hud WHERE mission_id = 'mission_123'"
                    }
                },
                "required": ["sql"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_flight_path",
            "description": "Get a sampled position timeline (lat, lon, alt) for a mission. Use this when you need to understand where the drone went, its altitude changes, or its route over time.",
            "parameters": {
                "type": "object",
                "properties": {
                    "mission_id": {
                        "type": "string",
                        "description": "The ID of the mission"
                    },
                    "sample_rate": {
                        "type": "integer",
                        "description": "Return every Nth point. Default is 20. Use a smaller number (e.g. 5) for more detail, or larger (e.g. 50) for less.",
                        "default": 20
                    }
                },
                "required": ["mission_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_anomalies",
            "description": "Get a list of all detected anomalies for a mission. Provides the exact timestamp, severity, and details of what went wrong. Crucial for diagnosing operational issues.",
            "parameters": {
                "type": "object",
                "properties": {
                    "mission_id": {
                        "type": "string",
                        "description": "The ID of the mission"
                    },
                    "event_type": {
                        "type": "string",
                        "description": "Optional filter for a specific anomaly type (e.g., 'IdleDrift', 'LowBattery')"
                    }
                },
                "required": ["mission_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_mission_stats",
            "description": "Get high-level summary statistics for a mission, including duration, max altitude, minimum battery remaining, and a count of anomaly types. Always a good starting point for a mission briefing.",
            "parameters": {
                "type": "object",
                "properties": {
                    "mission_id": {
                        "type": "string",
                        "description": "The ID of the mission"
                    }
                },
                "required": ["mission_id"]
            }
        }
    }
]

# Mapping from tool name to python function
TOOL_MAP = {
    "query_sql": query_sql,
    "get_flight_path": get_flight_path,
    "get_anomalies": get_anomalies,
    "get_mission_stats": get_mission_stats
}
