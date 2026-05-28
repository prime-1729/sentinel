# SENTINEL Implementation Log

Living document tracking implementation decisions, clarifications, and progress.
Updated as work progresses through each phase.

---

## Phase 1, Week 1 — SQLite Telemetry Store + ETL

### Goal

Transition telemetry from in-memory pandas DataFrames to a persistent, queryable SQLite database. No existing files are modified — the store is built and tested in isolation. Integration wiring happens in Week 2.

### New Files

| File | Purpose |
|------|---------|
| `src/telemetry_store.py` | `TelemetryStore` class — schema, connection management, ETL ingestion |
| `tests/test_telemetry_store.py` | pytest suite with in-memory SQLite |
| `tests/verify_ingest.py` | Integration script — loads real 48MB tlog, prints stats, cleans up |

### Database Schema

Six tables. Column names match existing DataFrame columns from `telemetry.py` exactly (zero transformation during ETL).

**missions** — mission lifecycle tracking
- `mission_id` (PK), `drone_id`, `start_time`, `end_time`, `status`, `planned_route` (JSON)

**positions** — from `GLOBAL_POSITION_INT`
- `drone_id`, `mission_id`, `timestamp`, `lat`, `lon`, `alt_metres`, `relative_alt`, `vx`, `vy`, `vz`

**battery** — from `BATTERY_STATUS`
- `drone_id`, `mission_id`, `timestamp`, `voltage`, `current`, `remaining_pct`

**attitude** — from `ATTITUDE`
- `drone_id`, `mission_id`, `timestamp`, `roll_deg`, `pitch_deg`, `yaw_deg`

**hud** — from `VFR_HUD`
- `drone_id`, `mission_id`, `timestamp`, `airspeed`, `groundspeed`, `altitude`, `climb_rate`, `throttle_pct`

**anomaly_events** — from anomaly detectors
- `drone_id`, `mission_id`, `timestamp`, `event_type`, `severity`, `detail`, `recommendation`

**Indexes:** composite `(drone_id, timestamp)` on every telemetry table, plus `event_type` on anomaly_events.

### TelemetryStore API

```python
class TelemetryStore:
    def __init__(self, db_path="data/sentinel.db")
    def create_mission(self, mission_id, drone_id) -> None
    def complete_mission(self, mission_id) -> None
    def ingest_dataframes(self, telemetry: dict, drone_id, mission_id) -> dict  # returns row counts
    def ingest_tlog(self, filepath, drone_id="drone_0", mission_id=None) -> dict
    def ingest_anomalies(self, anomalies: list, drone_id, mission_id) -> int
    def query(self, sql, params=()) -> list[dict]
    def get_mission(self, mission_id) -> dict | None
    def close(self)
```

### Design Clarifications

**Why "attitude" not "altitude"?**
In aerospace, *attitude* means the vehicle's orientation — roll, pitch, yaw angles. The table stores `roll_deg`, `pitch_deg`, `yaw_deg`. Altitude (height above ground) lives in the `positions` table as `relative_alt` and `alt_metres`. The name matches the MAVLink `ATTITUDE` message and is standard drone terminology.

**Why is HUD its own table?**
`VFR_HUD` (Visual Flight Rules Head-Up Display) is a standard MAVLink message providing pilot-oriented data. It has fields not available from other messages:
- `groundspeed` + `throttle_pct` — used by the `IdleDrift` detector
- `airspeed` — not in any other message
- `climb_rate` — instantaneous vertical speed, more granular than computing from position deltas

There's some altitude overlap with positions, but the unique fields are needed by existing detectors and the future query engine.

**Is SQLite scalable for high-frequency telemetry?**
Yes, for our scope. A 1-hour mission generates ~150k total rows. SQLite with WAL mode + `executemany` handles 50k+ inserts/second. The live monitor (`live_feed.py`) keeps its rolling in-memory buffer for real-time — SQLite is the *analytical store* for post-mission queries and the Week 3 query engine. If we ever scale to 50+ simultaneous drones, we'd move to TimescaleDB, but for SITL and iDEX demo, SQLite is correct.

**Database file location:** `data/sentinel.db` — same directory as `data/test_mission.tlog`.

### Verification

```bash
# Unit tests
pytest tests/test_telemetry_store.py -v

# Integration — loads real 48MB tlog, prints row counts and timing
python tests/verify_ingest.py
```

Performance target: 48MB tlog ingests in under 30 seconds.

### Week 1 Results

- 4 pytest tests passing (schema, mission lifecycle, DataFrame ingestion, anomaly ingestion)
- 48MB tlog ingested in **9.09 seconds** (target: <30s)
- 161,887 total rows across positions (40,472), battery (40,471), attitude (40,472), hud (40,472)

---

## Phase 1, Week 2 — ETL Wiring + New Detectors

### Goal

Wire the SQLite `TelemetryStore` into the existing data extraction and monitoring pipelines. Add two new anomaly detectors (`SignalDegraded`, `GPSGlitch`) with industry-standard thresholds sourced from ArduPilot documentation and hardware specifications.

### Files Modified

| File | Changes |
|------|---------|
| `src/telemetry.py` | Added `RADIO_STATUS` and `GPS_RAW_INT` parsing to both `extract_telemetry()` and `extract_telemetry_from_file()`. Added optional `store_in_db` parameter for SQLite persistence. |
| `src/anomaly.py` | Added `detect_signal_degraded()`, `detect_gps_glitch()`, `store_anomalies()` helper. Updated `run_all_detectors()`. Replaced all hardcoded thresholds with sourced values. |
| `src/monitor.py` | Added `radio` and `gps` rolling buffers. Parses `RADIO_STATUS` and `GPS_RAW_INT`. Runs new detectors. Stores anomalies to SQLite via `store_anomalies()`. |
| `src/live_feed.py` | Same changes as `monitor.py` — new buffers, message parsing, detector execution, SQLite persistence. |

