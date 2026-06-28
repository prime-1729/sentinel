# SENTINEL Execution Roadmap: Edge-Native Codebase Revamp

Last updated: 2026-06-26

> **Source of Truth:** All phases below map directly to the 6-stage pipeline
> (COLLECT → INTERPRET → DETECT → REASON → PLAN → ACT) and the 4 services
> (Sentinel Edge, C2, Fusion, Dashboard) defined in
> [`architecture/service_architecture.md`](architecture/service_architecture.md).

---

## 0. Current State & Goal

We have successfully built a Python-based, single-drone prototype that proves we can parse telemetry and run NLP-powered intelligent reasoning. 

**Our Goal:** Completely revamp this monolithic Python codebase into a decentralized, multi-language Edge-Native swarm intelligence platform consisting of:

| Service | Language | Runs On |
|---|---|---|
| **Sentinel Edge** | Go + Python sidecar | Every drone |
| **Sentinel C2** | Python | GCS (optional) |
| **Sentinel Fusion** | Python | GCS / Ground node |
| **Dashboard** | TypeScript (Next.js) | Operator workstation |

The following 7-phase execution plan details the exact engineering steps to achieve this.

---

## Phase A: Edge Agent & Mesh Infrastructure (Go)

> **Maps to:** Mesh backbone for all stages. NATS topic structure from `service_architecture.md §2`.

**Goal:** Establish the foundational NATS mesh network and the Go-based Edge Agent that will handle high-speed D2D (Drone-to-Drone) communication.

- [x] **A1. Initialize Go Project:** Setup `src/edge-agent` with `go mod init sentinel-edge-agent`.
- [x] **A2. Define Protobuf Schemas:** Create `src/protos/` containing:
  - `ThreatAlert`, `ThreatBid`, `ThreatConfirm`, `ThreatReport` (for TAPP protocol — all 4 phases)
  - `FleetState` (for CRDT state syncing)
- [x] **A3. Setup NATS Mesh:** Embed or connect to a NATS server configured for leaf-node/mesh routing.
- [x] **A4. Edge Agent Pub/Sub Wrapper:** Build the core Go client that handles epidemic broadcasting (publish) and subscription to the full NATS topic tree:
  - `sentinel.fleet.state.{drone_id}` — CRDT sync (1Hz)
  - `sentinel.threats.alert` — Epidemic broadcast
  - `sentinel.threats.confirm` — Sensor cross-validation
  - `sentinel.threats.bid` — CBBA auction
  - `sentinel.threats.report` — Post-action reporting
  - `sentinel.mesh.topology` — Mesh routing updates
- [x] **A5. Integration Test:** Build a mock Python node to verify sub-millisecond NATS pub/sub latency between Python and Go.

### A-Followup: Enrich Protobuf Schemas

The current `threat.proto` is simplified. It must be upgraded to match the architecture spec:

- [ ] **A6. Enrich `threat.proto`:** Add `ThreatType` enum (`HOSTILE_UAS`, `EW_JAMMING`, `GPS_SPOOFING`, `MOTOR_FAILURE`, etc.), `Position` and `Velocity` sub-messages, `ttl` (hop count for epidemic broadcast), `SensorSource` enum, and `cbba_round` to `ThreatBid`.
- [ ] **A7. Add `ThreatReport` message:** For TAPP Phase 4 (Execute & Report) — includes `action_taken`, `outcome`, `post_action_state`.
- [ ] **A8. Regenerate bindings** for Go and Python after schema enrichment.

---

## Phase B: Sensor Ingestion (ROS2 + PyMAVLink)

> **Maps to:** Stage 1 (COLLECT) — Sensor Data Acquisition.

**Goal:** Decouple sensor ingestion from the intelligence logic. Expose all telemetry, camera, and LiDAR data to the NATS mesh via ROS2.

- [x] **B1. ROS2 Workspace Setup:** Initialize `src/ros2_ws`.
- [x] **B2. MAVROS Configuration:** Set up MAVROS to bridge ArduPilot/PX4 flight controller data to native ROS2 topics.
- [x] **B3. Telemetry Refactor:** Refactor the existing Python `telemetry.py` from a SQLite-centric writer to a high-frequency NATS publisher. 
- [x] **B4. ROS2-to-NATS Bridge:** Write the bridging service that listens to ROS2 sensor topics (e.g., VIO, LiDAR point clouds) and republishes them to the NATS mesh so the Go Edge Agent and Python sidecar can consume them.

### B-Followup: Additional Sensor Adapters

Per the architecture, the COLLECT stage must be a set of **pluggable adapters**:

- [ ] **B5. RF Scanner Adapter:** Implement a UDP/ROS2 listener for RF scanner data (hostile drone control signals). Publish to `sentinel.telemetry.{drone_id}.rf`.
- [ ] **B6. Camera Adapter Stub:** Create a ROS2 subscriber for EO/IR camera streams that publishes detection metadata (not raw frames) to `sentinel.telemetry.{drone_id}.camera`.

