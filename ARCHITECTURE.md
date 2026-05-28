# SENTINEL Architecture

> Engineering does the thinking. The LLM does the talking.

This document is the single source of truth for SENTINEL's system design.
Any agent or developer working on this codebase should read this first.

---

## Design Principles

1. **Deterministic core.** Every conclusion traces to a named rule or calculation. Same telemetry in → same analysis out. No probabilistic reasoning in the critical path.
2. **LLM at the edges only.** The LLM parses operator questions into structured queries, and formats structured results into natural language. It never sees raw telemetry and never makes analytical decisions.
3. **Runs air-gapped.** The system must work on a laptop in a field tent with no internet. Local Ollama (llama3.2) handles the NLP layer. No cloud API dependencies in the core pipeline.
4. **Everything queryable.** Telemetry lives in SQLite, not in-memory DataFrames. Any question about a mission is a SQL query, not a DataFrame scan.

---

## System Topology

```
OPERATOR (natural language)
         ↓
┌─────────────────────────┐
│   NLP LAYER (LLM)       │  ← Only LLM in the system
│   • Parse intent         │     Ollama / llama3.2 (local)
│   • Extract parameters   │
└────────┬────────────────┘
         ↓
    QueryIntent (dataclass)
         ↓
┌─────────────────────────────────────────────┐
│              ENGINEERING CORE                │
│                                              │
│  ┌──────────────┐  ┌────────────────────┐    │
│  │ TELEMETRY    │  │ QUERY ENGINE       │    │
│  │ ETL          │  │ (deterministic)    │    │
│  │ MAVLink →    │  │ Executes structured│    │
│  │ SQLite       │  │ queries against    │    │
│  │              │  │ telemetry store    │    │
│  └──────┬───────┘  └────────┬───────────┘    │
│         ↓                   ↓                │
│  ┌───────────────────────────────────────┐   │
│  │ TELEMETRY STORE (SQLite)              │   │
│  │ • positions, battery, attitude, hud   │   │
│  │ • anomaly_events                      │   │
│  │ • missions                            │   │
│  │ • Indexed by timestamp + drone_id     │   │
│  └───────────────────────────────────────┘   │
│                                              │
│  ┌──────────────┐  ┌────────────────────┐    │
│  │ ANOMALY      │  │ REASONING ENGINE   │    │
│  │ DETECTOR     │  │ (rule-based)       │    │
│  │              │  │ Named correlation  │    │
│  │              │  │ rules across       │    │
│  │              │  │ telemetry streams  │    │
│  └──────────────┘  └────────────────────┘    │
│                                              │
│  ┌──────────────┐  ┌────────────────────┐    │
│  │ MISSION      │  │ MISSION SESSION    │    │
│  │ PLANNER      │  │ (conversational    │    │
│  │ (algorithmic)│  │  context memory)   │    │
│  └──────────────┘  └────────────────────┘    │
│                                              │
└──────────────────────────────────────────────┘
         ↓
    QueryResult (dataclass)
         ↓
┌─────────────────────────┐
│   NLP LAYER (LLM)       │  ← Same LLM, just formatting
│   • Convert result to   │
│     natural language     │
└─────────────────────────┘
         ↓
OPERATOR (plain-language answer with evidence)
```

---

## Data Flow

### Live Mission

```
ArduPilot SITL / Real Hardware
       ↓  MAVLink UDP
MAVProxy (port 14550 = console, 14551 = SENTINEL)
       ↓  MAVLink UDP
┌─────────────────────────────────────┐
│ live_feed.py (background thread)    │
│  • Receives GLOBAL_POSITION_INT,    │
│    BATTERY_STATUS, ATTITUDE, VFR_HUD│
│  • Buffers 60s rolling window       │
│  • Runs anomaly detection each 10s  │
│  • Updates live_state.py (in-mem)   │
│  • [FUTURE] Writes to SQLite via ETL│
└─────────┬───────────────────────────┘
          ↓
┌─────────────────────────────────────┐
│ live_state.py (thread-safe dict)    │
│  • Polled by dashboard via API      │
│  • Latest altitude, speed, battery, │
│    voltage, position, anomalies     │
└─────────────────────────────────────┘
```

### Log File Analysis

```
.tlog / .bin file
       ↓
┌─────────────────────────────────────┐
│ telemetry.py                        │
│  extract_telemetry_from_file()      │
│  • Replays all MAVLink messages     │
│  • Returns DataFrames               │
│  • [FUTURE] Writes to SQLite via ETL│
└─────────┬───────────────────────────┘
          ↓
┌─────────────────────────────────────┐
│ anomaly.py → run_all_detectors()    │
│ report.py  → LLM summary           │
└─────────────────────────────────────┘
```

