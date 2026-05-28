# SENTINEL Development Plan

Last updated: 2026-05-27

---

## Project Summary

SENTINEL is a mission intelligence system for autonomous drone operations, targeting iDEX DISC Challenge 21: "AI Enabled Multi Agent Module for UAS Functions."

The system connects to drone fleets via MAVLink, ingests telemetry, detects anomalies, correlates events across data streams, and answers operator questions in natural language — with every analytical conclusion backed by deterministic, testable engineering. The LLM only handles natural language parsing and formatting.

---

## Current State (What's Built)

### Core Pipeline — Working

| Capability | Files | Notes |
|------------|-------|-------|
| MAVLink connection (SITL + logs) | `connect.py`, `telemetry.py` | Stable. Live + file extraction. |
| Anomaly detection (5 detectors) | `anomaly.py` | BatteryStress, LowBattery, IdleDrift, RapidDescent, ExtremeAttitude |
| Intelligence report generation | `report.py` | Ollama/llama3.2. Sends full telemetry summary to LLM. |
| CLI live mission monitor | `monitor.py` | Terminal output with rolling anomaly scans. |
| Background live feed for dashboard | `live_feed.py`, `live_state.py` | Thread-safe, polls every 10s for anomalies. |
| FastAPI backend | `api.py` | `/analyze`, `/telemetry/live`, `/monitor/start`, `/monitor/stop` |
| Operator dashboard | `drone-mission-dashboard/` | Next.js. Upload .tlog or connect live. |

### Known Gaps (Identified by Review)

| Gap | Impact | Priority |
|-----|--------|----------|
| No `SignalDegraded` detector | Reasoning rules that check for signal events will never fire | **HIGH** — prerequisite for query engine |
| No `GPSGlitch` detector | "environmental_or_gps" catch-all is too vague for root cause analysis | **HIGH** — prerequisite for query engine |
| No `MotorImbalance` detector | Motor failure pattern rule is weaker without ESC data | MEDIUM — depends on FC support |
| Telemetry in DataFrames only | Can't query by time range, drone, waypoint | **HIGH** — blocks all query functionality |
| No structured query capability | Operator can only get full report, not targeted answers | HIGH — core feature gap |
| No cross-stream correlation | Each detector works in isolation | HIGH — intelligence value is in correlations |
| No conversational context | Follow-up questions like "was that related to..." fail | MEDIUM — needed for NLP layer |
| No mission planning | No path to multi-drone coordination | Future |
| Geographic references unresolvable | "Northern perimeter" has no coordinate mapping | Future — needed with mission planner |

---

## Build Roadmap

### Phase 1: Telemetry Foundation (Weeks 1–2)

**Goal:** Telemetry lives in SQLite. Everything is queryable.

#### Week 1 — SQLite Schema + ETL ✅

- [x] Create `telemetry_store.py` with SQLite schema
  - Tables: positions, battery, attitude, hud, anomaly_events, missions
  - Indexes on `(drone_id, timestamp)` for all telemetry tables
  - Index on `event_type` for anomaly_events
- [x] Write ETL functions: `ingest_dataframes()`, `ingest_tlog()`
- [x] Verify: load the existing 48MB .tlog → query with raw SQL (9.09s, target <30s)
- [x] Write basic tests for schema creation and data insertion (4 tests, all passing)

#### Week 2 — Wire ETL Into Existing Code + New Detectors ✅

- [x] Modify `telemetry.py` to optionally write into SQLite alongside DataFrame return
- [x] Modify `anomaly.py` to store detected events in `anomaly_events` table via `store_anomalies()` helper
- [x] Build `SignalDegraded` detector
  - Source: `RADIO_STATUS` messages (rssi field, 0–254 SiK scale)
  - Thresholds: RSSI < 30 → CRITICAL (~10 dB above sensitivity), RSSI 30–64 → MEDIUM
  - Source: SiK radio documentation, formula: `signal_dBm = (RSSI / 1.9) - 127`
  - Updated `live_feed.py` and `monitor.py` to collect `RADIO_STATUS`