---

## Phase C: 5-Domain Intelligence (Python Sidecar)

> **Maps to:** Stage 2 (INTERPRET) + Stage 3 (DETECT) — Physics Modeling & 5-Domain Anomaly Detection.

**Goal:** Transform the existing `anomaly.py` logic into a continuous ML and signal processing daemon that analyzes streams in real-time across **all 5 domains**.

- [ ] **C1. Python Sidecar Daemon:** Stand up the Python process (`src/intelligence_sidecar.py`) that subscribes to `sentinel.telemetry.>` NATS topics with sliding-window buffering.

### Domain 1: Propulsion Health

- [ ] **C2. Vibration FFT:** Implement Fast Fourier Transform analysis on `RAW_IMU` / `VIBRATION` topics to extract frequency-domain signatures for bearing wear and prop damage.
- [ ] **C3. Motor Current Signature Analysis (MCSA):** Upgrade `detect_motor_imbalance()` to use MCSA on `ESC_STATUS` for electrical degradation detection before mechanical failure.

### Domain 2: Power System

- [ ] **C4. Electrochemical Degradation Model:** Implement Peukert's law tracking + internal impedance estimation on `BATTERY_STATUS` telemetry to detect cell degradation and internal resistance rise.

### Domain 3: Navigation Integrity

- [ ] **C5. GPS Spoofing Detection:** Implement EKF innovation gating and IMU-cross-validation on position streams. Detect baro/GPS altitude divergence.
- [ ] **C6. State Estimation Monitoring:** Monitor EKF confidence (via `EKF_STATUS_REPORT` MAVLink message) for IMU drift and magnetometer jamming indicators.

### Domain 4: Flight Dynamics

- [ ] **C7. Commanded vs. Achieved Analysis:** Implement commanded vs. achieved attitude mapping using `SERVO_OUTPUT_RAW` vs `ATTITUDE`. Detect control instability, structural damage, and icing.

### Domain 5: Electronic Warfare ⚡

- [ ] **C8. RF Spectrum Baselining:** Implement baseline noise-floor estimation from the RF scanner feed. Flag deviations as potential jamming/spoofing.
- [ ] **C9. ML Anomaly Detection on RF:** Train/deploy an anomaly detection model (Isolation Forest or Autoencoder) on RF spectral features.
- [ ] **C10. Fleet Link-Loss Correlation:** Cross-reference local RSSI degradation with neighboring drones' CRDT states to determine if link loss is localized (hardware fault) or area-wide (active jamming).

### NATS Publishing (TAPP Integration)

- [ ] **C11. Publish `ThreatAlert` protobufs:** When any domain detector fires, the sidecar publishes a `ThreatAlert` protobuf (NOT a separate `AnomalyEvent` type) to `sentinel.threats.alert` on the NATS mesh. This directly triggers the TAPP protocol in the Go Edge Agent.

---

## Phase D: CRDT State Sync & CBBA (Go)

> **Maps to:** Stage 4 (REASON) — Distributed Situational Awareness + Stage 5 (PLAN) — Decentralized Task Allocation.

**Goal:** Give the swarm a distributed brain. Implement decentralized state sharing and task allocation in Go.

### REASON — Local Common Operating Picture

- [ ] **D1. FleetState CRDT:** Implement the Conflict-free Replicated Data Type structs in Go for maintaining the Common Operating Picture. Each drone maintains its own COP.
- [ ] **D2. Gossip Loop:** Build a 1Hz loop in the Go Edge Agent to broadcast and merge CRDTs with neighboring drones via `sentinel.fleet.state.{drone_id}`.
- [ ] **D3. Cross-Drone Correlation:** Implement logic that lets a drone independently conclude an area is jammed when it observes simultaneous link loss across its neighbors' CRDT states.

### PLAN — CBBA Task Allocation

- [ ] **D4. CBBA Engine:** Implement the Consensus-Based Bundle Algorithm logic in Go.
- [ ] **D5. Bidding Logic:** Define risk-aware and energy-aware scoring functions based on the current `FleetState` (distance, battery, capability).
- [ ] **D6. Bid Gossip & Conflict Resolution:** Implement bid gossiping via `sentinel.threats.bid` and local conflict resolution. Target convergence: 3-5 rounds (~500ms).
- [ ] **D7. Simulation Test:** Write unit tests simulating 5 Go agents receiving a task, gossiping bids, and successfully resolving the conflict without a central server.

---

## Phase E: TAPP Execution & Command Routing

> **Maps to:** Stage 6 (ACT) — Autonomous Execution Tiers + TAPP Protocol (§2).

**Goal:** Wire the threat detection, task allocation, and flight controller command execution into an autonomous closed loop implementing all 4 TAPP phases.