### New Files

| File | Purpose |
|------|---------|
| `tests/test_anomaly.py` | 15 pytest tests covering all 7 detectors with synthetic data |

### Anomaly Detector Thresholds (Industry-Sourced)

All thresholds are sourced from ArduPilot parameter defaults, MAVLink hardware specifications, and LiPo battery engineering standards. Each detector docstring in `anomaly.py` cites the specific source.

#### BatteryStress — Voltage Sag
- **Threshold:** > 0.5V drop between readings
- **Rationale:** Normal flight sag is 0.1–0.3V per LiPo engineering. Drops > 0.5V indicate dangerous load sag or cell failure.
- **Source:** ArduPilot battery failsafe docs (`ardupilot.org/copter/docs/failsafe-battery`). ArduPilot's `BATT_LOW_VOLT` default is 10.5V (3.5V/cell for 3S LiPo).

#### LowBattery — Two-Stage Alert
- **HIGH:** Battery < 20% remaining — maps to ArduPilot's `BATT_LOW_MAH` (low-battery warning stage)
- **CRITICAL:** Battery < 10% remaining — maps to ArduPilot's `BATT_CRT_MAH` (critical stage, forced land)
- **Source:** ArduPilot battery failsafe two-layer system

#### IdleDrift — Throttle vs Groundspeed
- **Throttle threshold:** > 25% (ArduPilot's `MOT_SPIN_MIN` default is ~15%, `MOT_SPIN_ARM` ~10%)
- **Groundspeed threshold:** < 0.3 m/s (GPS noise floor is ~0.1–0.2 m/s; 0.3 adds margin)
- **Duration:** > 5 readings to avoid false positives from waypoint hover holds

#### RapidDescent — Altitude Drop Rate
- **Threshold:** > 2.0m altitude loss per reading (~5+ m/s at 4 Hz telemetry rate)
- **Rationale:** ArduPilot's `WPNAV_SPEED_DN` default is 150 cm/s (1.5 m/s). `LAND_SPEED_HIGH` max is 500 cm/s (5 m/s). Descent exceeding 5 m/s is beyond any commanded rate.
- **Source:** ArduPilot Copter descent parameters. Crash check triggers at 30° lean error for 2 seconds.

#### ExtremeAttitude — Roll/Pitch Breach
- **Threshold:** Roll or Pitch > 45°
- **Source:** ArduPilot `ANGLE_MAX` parameter default = 4500 centidegrees (45°). This is the maximum lean angle the flight controller commands in stabilised modes. Exceeding it means loss of stabilisation authority. ArduPilot crash check triggers at 30° lean error.

#### SignalDegraded — Radio RSSI (Two-Tier)
- **CRITICAL:** RSSI < 30 (≈ -111 dBm, ~10 dB above SiK receiver sensitivity of -121 dBm). Link loss imminent.
- **MEDIUM:** RSSI 30–64 (≈ -93 dBm, ~28 dB above sensitivity). Degraded but functional.
- **Scale:** SiK radios use 0–254 raw scale. Healthy radios show > 190 at close range.
- **Conversion:** `signal_dBm = (RSSI / 1.9) - 127`
- **Source:** SiK radio documentation, ArduPilot telemetry docs

#### GPSGlitch — HDOP via GPS_RAW_INT.eph (Two-Tier)
- **CRITICAL:** eph > 400 (HDOP > 4.0). Navigation unreliable. Position errors 8–10m+. EKF may lose confidence.
- **HIGH:** eph 200–400 (HDOP 2.0–4.0). Exceeds ArduPilot's pre-arm limit. GPS-dependent modes degraded.
- **Source:** ArduPilot `GPS_HDOP_GOOD` parameter (default 140 = HDOP 1.4). Pre-arm check blocks arming when HDOP > 2.0 (eph > 200).

### Design Clarifications

**Why two-tier severity for Signal and GPS?**
A single threshold misses the operational difference between "degraded but flyable" and "link loss imminent." ArduPilot itself uses two-stage failsafes for battery (low → critical). We apply the same pattern to signal and GPS, giving operators time to react before the situation becomes critical.

**Why `store_anomalies()` instead of direct DB calls in anomaly.py?**
The helper function in `anomaly.py` wraps `TelemetryStore.ingest_anomalies()` and handles the dataclass-to-dict conversion. This keeps the database layer cleanly separated from the detection logic. `monitor.py` and `live_feed.py` call `store_anomalies()` after each scan window rather than embedding database code in the detector functions.

**Why not store raw RADIO_STATUS and GPS_RAW_INT in SQLite?**
For Phase 1, these streams feed the detectors in-memory only. The anomaly *events* they produce are stored in `anomaly_events`. Storing raw radio/GPS rows would add ~80k rows per hour with minimal query value. If the Phase 2 query engine needs them, we'll add dedicated tables.

### Verification

```bash
# All tests (Week 1 + Week 2)
PYTHONPATH=. pytest tests/ -v

# Week 2 detector tests only
PYTHONPATH=. pytest tests/test_anomaly.py -v
```

Week 2 results: **15 tests passing in 0.16 seconds.**

### Files NOT Modified

`api.py`, `report.py`, `live_state.py`, `connect.py` — untouched. These are targets for Phase 2/3.

---

*Next section will be added when Phase 2 begins.*
