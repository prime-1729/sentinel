# Mesh & P2P Networking for Drone Swarms

> **Purpose:** Research document on mesh networking protocols, P2P communication, and how drone swarms maintain connectivity in contested environments.

Last Updated: 2026-06-21

---

## 1. Why Mesh Networking — The Core Problem

In a star topology (what we have today), all communication routes through the GCS:

```
         ┌─────┐
    ┌────│ GCS │────┐
    │    └─────┘    │
    ↓       ↓       ↓
  [D1]    [D2]    [D3]
```

**Problems with star topology:**
- **Single Point of Failure:** GCS goes down → all coordination stops
- **Range limitation:** Every drone must be within radio range of GCS
- **Bandwidth bottleneck:** All N drones share one radio link to GCS
- **Latency for coordination:** Drone-to-drone messages must round-trip through GCS
- **Jamming vulnerability:** Jam one frequency → entire fleet loses coordination

In a mesh topology:

```
  [D1] ←→ [D2] ←→ [D3]
    ↕    ↗    ↕
  [D4] ←→ [D5]
    ↕
  [GCS] (optional)
```

**Advantages:**
- **No single point of failure** — any node can die
- **Extended range** — drones relay for each other (multi-hop)
- **Distributed bandwidth** — local traffic stays local
- **Low latency coordination** — neighbor-to-neighbor, no GCS round-trip
- **Jamming resilience** — frequency hopping + multiple paths

---

## 2. Network Types & Terminology

### MANET — Mobile Ad Hoc Network
A network where nodes (drones) are mobile and form connections dynamically without any fixed infrastructure. Each node is both client and router.

### FANET — Flying Ad Hoc Network
A MANET where all nodes are airborne. Special challenges:
- **High mobility** — nodes moving at 10-30+ m/s
- **3D topology** — not just 2D like ground MANETs
- **Power constraints** — radio power = battery drain
- **Sparse density** — fewer nodes per area than ground networks
- **Frequent topology changes** — as drones move in/out of range

### Mesh Topology
Every node connects to multiple peers. Data can take multiple paths. Self-healing — if a link breaks, traffic reroutes automatically.

### P2P (Peer-to-Peer)
No central server. All nodes are equal. Any node can initiate communication with any other node. Contrasts with client-server (star) model.

---

## 3. Routing Protocols for FANETs

### 3.1 Proactive Protocols (Table-Driven)
Each node maintains a routing table to ALL other nodes, updated continuously.

| Protocol | How It Works | Pros | Cons |
|---|---|---|---|
| **OLSR** (Optimized Link State Routing) | Each node broadcasts link state info. All nodes build full topology map. | Low latency (routes pre-computed). Good for small networks (5-20 nodes). | High overhead — broadcasts consume bandwidth. Doesn't scale past ~50 nodes. |
| **BATMAN** (Better Approach To Mobile Ad-hoc Networking) | Nodes periodically broadcast "originator messages." Neighbors track best next-hop. | Simple. Works well for mesh networks. Linux kernel support. | Higher latency than OLSR for initial routes. |

### 3.2 Reactive Protocols (On-Demand)
Routes are discovered only when needed. Lower overhead but higher initial latency.

| Protocol | How It Works | Pros | Cons |
|---|---|---|---|
| **AODV** (Ad-hoc On-Demand Distance Vector) | Route discovery broadcasts when a node needs to reach another. | Low overhead (no constant broadcasts). | Route discovery adds latency (100-500ms first time). |
| **DSR** (Dynamic Source Routing) | Source node includes full route in packet header. | No routing tables needed. Good for sparse networks. | Large packet headers. Not suitable for high-throughput. |

### 3.3 Hybrid Protocols
Combine proactive and reactive. Best of both worlds.

| Protocol | How It Works | Best For |
|---|---|---|
| **ZRP** (Zone Routing Protocol) | Proactive within a "zone" (k-hop neighborhood). Reactive for distant nodes. | Medium-large swarms (20-100 drones). |

