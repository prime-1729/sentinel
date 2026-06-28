# SENTINEL Service Architecture

> **Purpose:** The complete system architecture — from raw sensor data to operator action. Every pipeline stage maps to industry standards for decentralized, edge-native drone swarms (e.g., Shield AI, Anduril). SENTINEL is designed as a **GCS-optional** Layer 2 C2 platform, meaning the swarm can fight and coordinate without a ground station.

Last Updated: 2026-06-25

---

## 1. The Full Pipeline

SENTINEL follows the **Perception → Cognition → Action** pipeline, running at the tactical edge. 
Crucially, **REASON and PLAN stages are distributed across all nodes**.

```
┌─────────────────────────────────────────────────────────────────────────┐
│                                                                         │
│   COLLECT ──→ INTERPRET ──→ DETECT ──→ REASON ──→ PLAN ──→ ACT         │
│                                                                         │
│   Sensors      Physics       5-Domain    Local COP    CBBA       Execute │
│   → raw data   Modeling      Anomalies   + Mesh       Auction    Tiers   │
│                + Fusion      + Threats   Sync         (Edge)     to FC   │
│                                                                         │
│   ◄─────────────────────── EVERY NODE (EDGE) ─────────────────────────► │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

### Stage 1: COLLECT — Sensor Data Acquisition

**What happens:** Raw data streams from every available sensor on the platform. Sensor-agnostic ingestion is table stakes.

| Data Source | Protocol / Driver | What It Gives Us |
|---|---|---|
| **Flight Controller** | MAVLink (serial) | `RAW_IMU`, `VIBRATION`, `SCALED_PRESSURE`, `ESC_STATUS`, `SERVO_OUTPUT_RAW`, `GPS_RAW_INT`, `ATTITUDE`, `BATTERY_STATUS` |
| **Cameras** (EO/IR) | ROS2 bridge | Object detection, visual tracking, visual odometry |
| **LiDAR** | ROS2 bridge | 3D point clouds for obstacle avoidance |
| **RF Scanner** | ROS2 / UDP | Detect hostile drone control signals |

**Key design rule:** The ingestion layer is a set of pluggable adapters. MAVLink is used for FC telemetry, but **ROS2 is the core architecture** for multi-modal sensor fusion.

---

### Stage 2: INTERPRET — Physics-Based Modeling & Fusion

**What happens:** Raw sensor data is transformed into structured features and validated against physics models.

| Processing Task | Method | Why |
|---|---|---|
| **Vibration Analysis** | FFT on `RAW_IMU` & `VIBRATION` | Extracts frequency-domain signatures for motor/propeller health. |
| **Propulsion Modeling** | Motor Current Signature Analysis (MCSA) on `ESC_STATUS` | Detects electrical degradation before mechanical failure. |
| **Sensor Cross-Validation** | EKF innovation gating + physical constraints | Compares GPS movement vs IMU integration to detect GPS spoofing. |
| **State Estimation** | EKF fusing IMU, Baro, GPS, VIO | Provides resilient navigation when GPS is degraded. |
| **Flight Dynamics** | Commanded vs Achieved attitude mapping | Identifies structural damage or control surface failures. |

---

### Stage 3: DETECT — 5-Domain Intelligence

**What happens:** Moving beyond simple thresholds, SENTINEL evaluates health and threats across 5 distinct domains ON-EDGE.

| Domain | What It Detects | Detection Method |
|---|---|---|
| **Propulsion Health** | Bearing wear, prop damage, motor degradation | FFT vibration peaks + MCSA + deviation from thrust physics model |
| **Power System** | Cell degradation, internal resistance rise | Electrochemical modeling + Peukert's law + impedance estimation |
| **Navigation Integrity** | GPS spoofing, IMU drift, magnetometer jamming | EKF innovation monitoring + baro/GPS altitude divergence |
| **Flight Dynamics** | Control instability, structural damage, icing | Commanded vs achieved analysis + aerodynamic system identification |
| **Electronic Warfare** | RF jamming, spoofing, link hijacking | RF spectrum baselining + ML anomaly detection + fleet link-loss correlation |

---

### Stage 4: REASON — Distributed Situational Awareness

**What happens:** Anomalies and threats are correlated. **This happens on EVERY drone, not just the GCS.**

*   **Local Common Operating Picture (COP):** Every drone maintains its own COP using **Conflict-free Replicated Data Types (CRDTs)**.
*   **Mesh Sync:** Drones gossip their CRDT state to neighbors at 1Hz. When in range, they merge states, ensuring eventual consistency.
*   **Cross-Drone Correlation:** A drone can independently conclude an area is jammed if it sees its neighbors' CRDT states indicating simultaneous link loss.
*   **GCS Role:** The GCS is **optional**. If present, it passively subscribes to the mesh to provide an operator dashboard, NLP reasoning, and historical logging. It does NOT command the swarm's core reasoning.

---

### Stage 5: PLAN — Decentralized Task Allocation

**What happens:** The swarm assigns tasks (intercept, patrol, evade) without a central coordinator.

*   **CBBA (Consensus-Based Bundle Algorithm):** The primary task allocator. 
    *   When a task is generated, drones greedily build bundles and bid on them.
    *   Bids are calculated based on a risk-aware and energy-aware scoring function (e.g., closer drones with healthier batteries bid higher).
    *   Drones gossip bids. Conflicts are resolved locally. Converges in 3-5 rounds (~500ms).
*   **Hungarian Algorithm:** Fallback/optimization. Used ONLY if the GCS is active and wants to compute a globally optimal pre-mission plan.

---

### Stage 6: ACT — Autonomous Execution Tiers

**What happens:** Plans are converted into physical actions.

| Tier | Autonomy Level | Actions |
|---|---|---|
| **Tier 1 (Edge)** | Fully Autonomous | ArduPilot failsafes, collision avoidance, immediate EW evasion. |
| **Tier 2 (Swarm)** | Collaborative | CBBA-assigned intercepts, dynamic formation changes, re-routing. |
| **Tier 3 (Operator)** | Human-in-the-loop | Kinetic engagement, mission abort, manual override. |

---

## 2. Threat Alert Propagation Protocol (TAPP)

**How drones communicate threats without a GCS.**

**Phase 1: DETECT & BROADCAST**
*   Drone detects threat and publishes `THREAT_ALERT` to NATS `sentinel.threats.alert`.
*   Uses **epidemic broadcast** (gossip fan-out with TTL) to rapidly propagate across the mesh.

**Phase 2: CORROBORATE**
*   Receiving drones check if they can independently verify (e.g., via their own RF scanners or cameras).
*   Publish `THREAT_CONFIRM` or `THREAT_DENY` on `sentinel.threats.confirm`.
*   Confidence score = $f(\text{corroborating\_drones}, \text{sensor\_diversity})$.

**Phase 3: ASSESS & RESPOND (CBBA)**
*   Drones independently assess if they should respond (based on distance, fuel, capabilities).
*   They publish bids to `sentinel.threats.bid`.
*   The mesh reaches consensus. The winning drone claims the intercept/observe task.

**Phase 4: EXECUTE & REPORT**
*   Assigned drone executes. Logs action to local SQLite WAL.
*   Publishes outcome to `sentinel.threats.report` to update the fleet CRDT state.

### TAPP Protobuf Schema

```protobuf
message ThreatAlert {
  string threat_id = 1;           
  ThreatType type = 2;            // HOSTILE_UAS, EW_JAMMING, etc.
  Position position = 3;          
  Velocity velocity = 4;          
  float confidence = 5;           
  string detecting_drone_id = 6;  
  int64 timestamp_ms = 7;         
  int32 ttl = 8;                  // hop count
  SensorSource source = 9;        
}