### Operator Query (Future — Week 3-4)

```
"Was the mission compromised at waypoint 4?"
       ↓
nlp.py → parse_intent()           [LLM: ~1s]
       ↓
QueryIntent(WAYPOINT_ANALYSIS, waypoint_id=4)
       ↓
query_engine.py → analyse_waypoint()  [SQL + Python: ~50ms]
  • Planned position from missions table
  • Actual positions ±30s of waypoint ETA
  • Haversine deviation calculation
  • Correlated anomalies in same window
  • Battery state in same window
       ↓
reasoning.py → evaluate_rules()       [Python: ~10ms]
  • Matches named correlation rules
  • e.g. "signal_induced_deviation"
       ↓
QueryResult(summary, evidence, confidence)
       ↓
nlp.py → format_response()       [LLM: ~2s]
       ↓
"Waypoint 4 was compromised. Position deviation of 47.2 metres..."
```

---

## Component Registry

### Existing (Built)

| File | Role | Status |
|------|------|--------|
| `connect.py` | MAVLink connection + raw message reader | Stable |
| `telemetry.py` | Live + file telemetry extraction → DataFrames | Stable, needs ETL output |
| `anomaly.py` | Anomaly detection (5 detectors) | Stable, needs 3 more detectors |
| `report.py` | After-action report via Ollama | Stable, will be replaced by query engine |
| `monitor.py` | CLI live monitor with anomaly alerts | Stable |
| `live_feed.py` | Background MAVLink thread for dashboard | Stable |
| `live_state.py` | Thread-safe telemetry store for API polling | Stable |
| `api.py` | FastAPI backend (analyze, live, monitor) | Stable, needs `/ask` endpoint |

### Planned (To Build)

| File | Role | Target |
|------|------|--------|
| `telemetry_store.py` | SQLite schema + ETL functions | Week 1-2 |
| `query_engine.py` | Structured query execution | Week 3 |
| `reasoning.py` | Rule-based cross-stream correlation | Week 3 |
| `nlp.py` | Thin LLM wrapper (parse + format only) | Week 4 |
| `sentinel_agent.py` | Orchestrator: NLP → Engine → NLP | Week 4 |
| `mission_planner.py` | Algorithmic mission decomposition | Week 5-8 |
| `site_config.py` | Named geographic zones → coordinate polygons | Week 5 |

---

## Anomaly Detectors

Each detector takes a DataFrame, returns `List[AnomalyEvent]`.

| Detector | MAVLink Source | Trigger | Severity | Status |
|----------|---------------|---------|----------|--------|
| `BatteryStress` | `BATTERY_STATUS` | Voltage drop > 0.2V between readings | HIGH | ✅ Built |
| `LowBattery` | `BATTERY_STATUS` | remaining_pct < 20% | CRITICAL | ✅ Built |
| `IdleDrift` | `VFR_HUD` | Throttle > 30% but groundspeed < 0.1 for 5+ readings | MEDIUM | ✅ Built |
| `RapidDescent` | `GLOBAL_POSITION_INT` | Altitude drop > 3m per reading | CRITICAL | ✅ Built |
| `ExtremeAttitude` | `ATTITUDE` | Roll or pitch > 45° | CRITICAL | ✅ Built |
| `SignalDegraded` | `RADIO_STATUS` | RSSI < 50 (remrssi or rssi) | HIGH | ❌ Needed for reasoning rules |
| `GPSGlitch` | `GPS_RAW_INT` | HDOP (eph) > 200 | MEDIUM | ❌ Needed for reasoning rules |
| `MotorImbalance` | `ESC_TELEMETRY_1_TO_4` | Asymmetric RPM/current across motors | HIGH | ❌ Optional (not all FC send this) |

---

## Reasoning Rules

Named, testable condition → conclusion pairs. No LLM involved.

| Rule Name | Conditions | Conclusion | Confidence |
|-----------|-----------|------------|------------|
| `signal_induced_deviation` | deviation > 20m AND `SignalDegraded` within 30s | Communication interference | HIGH |
| `battery_forced_descent` | `RapidDescent` within 10s AND `BatteryStress` within 30s | Battery voltage drop caused altitude loss | HIGH |
| `motor_failure_pattern` | `ExtremeAttitude` AND `RapidDescent` within 5s AND avg throttle > 70% | Partial motor failure | MEDIUM |
| `gps_position_error` | deviation > 20m AND `GPSGlitch` within 30s AND no signal anomaly | GPS accuracy issue, not real deviation | MEDIUM |
| `environmental_drift` | deviation > 20m AND no anomalies in window | Wind or environmental factor | LOW |