### Recommendation for SENTINEL
- **Start with OLSR** for 2-10 drones — it's simple, well-supported, and the overhead is negligible at this scale.
- **Move to BATMAN-adv** when scaling — it's in the Linux kernel, handles mobile nodes well, and is used by community mesh networks worldwide.
- **Consider ZRP** if scaling beyond 50 drones — the hybrid approach reduces broadcast overhead.

---

## 4. Data Distribution Patterns

### 4.1 Gossip Protocol
- Each node periodically shares its state with random neighbors
- Neighbors forward to their neighbors
- Eventually consistent — every node gets every update
- **Convergence time:** For 10 nodes, ~3-5 rounds (~200-500ms)
- Used by: Amazon Dynamo, Apache Cassandra, and most swarm coordination systems

### 4.2 Pub/Sub (Publish/Subscribe)
- Nodes "publish" data on named topics (e.g., "position", "anomaly_events")
- Other nodes "subscribe" to topics they care about
- A message broker or DHT routes messages to subscribers
- **Used by:** Anduril Lattice (Lattice Mesh), ROS2 (DDS), NATS

### 4.3 CRDTs (Conflict-free Replicated Data Types)
Data structures that can be merged without conflicts or coordination:
- **G-Counter:** Grow-only counter (each node increments own slot, total = sum)
- **LWW-Register:** Last-Writer-Wins register (keep value with latest timestamp)
- **OR-Set:** Observed-Remove Set (add/remove elements without conflicts)

**Why CRDTs matter for drones:**
When two drones both update fleet state simultaneously (no central coordinator), CRDTs guarantee the merged result is always correct. No locking, no consensus protocol, no leader election.

---

## 5. Anti-Jamming & Resilience Techniques

### 5.1 Frequency Hopping Spread Spectrum (FHSS)
- Radio rapidly switches frequencies (100+ hops/second)
- Jammer must jam ALL frequencies simultaneously (very expensive)
- Standard in military radios (MIL-STD-188-141B)
- SiK radios (our current hardware) support basic FHSS

### 5.2 Channel Hopping
- Software-defined channel switching
- MIT LINCOLN LAB's QLIMM protocol: drones share queue states to optimize which channels to use
- Avoids jammed bands automatically

### 5.3 Multi-Modal Communication
- **Primary:** RF mesh (915 MHz / 2.4 GHz)
- **Backup:** Optical (laser/LiFi) — immune to RF jamming
- **Tertiary:** Acoustic (underwater/close range)
- **Fallback:** SATCOM (if available)
- Industry standard: 2+ independent communication paths

### 5.4 Power Control
- Reduce transmission power to limit interception range
- Increase power only when needed (adaptive power control)
- "Low probability of intercept" (LPI) communication

---

## 6. Hardware Options

| Radio | Type | Range | Bandwidth | Weight | Cost | Mesh Support |
|---|---|---|---|---|---|---|
| **SiK 915MHz** | Point-to-point | 1-2 km | 57.6 kbps | 5g | ~$30 | ❌ No mesh |
| **ESP32 (ESP-NOW)** | WiFi mesh | 200m LOS | 1 Mbps | 3g | ~$5 | ✅ Built-in |
| **XBee 900HP** | Mesh radio | 1.6 km | 200 kbps | 8g | ~$40 | ✅ DigiMesh |
| **Doodle Labs Helix** | COFDM mesh | 5-10 km | 20+ Mbps | 85g | ~$2,000 | ✅ IP mesh |
| **Rajant Peregrine** | Kinetic mesh | 2-5 km | 40+ Mbps | 120g | ~$3,000 | ✅ Self-healing |
| **Silvus StreamCaster** | MIMO mesh | 5-80 km | 100+ Mbps | 200g | ~$5,000 | ✅ MANET |
| **Persistent Systems MPU5** | MIMO mesh | 4+ km | 100+ Mbps | 350g | ~$8,000 | ✅ Wave Relay |