- [x] Build `GPSGlitch` detector
  - Source: `GPS_RAW_INT` messages (eph field = HDOP × 100)
  - Thresholds: eph > 400 (HDOP > 4.0) → CRITICAL, eph 200–400 (HDOP 2.0–4.0) → HIGH
  - Source: ArduPilot `GPS_HDOP_GOOD` parameter (default 140), pre-arm blocks at eph > 200
  - Updated `live_feed.py` and `monitor.py` to collect `GPS_RAW_INT`
- [x] Add both new detectors to `run_all_detectors()`
- [x] Test detectors with synthetic data (15 tests, all passing)

---

### Phase 2: Intelligence Engine (Week 3)

**Goal:** The system can answer structured questions about missions with evidence.

#### Query Engine

- [ ] Create `query_engine.py`
- [ ] Implement query handlers:
  - `analyse_waypoint(waypoint_id, mission_id)` — deviation, correlated anomalies, battery state
  - `query_time_window(start, end, drone_id)` — all telemetry in a time range
  - `summarise_anomalies(mission_id, anomaly_type?)` — filtered anomaly listing
  - `analyse_route_deviation(mission_id)` — planned vs actual with Haversine
  - `battery_profile(mission_id)` — voltage curve, stress events, discharge rate
  - `mission_summary(mission_id)` — full mission overview
- [ ] Implement `_determine_cause()` as a deterministic decision tree
  - Checks signal, battery, attitude, GPS, and environmental causes
  - Returns ranked list of probable causes
- [ ] Write Haversine distance utility

#### Reasoning Engine

- [ ] Create `reasoning.py`
- [ ] Implement named correlation rules:
  - `signal_induced_deviation` — deviation + SignalDegraded → communication interference
  - `battery_forced_descent` — RapidDescent + BatteryStress → power failure
  - `motor_failure_pattern` — ExtremeAttitude + RapidDescent + high throttle → motor issue
  - `gps_position_error` — deviation + GPSGlitch + no signal anomaly → GPS accuracy
  - `environmental_drift` — deviation + no anomalies → wind/environment
- [ ] Each rule: name, description, conditions (lambda), conclusion, confidence level
- [ ] Unit test each rule with synthetic telemetry contexts
- [ ] Verify: run canned queries against stored telemetry, validate results manually

---

### Phase 3: NLP Layer + Agent (Week 4)

**Goal:** Operator types a question, gets a grounded answer. Follow-up questions work.

#### NLP Layer

- [ ] Create `nlp.py`
- [ ] `parse_intent(question, session_context?) → QueryIntent`
  - LLM extracts query type + parameters from natural language
  - Few-shot examples in the prompt for each QueryType
  - JSON output mode for structured extraction
  - Session context injected for follow-up question resolution
- [ ] `format_response(result: QueryResult, session_context?) → str`
  - LLM converts structured result to operational briefing
  - Must reference evidence — no freeform claims
  - Previous context shapes the narrative

#### Mission Session

- [ ] Add `MissionSession` class to `sentinel_agent.py`
  - `query_history: list[(QueryIntent, QueryResult)]`
  - `established_facts: dict` — keyed by query context, not flat merge
  - `open_questions: list`
  - `add_result()` — stores results, updates facts for HIGH confidence
- [ ] Session created per operator conversation
- [ ] Context passed to both `parse_intent()` and `format_response()`

#### Orchestrator

- [ ] Create `sentinel_agent.py`
  - Wires: NLP parse → query engine → reasoning → NLP format
  - Manages MissionSession lifecycle
  - Handles error cases (missing data, unknown query type)
- [ ] Add `/ask` endpoint to `api.py`
  - POST body: `{"question": "...", "session_id": "...", "mission_id": "..."}`
  - Returns: `{"answer": "...", "confidence": "...", "evidence": [...]}`
- [ ] Rewrite `report.py` to use query engine (MISSION_SUMMARY query) instead of raw LLM dump
- [ ] End-to-end test: operator question → grounded natural language answer

---

### Phase 4: MotorImbalance Detector (Week 4, if time)