---

## SQLite Schema (Telemetry Store)

Six tables, indexed by `(drone_id, timestamp)`:

- **positions** — lat, lon, alt, relative_alt, velocity components
- **battery** — voltage, current_draw, remaining_pct
- **attitude** — roll_deg, pitch_deg, yaw_deg
- **hud** — airspeed, groundspeed, altitude, climb_rate, throttle_pct
- **anomaly_events** — event_type, severity, detail, recommendation
- **missions** — mission_id, drone_id, start/end time, status, planned_route (JSON)

All tables include `drone_id` and `mission_id` columns for multi-drone support.

---

## Key Interfaces

### QueryIntent → QueryResult

```python
class QueryType(Enum):
    WAYPOINT_ANALYSIS = "waypoint_analysis"
    TIME_WINDOW = "time_window"
    ANOMALY_SUMMARY = "anomaly_summary"
    ROUTE_DEVIATION = "route_deviation"
    BATTERY_PROFILE = "battery_profile"
    FLEET_STATUS = "fleet_status"
    MISSION_SUMMARY = "mission_summary"
    CORRELATION = "correlation"

@dataclass
class QueryIntent:
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
    success: bool
    summary: dict
    evidence: list[dict]
    confidence: str          # HIGH / MEDIUM / LOW
    data_gaps: list[str]
```

### MissionSession (Conversational Context)

```python
class MissionSession:
    def __init__(self, mission_id: str):
        self.mission_id = mission_id
        self.query_history = []           # list of (QueryIntent, QueryResult)
        self.established_facts = {}       # keyed by query context
        self.open_questions = []          # unresolved items

    def add_result(self, intent: QueryIntent, result: QueryResult):
        self.query_history.append((intent, result))
        if result.confidence == "HIGH":
            fact_key = f"{intent.query_type.value}_{intent.waypoint_id or intent.drone_id or 'general'}"
            self.established_facts[fact_key] = {
                "intent": intent,
                "summary": result.summary,
                "timestamp": time.time()
            }
```

---

## MAVLink Messages

SENTINEL consumes these message types. See `MAVLINK.md` for the full reference.

| Message | Purpose | Used By |
|---------|---------|---------|
| `HEARTBEAT` | Connection verification | `connect.py` |
| `GLOBAL_POSITION_INT` | GPS + altitude + velocity | `telemetry.py`, `live_feed.py`, `monitor.py` |
| `BATTERY_STATUS` | Voltage, current, remaining % | `telemetry.py`, `live_feed.py`, `monitor.py` |
| `ATTITUDE` | Roll, pitch, yaw (radians → degrees) | `telemetry.py`, `live_feed.py`, `monitor.py` |
| `VFR_HUD` | Groundspeed, airspeed, throttle, climb | `telemetry.py`, `live_feed.py`, `monitor.py` |
| `RADIO_STATUS` | RSSI, remote RSSI, noise | **Planned:** `SignalDegraded` detector |
| `GPS_RAW_INT` | Fix type, HDOP, satellite count | **Planned:** `GPSGlitch` detector |
| `ESC_TELEMETRY_1_TO_4` | Per-motor RPM, current, voltage | **Planned:** `MotorImbalance` detector |

---

## API Surface

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/` | GET | Health check |
| `/health` | GET | System status + live monitor state |
| `/analyze` | POST | Upload .tlog → anomalies + intelligence report |
| `/telemetry/live` | GET | Latest live telemetry snapshot |
| `/monitor/start` | POST | Start background MAVLink monitor |
| `/monitor/stop` | POST | Stop background MAVLink monitor |
| `/ask` | POST | **Planned:** Natural language query endpoint |

---

## Infrastructure

| Component | Technology | Notes |
|-----------|-----------|-------|
| Language | Python 3.12 | Use `Optional[T]` over `T | None` for deployment compatibility |
| Telemetry store | SQLite | Zero infrastructure, single file, runs anywhere |
| LLM | Ollama + llama3.2 | Local, air-gapped, no API costs |
| API | FastAPI + Uvicorn | Async, auto-docs at `/docs` |
| Dashboard | Next.js (TypeScript) | Operator UI at localhost:3000 |
| Simulator | ArduPilot SITL + MAVProxy | MAVLink over UDP |
| Drone protocol | MAVLink v2 via pymavlink | |

---

## Target

iDEX DISC Challenge 21: "AI Enabled Multi Agent Module for UAS Functions"
