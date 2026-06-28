# SENTINEL Competitive Benchmarking

> **Purpose:** A stage-by-stage comparison of SENTINEL against industry leaders (Shield AI, Anduril, DroneShield, Skydio, Fortem Technologies, DARPA OFFSET).

Last Updated: 2026-06-25

---

## Stage 1: COLLECT — Sensor Data Acquisition

| Capability | Shield AI (Hivemind) | Anduril (Lattice) | DroneShield (DroneSentry) | Skydio | Fortem Technologies | SENTINEL |
|---|---|---|---|---|---|---|
| **Sensor types** | 6x stereo cameras, LiDAR, IMU, EO/IR, radar | ANY sensor — drones, radar, IR, cameras, satellites. Hardware-agnostic. | RF + radar + EO/IR + acoustic (multi-modal) | 6x fisheye cameras + IMU (vision-only) | TrueView radar + EO/IR + RF | MAVLink telemetry, ROS2 bridge (EO/IR, LiDAR), External radar/RF (REST API) |
| **Ingestion model** | Edge-first: all sensing processed onboard, sensor-prioritized | Sensor-agnostic pluggable drivers. Edge processing before sharing. | Modular "sensor-agnostic" software layer. Vendor-independent. | Vertically integrated: hardware purpose-built for the software stack | Networked radar arrays with centralized fusion | Pluggable adapters via ROS2 on-edge and NATS across the mesh. |
| **Edge processing** | ✅ Full perception stack runs on aircraft | ✅ Edge AI classifies objects locally before sharing conclusions | ❌ Centralized at DroneSentry-C2 | ✅ NVIDIA Jetson SoC: all vision runs on-drone | Partially — radar processing on-sensor, fusion centralized | ✅ Sentinel Edge (Go+Python) processes locally. |

---

## Stage 2: INTERPRET — Physics-Based Modeling & Fusion

| Capability | Shield AI | Anduril | DroneShield | Skydio | SENTINEL |
|---|---|---|---|---|---|
| **Core fusion** | VIO (camera + IMU fusion) for navigation. ViDAR for detection. | Edge AI: detect, classify, track at edge. Share conclusions. | SensorFusionAI (SFAI): correlates RF + radar + EO/IR into unified tracks | VIO + 360° depth perception. 1M+ data points/sec on-drone. | MCSA, FFT vibration analysis, EKF state estimation, Flight Dynamics mapping. |
| **Share conclusions vs raw data** | ✅ Shares detections + tracks, not video | ✅ Explicit design principle | ❌ Streams all data to C2 | ✅ On-drone processing | ✅ Publishes state vectors + anomaly events to NATS mesh, not raw telemetry. |
| **Object detection** | ViDAR + custom CV models | YOLO-class models on edge GPU | ML classifier for RF. Rule-based for radar RCS. | Custom deep neural networks (multiple simultaneously) | YOLO on edge GPU. Deterministic/Physics-based rules for telemetry anomalies. |

---

## Stage 3: DETECT — 5-Domain Intelligence

| Capability | Shield AI | Anduril | DroneShield | Fortem | SENTINEL |
|---|---|---|---|---|---|
| **Own-fleet health monitoring** | On-aircraft health management system | Lattice monitors all platform health telemetry | N/A (C-UAS only) | N/A (C-UAS only) | ✅ 5-Domain: Propulsion (FFT), Power, Nav Integrity, Dynamics, EW (RF baseline). |
| **Threat detection** | Tactical threat assessment in cognition layer | Multi-sensor fusion: radar + EO/IR + signals intelligence | Multi-modal: RF + radar + acoustic + EO/IR. SensorFusionAI. | TrueView radar specialized for small UAS. AI-powered classification. | External sensor API → track correlation → classification → prioritization |
| **EW attack detection** | ✅ Core capability — DDIL environments | ✅ Explicit design for contested environments | ✅ RF detection of hostile control signals | ❌ Not primary focus | ✅ GPSSpoofing (EKF Innovation), RF anomaly baselining, link-loss correlation. |

---

## Stage 4: REASON — Distributed Situational Awareness

| Capability | Shield AI | Anduril | DroneShield | DARPA OFFSET | SENTINEL |
|---|---|---|---|---|---|
| **Cross-drone correlation** | Hivemind: shared tactical picture across wingmen | Lattice COP: correlates data from ALL nodes in real-time | DroneSentry-C2 Enterprise: multi-site correlation | Swarm-level shared perception via sub-swarm leaders | Local CRDT sync across mesh. Edge-native cross-drone correlation. |
| **Where it runs** | Distributed across aircraft (each has full COP) | Distributed — every Lattice node maintains COP independently | Centralized at C2 | Hierarchical — sub-swarm leaders aggregate, share up | ✅ **Distributed (Every node via CRDTs)** |
| **Operates without GCS** | ✅ Each aircraft has autonomous reasoning | ✅ Each Lattice node can reason independently | ❌ Requires C2 | ✅ Sub-swarms operate autonomously | ✅ Yes. GCS is optional for reasoning. |

---

## Stage 5: PLAN — Decentralized Task Allocation

| Capability | Shield AI | Anduril | DARPA OFFSET | AeroVironment | SENTINEL |
|---|---|---|---|---|---|
| **Mission decomposition** | Autonomous tactical planning on-aircraft | Intent-to-Task: operators say "secure this perimeter" → system auto-decomposes | Tactics → Plays → Primitives hierarchy | AV_Halo INSTINCT: distributed collaborative mission execution | Boustrophedon, Voronoi, geometric partitioning |
| **Task allocation** | Distributed across wingmen | Distributed across Lattice nodes | Decentralized via swarm primitives | Sensor-to-Shooter automated handoffs | **CBBA (Decentralized, Primary)** + Hungarian (Centralized, Fallback) |
| **Decentralized allocation** | ✅ Each aircraft contributes to plan | ✅ Lattice distributes planning | ✅ Core design principle of OFFSET | ✅ AV_Halo distributes across platforms | ✅ Yes. CBBA gossip convergence in 3-5 rounds. |

---

## Stage 6: ACT — Autonomous Execution

| Capability | Shield AI | Anduril | Fortem | AeroVironment | SENTINEL |
|---|---|---|---|---|---|
| **Failsafe** | On-aircraft autonomous | Platform-native | Autonomous interceptor launch + capture | Autonomous Switchblade engagement | ✅ Tier 1 Edge Agent → serial MAVLink to FC (<50ms) |
| **Autonomous engagement** | ✅ Aircraft can engage autonomously | ✅ Lattice can engage with operator pre-authorization | ✅ DroneHunter launches autonomously, captures with nets | ✅ Sensor-to-Shooter with wave-off capability | ⚠️ Tier 3 requires operator authorization (iDEX/DPCO compliance). |
| **Response Modalities** | Kinetic, EW | Kinetic, EW, cyber | Kinetic (net capture — non-lethal) | Kinetic (Switchblade), ISR (Puma) | Failsafe, CBBA patrol, formation adjust, EW soft-kill, intercept. |