- [ ] Build `MotorImbalance` detector
  - Source: `ESC_TELEMETRY_1_TO_4` messages
  - Detect asymmetric RPM or current across motors
  - Handle gracefully when ESC telemetry is not available (many FCs don't send it)
- [ ] Add to `run_all_detectors()` with availability check

---

### Phase 5: Mission Planner + Multi-Drone (Weeks 5–8)

**Goal:** System can decompose high-level mission objectives into executable drone plans.

#### Site Configuration

- [ ] Create `site_config.py`
  - Named geographic zones → coordinate polygons
  - e.g. `"northern_perimeter"` → `[(lat, lon), ...]`
  - Hardcode 3-4 zones on SITL map for demo
  - Extensible config file format

#### Mission Planner

- [ ] Create `mission_planner.py`
- [ ] Implement planning algorithms:
  - `plan_perimeter_patrol(perimeter, n_drones)` — geometric partitioning
  - `plan_area_search(bounds, n_drones)` — boustrophedon decomposition + lawnmower patterns
  - `plan_point_inspection(waypoints, n_drones)` — task allocation (Hungarian or greedy)
- [ ] NLP parses mission directives → structured mission objectives
- [ ] Planner converts objectives → waypoint sequences
- [ ] Output: MAVLink-compatible waypoint lists per drone

#### Multi-Drone Infrastructure

- [ ] Multi-SITL setup (multiple ArduPilot instances)
- [ ] Connection manager for multiple simultaneous MAVLink links
- [ ] Per-drone telemetry stores (drone_id partitioning in SQLite)
- [ ] Fleet status query handler
- [ ] Dashboard updates for multi-drone view

---

## Pre-Deployment Checklist

- [ ] Replace `str | None` with `Optional[str]` throughout for Python 3.9+ compatibility
- [ ] Rotate API keys and PAT in `.env` before any public push
- [ ] Add `.env` to `.gitignore` (verify current state)
- [ ] Write integration tests for the full pipeline
- [ ] Performance test SQLite queries with large .tlog files
- [ ] Document API endpoints in OpenAPI (FastAPI auto-generates this)

---

## Verification Strategy

| Phase | Verification |
|-------|-------------|
| Phase 1 | Load .tlog into SQLite → raw SQL queries return correct data |
| Phase 1 | New detectors fire on synthetic RADIO_STATUS and GPS_RAW_INT data |
| Phase 2 | Canned queries against stored telemetry → manually validate results |
| Phase 2 | Each reasoning rule unit tested with synthetic contexts |
| Phase 3 | End-to-end: natural language → correct structured answer with evidence |
| Phase 3 | Follow-up questions resolve references correctly via MissionSession |
| Phase 5 | Generated waypoints visualised on map, validated against mission intent |

---

## File Map (Current → Future)

```
src/
├── connect.py              ← Keep as-is
├── telemetry.py            ← Modify: add SQLite ETL output path
├── anomaly.py              ← Modify: add SignalDegraded, GPSGlitch, MotorImbalance
├── telemetry_store.py      [NEW — Week 1] SQLite schema + ETL functions
├── query_engine.py         [NEW — Week 3] Structured query execution
├── reasoning.py            [NEW — Week 3] Rule-based correlation engine
├── nlp.py                  [NEW — Week 4] Thin LLM wrapper (parse + format)
├── sentinel_agent.py       [NEW — Week 4] Orchestrator + MissionSession
├── mission_planner.py      [NEW — Week 5] Algorithmic mission planning
├── site_config.py          [NEW — Week 5] Geographic zone definitions
├── report.py               ← Rewrite: use query engine instead of raw LLM
├── monitor.py              ← Modify: collect RADIO_STATUS, GPS_RAW_INT
├── live_feed.py            ← Modify: collect new message types, feed ETL
├── live_state.py           ← Keep as-is
├── api.py                  ← Extend: add /ask endpoint
```

---

## Dependencies

### Python (in venv-sentinel)

| Package | Purpose |
|---------|---------|
| pymavlink | MAVLink protocol |
| pandas | Telemetry DataFrames |
| ollama | Local LLM (llama3.2) |
| fastapi | REST API |
| uvicorn | ASGI server |
| python-multipart | File upload handling |
| python-dotenv | Environment variables |

### System

| Component | Purpose |
|-----------|---------|
| ArduPilot SITL | Drone simulator |
| MAVProxy | MAVLink proxy + GCS |
| Ollama | Local LLM runtime |
| Node.js 20+ | Dashboard (Next.js) |
| SQLite3 | Telemetry store (stdlib, no install) |

---

## References

- Architecture decisions: see `ARCHITECTURE.md`
- MAVLink protocol reference: see `MAVLINK.md`
- Setup and troubleshooting: see `README.md`