message ThreatBid {
  string threat_id = 1;
  string drone_id = 2;
  float bid_score = 3;            // Based on distance, battery, capability
  ResponseAction proposed_action = 4; 
  int32 cbba_round = 5;
}
```

### NATS Mesh Topic Structure

```text
sentinel.fleet.state.{drone_id}      # CRDT sync (1Hz)
sentinel.threats.alert               # Epidemic broadcast
sentinel.threats.confirm             # Sensor cross-validation
sentinel.threats.bid                 # CBBA auction
sentinel.threats.report              # Post-action reporting
sentinel.mesh.topology               # Mesh routing updates
```

---

## 3. Language Selection & Services

| Service | Language | Role |
|---|---|---|
| **Sentinel Edge** | **Go** + **Python** | Runs on EVERY drone. Go handles NATS mesh, CBBA, MAVLink, and TAPP. Python sidecar handles FFT, MCSA, EKF innovation ML, and YOLO CV. |
| **Sentinel C2** | **Python** | Runs on GCS (Optional). Passive observer. Consumes CRDTs for operator dashboard. Provides NLP Agent interface. |
| **Sentinel Fusion** | **Python** | Runs on GCS/Ground Node. Ingests external ground radar/RF feeds via REST API and bridges them into the NATS mesh. |
| **Dashboard** | **TypeScript** | Next.js frontend for operators. |

---

## 4. Codebase Structure

The canonical directory layout maps 1:1 to the 4 services above. Every file has a single owner service.

```
sentinel/
│
├── architecture/                          # System design docs (this file lives here)
│   ├── service_architecture.md
│   └── competitive_benchmarking.md
│
├── src/
│   ├── protos/                            # ── SHARED: Protobuf IDL (source of truth) ──
│   │   ├── threat.proto                   #   ThreatAlert, ThreatBid, ThreatConfirm, ThreatReport
│   │   └── fleet.proto                    #   FleetState, NodeState
│   │
│   │
│   │   # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
│   │   # SERVICE 1: SENTINEL EDGE  (Go + Python · Runs on every drone)
│   │   # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
│   │
│   ├── edge-agent/                        # ── Go Edge Agent ──
│   │   ├── go.mod
│   │   ├── cmd/
│   │   │   └── sentinel-agent/
│   │   │       └── main.go                #   Entry point. Boots NATS, starts TAPP + CBBA loops.
│   │   └── internal/
│   │       ├── mesh/                      #   NATS pub/sub wrapper + epidemic broadcast
│   │       │   ├── nats.go                #     Connect, Publish, Subscribe
│   │       │   └── pb/                    #     Auto-generated protobuf Go bindings
│   │       │       ├── threat.pb.go
│   │       │       └── fleet.pb.go
│   │       ├── crdt/                      #   [PLANNED] FleetState CRDT structs + merge logic
│   │       │   └── fleet_state.go
│   │       ├── cbba/                      #   [PLANNED] Consensus-Based Bundle Algorithm
│   │       │   ├── engine.go              #     Bid generation, gossip, conflict resolution
│   │       │   └── scoring.go             #     Risk-aware + energy-aware scoring functions
│   │       ├── tapp/                      #   [PLANNED] TAPP state machine (4 phases)
│   │       │   └── state_machine.go
│   │       └── command/                   #   [PLANNED] MAVLink command sender to FC
│   │           └── command_sender.go
│   │
│   ├── intelligence/                      # ── Python Sidecar (5-Domain Intelligence) ──
│   │   ├── __init__.py
│   │   ├── sidecar.py                     #   [PLANNED] Main daemon. Subscribes to NATS telemetry topics.
│   │   ├── domains/
│   │   │   ├── __init__.py
│   │   │   ├── propulsion.py              #   [PLANNED] FFT vibration analysis + MCSA
│   │   │   ├── power.py                   #   [PLANNED] Peukert's law + impedance estimation
│   │   │   ├── navigation.py              #   [PLANNED] GPS spoofing / EKF innovation gating
│   │   │   ├── flight_dynamics.py         #   [PLANNED] Commanded vs achieved mapping
│   │   │   └── electronic_warfare.py      #   [PLANNED] RF baselining + ML anomaly detection
│   │   └── ml_models/                     #   Trained model artifacts (.pkl, .onnx)
│   │       └── isolation_forest.pkl
│   │
│   │
│   │   # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
│   │   # SERVICE 2: SENTINEL C2  (Python · Runs on GCS, optional)
│   │   # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
│   │
│   ├── c2/                                # ── Ground Control Station Service ──
│   │   ├── __init__.py
│   │   ├── server.py                      #   [PLANNED] FastAPI app. REST + WebSocket API for dashboard.
│   │   ├── crdt_consumer.py               #   [PLANNED] Subscribes to sentinel.fleet.state.> via NATS.
│   │   ├── nlp_agent.py                   #   [PLANNED] ReAct agent consuming live CRDT + threat feeds.
│   │   ├── historical_logger.py           #   [PLANNED] Persists CRDT snapshots + threats to time-series DB.
│   │   └── knowledge/                     #   RAG knowledge base for NLP reasoning
│   │       ├── anomalies.md
│   │       ├── correlations.md
│   │       └── schema.md
│   │
│   │
│   │   # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
│   │   # SERVICE 3: SENTINEL FUSION  (Python · Runs on GCS/Ground node)
│   │   # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
│   │
│   ├── fusion/                            # ── External Sensor Bridge ──
│   │   ├── __init__.py
│   │   ├── server.py                      #   [PLANNED] FastAPI. Accepts ground radar/RF feeds via REST.
│   │   ├── nats_bridge.py                 #   [PLANNED] Converts external data → ThreatAlert protobufs → NATS.
│   │   └── auth.py                        #   [PLANNED] API key / mTLS validation.
│   │
│   │
│   │   # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
│   │   # SENSOR INGESTION LAYER  (ROS2 · Runs on every drone)
│   │   # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
│   │
│   ├── ros2_ws/                           # ── ROS2 Workspace ──
│   │   └── src/
│   │       └── sentinel_bridge/
│   │           ├── package.xml
│   │           ├── setup.py
│   │           ├── launch/
│   │           │   └── mavros_bridge.launch.py
│   │           └── sentinel_bridge/
│   │               ├── __init__.py
│   │               └── bridge_node.py     #   ROS2 node: subscribes to MAVROS/Camera → publishes to NATS
│   │
│   │
│   │   # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
│   │   # LEGACY FILES  (Pre-refactor monolith · Migration targets noted)
│   │   # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
│   │
│   ├── telemetry.py                       #   LEGACY → Migrates to: c2/telemetry.py
│   ├── telemetry_store.py                 #   LEGACY → Migrates to: c2/historical_logger.py (time-series DB)
│   ├── anomaly.py                         #   LEGACY → Migrates to: intelligence/domains/*.py (5-domain split)
│   ├── ml_detector.py                     #   LEGACY → Migrates to: intelligence/ml_models/
│   ├── live_feed.py                       #   LEGACY → Replaced by: intelligence/sidecar.py + NATS streaming
│   ├── live_state.py                      #   LEGACY → Replaced by: CRDT FleetState (edge-agent/internal/crdt/)
│   ├── connect.py                         #   LEGACY → Migrates to: c2/connect.py
│   ├── agent.py                           #   LEGACY → Migrates to: c2/nlp_agent.py
│   ├── sentinel_agent.py                  #   LEGACY → Migrates to: c2/nlp_agent.py
│   ├── reasoning.py                       #   LEGACY → Migrates to: c2/nlp_agent.py
│   ├── query_engine.py                    #   LEGACY → Migrates to: c2/nlp_agent.py
│   ├── tools.py                           #   LEGACY → Migrates to: c2/nlp_agent.py (tool definitions)
│   ├── nlp.py                             #   LEGACY → Migrates to: c2/nlp_agent.py
│   ├── rag.py                             #   LEGACY → Migrates to: c2/knowledge/
│   ├── api.py                             #   LEGACY → Migrates to: c2/server.py (REST API)
│   ├── monitor.py                         #   LEGACY → Replaced by: intelligence/sidecar.py
│   ├── report.py                          #   LEGACY → Migrates to: c2/server.py
│   └── knowledge/                         #   LEGACY → Migrates to: c2/knowledge/
│       ├── anomalies.md
│       ├── correlations.md
│       └── schema.md
│
│
│   # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
│   # SERVICE 4: DASHBOARD  (TypeScript/Next.js · Operator workstation)
│   # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
│
├── drone-mission-dashboard/               # ── Next.js Operator Dashboard ──
│   ├── app/                               #   Next.js App Router pages
│   ├── components/                        #   React components (UI kit + custom)
│   ├── lib/
│   │   ├── api.ts                         #   API client (consumes c2/server.py endpoints)
│   │   ├── types.ts                       #   TypeScript interfaces matching protobuf schemas
│   │   └── utils.ts
│   ├── package.json
│   └── tsconfig.json
│
│
│   # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
│   # SUPPORT FILES
│   # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
│
├── scripts/
│   ├── setup_deps.sh                      #   Downloads Go, protoc, NATS into .tools/
│   ├── start_nats.sh                      #   Starts local NATS server for dev/test
│   └── train_model.py                     #   ML model training pipeline
│
├── tests/
│   ├── pb/                                #   Auto-generated protobuf Python bindings
│   │   ├── threat_pb2.py
│   │   └── fleet_pb2.py
│   ├── test_nats_latency.py               #   Phase A integration test (Go ↔ Python)
│   ├── test_anomaly.py                    #   Unit tests for anomaly detectors
│   ├── test_agent.py                      #   Unit tests for NLP agent
│   ├── test_query_engine.py               #   Unit tests for query engine
│   ├── test_ml_detector.py                #   Unit tests for ML detector
│   ├── test_telemetry_store.py            #   Unit tests for telemetry store
│   └── verify_ingest.py                   #   Ingestion verification script
│
├── data/                                  #   SQLite databases, log files, mission data
├── techstack/                             #   Technology research notes
│   ├── databases.md
│   ├── mesh_and_p2p_networks.md
│   └── sensor_data_collection.md
│
├── .tools/                                #   Local dev toolchain (Go, protoc, NATS) — .gitignored
├── PLAN.md                                #   Execution roadmap (7 phases, maps to this doc)
├── README.md
├── MAVLINK.md                             #   MAVLink protocol reference
└── SITL.md                                #   ArduPilot SITL setup guide
```

### Service ↔ Pipeline Stage Mapping

| Pipeline Stage | Owner Service | Key Directory |
|---|---|---|
| **COLLECT** | Sentinel Edge (ROS2 layer) | `src/ros2_ws/`, `src/edge-agent/internal/ingestion/` |
| **INTERPRET** | Sentinel Edge (Python sidecar) | `src/intelligence/domains/` |
| **DETECT** | Sentinel Edge (Python sidecar) | `src/intelligence/domains/`, `src/intelligence/ml_models/` |
| **REASON** | Sentinel Edge (Go) | `src/edge-agent/internal/crdt/` |
| **PLAN** | Sentinel Edge (Go) | `src/edge-agent/internal/cbba/` |
| **ACT** | Sentinel Edge (Go) | `src/edge-agent/internal/tapp/`, `src/edge-agent/internal/command/` |
| **GCS Observe** | Sentinel C2 | `src/c2/` |
| **External Feeds** | Sentinel Fusion | `src/fusion/` |
| **Operator UI** | Dashboard | `drone-mission-dashboard/` |

### Legacy Migration Path

All files directly under `src/` (outside of service directories) are **legacy monolith code** from the single-drone prototype. They will be incrementally migrated into their target service directories as each phase executes. The legacy files remain functional during migration to avoid breaking the existing demo pipeline.

---

## 5. Degradation Model (Resilience)

| Level | Connectivity | Capability |
|---|---|---|
| **NORMAL** | Full mesh + GCS | Full fleet coordination, operator NLP queries, external ground radar feeds active. |
| **DEGRADED** | Mesh only (No GCS) | **Swarm continues fighting.** TAPP protocol active, CBBA dynamic task allocation, edge anomaly detection, local CRDT sync. |
| **AUTONOMOUS** | Zero connectivity | Single-drone survival. 5-domain anomaly detection active. Pre-planned route execution. Obstacle avoidance. |
| **SURVIVAL** | Flight controller only | ArduPilot hardware failsafes (RTB/Land). |