### Recommendation for SENTINEL
1. **Development/SITL:** Virtual mesh over localhost UDP (free, no hardware)
2. **Lab prototype:** ESP32 ESP-NOW ($5/node, 200m range, good enough for indoor testing)
3. **Field demo:** XBee 900HP ($40/node, 1.6km, real mesh protocol)
4. **Production:** Doodle Labs Helix ($2K/node, military-grade, IP mesh)

---

## 7. Software Frameworks & Libraries

### 7.1 NATS (Messaging)
- **What:** Lightweight pub/sub messaging system, single Go binary (~17MB)
- **Edge suitability:** Excellent — runs on Raspberry Pi, ARM devices
- **Features:** Topic-based pub/sub, request-reply, JetStream for persistence
- **Why for drones:** Sub-millisecond latency, handles intermittent connectivity (leaf nodes), minimal resource usage
- **Use case:** Inter-service communication on companion computer + GCS

### 7.2 DDS (Data Distribution Service)
- **What:** Real-time pub/sub middleware, the native transport for ROS2
- **Edge suitability:** Good — runs on embedded systems
- **Features:** Quality-of-Service policies, real-time guarantees, automatic discovery
- **Why for drones:** Industry standard for robotics, used by PX4 (uXRCE-DDS)
- **Use case:** On-drone sensor data distribution between flight controller and companion computer

### 7.3 ZeroMQ
- **What:** High-performance async messaging library
- **Edge suitability:** Excellent — C library with bindings for every language
- **Features:** Various patterns (pub/sub, push/pull, request-reply), no broker needed
- **Why for drones:** Brokerless = one less thing to fail
- **Use case:** Direct drone-to-drone coordination messages

### 7.4 libp2p
- **What:** Modular P2P networking library (from IPFS project)
- **Edge suitability:** Moderate — Go/Rust implementations available
- **Features:** Peer discovery, NAT traversal, multiplexing, encryption
- **Why for drones:** Battle-tested P2P stack with security built in
- **Use case:** Higher-level P2P overlay if mesh radio provides IP connectivity

---

## 8. MAVLink Over Mesh — How It Works

MAVLink is just a binary protocol — it doesn't care what transport it rides on. Today it rides on serial/UDP point-to-point. On a mesh, it rides inside mesh packets:

```
┌────────────────────────────────────────────────┐
│  Mesh Packet Header (source, dest, hop count)  │
│  ┌──────────────────────────────────────────┐  │
│  │  MAVLink Packet                          │  │
│  │  (system_id, component_id, msg_id,       │  │
│  │   sequence, payload, CRC)                │  │
│  └──────────────────────────────────────────┘  │
└────────────────────────────────────────────────┘
```

**Key consideration:** MAVLink uses `system_id` to identify drones. On a mesh, all drones hear all messages. Each drone filters for its own `system_id`. This already works — MAVLink was designed for multi-vehicle environments.

### MAVLink v2 Signing
MAVLink v2 supports packet signing for authentication. This prevents a hostile node from injecting commands into the mesh. We should enable signing on all mesh communications.

---

## 9. Open Questions for Implementation

| Question | Impact | Research Needed |
|---|---|---|
| OLSR vs BATMAN for 2-10 drones? | Protocol selection affects latency and reliability | Benchmark both on SITL virtual mesh |
| NATS vs DDS for inter-service communication? | Resolved: NATS | NATS chosen for edge mesh due to lightweight leaf node capabilities and TAPP protocol support. ROS2/DDS used internally per-node for sensor ingestion. |
| How to handle mesh partition? | Resolved: CRDTs | Implemented Fleet State CRDTs. Each partition operates independently and merges state gracefully upon reconnection. |
| Task Allocation Mechanism? | Resolved: CBBA | Consensus-Based Bundle Algorithm (CBBA) is primary for decentralized task allocation without GCS. |