### TAPP State Machine (All 4 Phases)

- [ ] **E1. Phase 1 — Detect & Broadcast:** Python sidecar publishes `ThreatAlert` to `sentinel.threats.alert`. Go Edge Agent uses epidemic broadcast (gossip fan-out with TTL) to propagate across the mesh.
- [ ] **E2. Phase 2 — Corroborate:** Receiving drones independently verify the threat via their own sensors. Publish `ThreatConfirm` or deny to `sentinel.threats.confirm`. Confidence score = f(corroborating_drones, sensor_diversity).
- [ ] **E3. Phase 3 — Assess & Respond (CBBA):** Drones independently assess and bid. CBBA auction on `sentinel.threats.bid`. Winning drone claims the intercept/observe task.
- [ ] **E4. Phase 4 — Execute & Report:** Assigned drone executes. Logs action to local SQLite WAL. Publishes `ThreatReport` to `sentinel.threats.report` to update the fleet CRDT state.

### Command Routing

- [ ] **E5. Command Sender:** Create `command_sender.go` to securely send MAVLink commands (e.g., `SET_MODE`, `MISSION_ITEM_INT`) to the FC over serial/UDP once CBBA assigns an intercept/patrol task.

### Autonomous Execution Tiers

- [ ] **E6. Tier 1 (Edge — Fully Autonomous):** ArduPilot failsafes, collision avoidance, immediate EW evasion. No human required.
- [ ] **E7. Tier 2 (Swarm — Collaborative):** CBBA-assigned intercepts, dynamic formation changes, re-routing.
- [ ] **E8. Tier 3 (Operator — Human-in-the-Loop):** Implement the failsafe gateway where kinetic engagement tasks require explicit cryptographic confirmation from a GCS node (if available).

### Mesh Topology

- [ ] **E9. Mesh Topology Service:** Implement `sentinel.mesh.topology` publisher/subscriber in Go to maintain mesh routing state and detect network partitions.

### End-to-End Test

- [ ] **E10. Full Pipeline Test:**
  1. Python sidecar detects GPS spoofing (Domain 3).
  2. Publishes `ThreatAlert` to NATS.
  3. Go Edge Agent triggers TAPP Phase 1 (epidemic broadcast).
  4. Neighbor drones corroborate (Phase 2).
  5. Mesh conducts CBBA auction (Phase 3).
  6. Winning Edge Agent sends MAVLink maneuver command to FC (Phase 4).
  7. `ThreatReport` published to update fleet COP.

---

## Phase F: Sentinel C2 — GCS Passive Observer (Python)

> **Maps to:** Sentinel C2 service (§3) + Stage 4 REASON (GCS Role).

**Goal:** Build the optional ground control station service that passively observes the swarm without commanding it.

- [ ] **F1. CRDT Consumer:** Subscribe to `sentinel.fleet.state.>` on the NATS mesh and build a ground-side Common Operating Picture.
- [ ] **F2. NLP Agent Interface:** Migrate the existing `agent.py` / `reasoning.py` / `query_engine.py` to consume the live CRDT state and NATS threat feeds instead of querying SQLite.
- [ ] **F3. Historical Logging:** Persist all received CRDT snapshots, `ThreatAlert`s, and `ThreatReport`s into a time-series database for post-mission analysis.
- [ ] **F4. Dashboard Integration:** Expose a REST/WebSocket API that the Next.js dashboard can consume for real-time fleet visualization.

---

## Phase G: Sentinel Fusion — External Sensor Bridge (Python)

> **Maps to:** Sentinel Fusion service (§3).

**Goal:** Bridge external ground-based sensor feeds into the NATS mesh so the swarm can incorporate off-platform intelligence.

- [ ] **G1. REST API Ingestion:** Build a FastAPI service that accepts ground radar and RF scanner feeds via REST endpoints.
- [ ] **G2. NATS Bridge:** Convert incoming external sensor data into `ThreatAlert` protobufs and publish to `sentinel.threats.alert` so the swarm's TAPP protocol treats them identically to on-platform detections.
- [ ] **G3. Authentication:** Implement API key or mTLS authentication to prevent adversarial injection of false threat data.

---

## Appendix: Degradation Model Compliance

All phases above must be validated against the 4 degradation levels:

| Level | Connectivity | What Must Still Work |
|---|---|---|
| **NORMAL** | Full mesh + GCS | All 7 phases active. Full fleet coordination, NLP queries, external ground feeds. |
| **DEGRADED** | Mesh only (No GCS) | Phases A–E active. TAPP protocol, CBBA, edge anomaly detection, CRDT sync. Phases F–G offline. |
| **AUTONOMOUS** | Zero connectivity | Phase C active (single-drone 5-domain detection). Pre-planned route execution. Obstacle avoidance. |
| **SURVIVAL** | Flight controller only | ArduPilot hardware failsafes (RTB/Land). All software layers offline. |
