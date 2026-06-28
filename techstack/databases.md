# Database Strategy for SENTINEL

> **Purpose:** Research the right database(s) for drone telemetry at different tiers.

Last Updated: 2026-06-21

---

## 1. Different Tiers, Different Needs

| Tier | Location | Write Rate | Query Pattern | Constraints |
|---|---|---|---|---|
| **Tier 1 (Drone)** | Companion computer | 10-100 Hz | Local telemetry, state sync | ≤4GB RAM, SD card |
| **Tier 2 (GCS)** | Laptop / field server (Optional) | 10-100 Hz × N drones | Operator dashboards, NLP | Air-gapped |
| **Tier 3 (Post-mission)** | Analyst workstation | Batch | Analytics, ML training | More powerful hardware |

---

## 2. Candidate Databases

### SQLite
- **Footprint:** ~600KB, zero config, zero admin, embedded
- **Write speed:** ~50K inserts/sec (WAL mode)
- **Concurrency:** Single-writer, multiple-reader
- **Edge suitability:** ★★★★★
- ✅ Tier 1 (Drone): Perfect. Zero overhead, crash-safe. Stores local logs and CRDT state.
- 🔶 Tier 2 (GCS): Adequate for basic operator display, but GCS is optional.
- ❌ Tier 3: Too limited for serious analytics.

### TimescaleDB (PostgreSQL Extension)
- **Footprint:** ~200MB (PostgreSQL server required)
- **Write speed:** ~100K+ inserts/sec (batch)
- **Concurrency:** Full multi-writer (PostgreSQL MVCC)
- **Features:** Hypertables (auto time-partition), continuous aggregates, PostGIS for geospatial
- ❌ Tier 1: Too heavy for companion computer
- ✅ Tier 2 (GCS): Excellent. Concurrent writes, geospatial queries, fleet aggregations.
- ✅ Tier 3: Full analytics capability.

### InfluxDB
- **Footprint:** ~100MB binary, server process required
- **Write speed:** ~1M+ points/sec
- **Features:** Purpose-built time-series. Custom query language (NOT standard SQL).
- ❌ Tier 1: Overkill
- 🔶 Tier 2: Good for metrics, but weak joins and non-standard SQL
- ✅ Tier 3: Excellent for dashboards (Grafana native)

### DuckDB
- **Footprint:** ~20MB, embedded (no server)
- **Optimized for:** Analytical queries (columnar storage)
- ❌ Tier 1: Not great for streaming writes
- ✅ Tier 3: Excellent for fleet-wide aggregations and ML data prep

---

## 3. Recommended Strategy

```
TIER 1 (Drone):  SQLite (WAL mode)
    → Zero overhead, crash-safe. Stores local telemetry + anomaly events.
    → Maintains local CRDT state for fleet-wide sync.

TIER 2 (GCS - Optional): TimescaleDB
    → Multi-writer for N drone feeds, PostGIS for geospatial,
      time_bucket() for fleet aggregations, retention policies
    → Standard SQL = minimal code rewrite from SQLite

TIER 3 (Post):   DuckDB or TimescaleDB
    → Historical archives, ML training data
```

### Why Move From SQLite on GCS?

| Scenario | SQLite Limitation | TimescaleDB Advantage |
|---|---|---|
| 5 drones writing simultaneously | Single-writer lock | Full MVCC concurrency |
| "Drones within 500m of threat?" | No geospatial. Haversine in Python. | PostGIS: `ST_DWithin()` |
| "Avg battery, 5-min windows" | Manual subqueries | `time_bucket()` native |
| Auto-delete data > 30 days | Manual DELETE query | `add_retention_policy()` |

### Migration Path

| Phase | Database | Reason |
|---|---|---|
| Now (SITL dev) | SQLite | Local testing |
| Multi-drone SITL | SQLite on Edge | CRDT state sync over mesh |
| Physical drones | SQLite on drone + TimescaleDB on GCS | Tiered storage |

---

## 4. Open Questions

| Question | Options | Impact |
|---|---|---|
| When to migrate from SQLite on GCS? | With multi-drone, or earlier? | Affects all query code |
| TimescaleDB vs InfluxDB for GCS? | SQL vs custom language | TimescaleDB wins — SQL compatibility |
| Edge-to-GCS sync strategy? | Event-push vs periodic bulk | Architecture decision |
| Schema migration tool? | Alembic vs Flyway | Needed for production |
