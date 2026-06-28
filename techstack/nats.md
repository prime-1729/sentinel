# NATS — Deep Dive for SENTINEL

> **Purpose:** Comprehensive technical reference on NATS messaging — what it is, how it works internally, and exactly how SENTINEL uses it for drone-to-drone communication.

Last Updated: 2026-06-28

---

## 1. What is NATS?

NATS is an **open-source, lightweight messaging system** written in Go. It is a single binary (~17MB) that acts as a message broker — processes connect to it and exchange messages via named subjects (topics).

Think of it as a **postal system for software**:
- A process **publishes** a message to a subject (like mailing a letter to an address)
- Any process **subscribed** to that subject receives the message (like having a PO box)
- The NATS server is the post office that routes messages

### Why NATS, not Kafka/RabbitMQ/MQTT?

| Feature | NATS | Kafka | RabbitMQ | MQTT |
|---|---|---|---|---|
| **Binary size** | ~17MB | ~500MB+ JVM | ~100MB + Erlang | ~5MB |
| **Latency** | <1ms | 2-10ms | 1-5ms | 1-5ms |
| **RAM usage** | ~10MB idle | 1GB+ | 100MB+ | ~10MB |
| **Runs on Raspberry Pi** | ✅ Yes | ❌ No (JVM) | ⚠️ Painful | ✅ Yes |
| **Clustering/Mesh** | ✅ Built-in | ✅ Built-in | ✅ Clustering | ❌ No native |
| **Leaf nodes (edge)** | ✅ Native | ❌ No | ❌ No | ❌ No |
| **Language** | Go | Java/Scala | Erlang | C/varies |

**NATS wins for drones because:**
1. Tiny footprint — runs on companion computers (RPi, Jetson Nano)
2. Sub-millisecond latency — critical for real-time threat response
3. **Leaf node architecture** — drones can form isolated clusters that reconnect to a hub when in range
4. No external dependencies — single binary, no JVM, no Erlang
5. Built-in clustering for GCS ↔ Drone mesh bridging

---

## 2. Core Concepts

### 2.1 Subjects (Topics)

Messages are routed by **subject** — a string with dot-separated segments.

```
sentinel.threats.alert          # A specific subject
sentinel.threats.confirm        # Another specific subject  
sentinel.threats.>              # Wildcard: matches ALL subjects starting with sentinel.threats.
sentinel.telemetry.*.position   # Wildcard: matches sentinel.telemetry.drone_0.position, etc.
```

**Wildcard rules:**
- `*` matches exactly one token: `sentinel.*.alert` matches `sentinel.threats.alert` but NOT `sentinel.threats.sub.alert`
- `>` matches one or more tokens (must be last): `sentinel.threats.>` matches everything under `sentinel.threats.`

### 2.2 Pub/Sub Pattern

The fundamental pattern. Publishers and subscribers are fully decoupled — they don't know about each other.

```
Publisher A                    NATS Server              Subscriber X
    │                              │                        │
    │── Publish("threats.alert")──►│                        │
    │                              │── Deliver to all ──►   │
    │                              │                   Subscriber Y
    │                              │── Deliver to all ──►   │
```

- **Fire and forget**: Publisher doesn't wait for acknowledgment
- **Fan-out**: One message can go to N subscribers
- **No persistence**: If no one is subscribed, the message is dropped (use JetStream for persistence)

### 2.3 Request/Reply Pattern

Synchronous request-response built on top of pub/sub. The requester publishes a message with a unique "reply-to" subject, and the responder publishes back to that subject.

```
Requester                      NATS Server              Responder
    │                              │                        │
    │── Publish("threats.alert",   │                        │
    │   reply_to="_INBOX.abc123")─►│                        │
    │                              │── Deliver ──────────►  │
    │                              │                        │
    │                              │◄── Publish("_INBOX.    │
    │◄── Deliver ──────────────────│    abc123", response)──│
```

This is how the NATS latency test works — the Go agent receives a PING_TEST alert and replies on the confirm topic.

### 2.4 JetStream (Persistence)

Standard NATS is ephemeral — messages are fire-and-forget. **JetStream** adds:
- Message persistence (disk/memory)
- At-least-once / exactly-once delivery
- Message replay (consumers can read historical messages)
- Stream-based processing (like Kafka)

**SENTINEL use case:** JetStream will be critical for the CRDT gossip protocol — if a drone temporarily loses mesh connectivity, it needs to catch up on missed `fleet.state` messages when it reconnects.

### 2.5 Leaf Nodes

A NATS feature specifically designed for edge computing:

```
           ┌──────────────┐
           │  Hub Server  │ (GCS)
           │  (Full NATS) │
           └──┬───────┬───┘
              │       │
        ┌─────┘       └─────┐
        ▼                    ▼
  ┌──────────┐        ┌──────────┐
  │ Leaf Node│        │ Leaf Node│
  │ (Drone 1)│◄──────►│ (Drone 2)│  ← Can also peer directly
  └──────────┘        └──────────┘
```

- Each drone runs a **leaf node** NATS server
- Leaf nodes connect to a hub (GCS) when in range
- Leaf nodes can also connect to each other for direct D2D comms
- When disconnected from hub, leaf nodes continue operating independently
- When reconnected, they automatically sync (with JetStream)

This maps perfectly to SENTINEL's degradation model:
- **NORMAL**: All leaf nodes connected to GCS hub
- **DEGRADED**: Leaf nodes peering directly, no GCS
- **AUTONOMOUS**: Single leaf node, local pub/sub only

---

## 3. How NATS Works Internally

### 3.1 Connection Lifecycle

```
1. Client opens TCP connection to NATS server (default port 4222)
2. Server sends INFO message (version, server ID, auth requirements)
3. Client sends CONNECT message (credentials, protocol version)
4. Connection established — client can now PUB/SUB
5. Server sends PINGs every 2 minutes to check liveness
6. Client responds with PONGs
7. If 2 PINGs go unanswered → connection dropped
```

### 3.2 Message Routing

NATS uses a **trie-based subject matcher** internally:

```
sentinel
  └── threats
  │     ├── alert     → [subscriber1, subscriber2]
  │     ├── confirm   → [subscriber3]
  │     └── bid       → [subscriber4]
  └── fleet
        └── state
              └── *   → [subscriber5]  (wildcard)
```

When a message is published to `sentinel.threats.alert`:
1. Server walks the trie to find matching subscribers
2. Copies the message to each subscriber's outbound buffer
3. Flushes buffers (async, batched for throughput)

**This is why NATS is so fast** — it's an in-memory router with zero persistence overhead (unless JetStream is enabled).

### 3.3 Wire Protocol

NATS uses a text-based protocol (human-readable, easy to debug):

```
# Subscribe to a subject
SUB sentinel.threats.alert 1\r\n

# Publish a message (12 bytes of payload)
PUB sentinel.threats.alert 12\r\n
<12 bytes of protobuf data>\r\n

# Message delivered to subscriber
MSG sentinel.threats.alert 1 12\r\n
<12 bytes of protobuf data>\r\n
```

---

## 4. SENTINEL's NATS Topic Architecture

From `service_architecture.md §2`:

```
sentinel.fleet.state.{drone_id}      # CRDT sync (1Hz gossip)
sentinel.threats.alert               # Epidemic broadcast (TAPP Phase 1)
sentinel.threats.confirm             # Sensor cross-validation (TAPP Phase 2)
sentinel.threats.bid                 # CBBA auction (TAPP Phase 3)
sentinel.threats.report              # Post-action reporting (TAPP Phase 4)
sentinel.mesh.topology               # Mesh routing updates
sentinel.telemetry.{drone_id}.*      # Raw telemetry streams
```

### Data Flow Through Topics

```
  Python Sidecar                NATS                    Go Edge Agent
  (5-domain ML)                Server                  (TAPP + CBBA)
       │                         │                          │
       │  Detects GPS spoofing   │                          │
       ├── PUB threats.alert ───►│                          │
       │                         │── Deliver ──────────────►│
       │                         │                          │ Trigger TAPP Phase 1
       │                         │                          │ Epidemic broadcast
       │                         │◄── PUB threats.alert ────│ (TTL-1, forward to mesh)
       │                         │                          │
       │                         │── Deliver to Drone2 ────►│
       │                         │── Deliver to Drone3 ────►│
       │                         │                          │
       │                         │◄── PUB threats.confirm ──│ Drone2 corroborates
       │                         │                          │
       │                         │◄── PUB threats.bid ──────│ Drones bid to intercept
       │                         │                          │
       │                         │◄── PUB threats.report ───│ Winning drone reports
```

### Current Implementation Status

| Topic | Message Format | Used By | Status |
|---|---|---|---|
| `sentinel.threats.alert` | Protobuf `ThreatAlert` | main.go (subscribe), test_nats_latency.py (publish) | ✅ Working |
| `sentinel.threats.confirm` | Protobuf `ThreatConfirm` | main.go (publish on PING_TEST) | ✅ Working |
| `sentinel.threats.bid` | Protobuf `ThreatBid` | — | 🔴 Not used |
| `sentinel.threats.report` | — | — | 🔴 Not defined |
| `sentinel.fleet.state.*` | Protobuf `NodeState` | — | 🔴 Not used |
| `sentinel.telemetry.*.position` | JSON | telemetry.py (publish) | ✅ Working |
| `sentinel.telemetry.ros.*` | JSON | bridge_node.py (publish) | ✅ Working |

---

## 5. Running NATS for Development

```bash
# Start NATS server (from .tools/)
./scripts/start_nats.sh
# Or directly:
.tools/nats-server &

# Default: localhost:4222, no auth
# Monitor: http://localhost:8222 (if monitoring enabled)

# Test connectivity (Go agent)
cd src/edge-agent && go run ./cmd/sentinel-agent/

# Test connectivity (Python)
python -c "import asyncio, nats; asyncio.run(nats.connect('nats://localhost:4222'))"
```

---

## 6. Go Syntax Explained

### The Signal Channel Pattern in `main.go`

```go
sigCh := make(chan os.Signal, 1)
signal.Notify(sigCh, syscall.SIGINT, syscall.SIGTERM)
<-sigCh
```

**Line-by-line:**

1. `sigCh := make(chan os.Signal, 1)` — Creates a **channel** (Go's concurrency primitive for communication between goroutines). This channel carries `os.Signal` values and has a buffer of 1. Think of it as a pipe that can hold one signal.

2. `signal.Notify(sigCh, syscall.SIGINT, syscall.SIGTERM)` — Tells the OS: "When this process receives SIGINT (Ctrl+C) or SIGTERM (kill command), put the signal into `sigCh` instead of immediately killing the process."

3. `<-sigCh` — **Blocks** the current goroutine (main thread) until something is received from the channel. The program sits here doing nothing until Ctrl+C or a kill signal arrives. Meanwhile, the NATS subscription callbacks run in background goroutines.

**Why this pattern?** Without it, `main()` would exit immediately after setting up subscriptions, killing the process. This keeps the agent alive until explicitly terminated.

**Analogy:** It's like a receptionist sitting at a desk waiting for the phone to ring. The `make(chan)` creates the phone, `signal.Notify` forwards calls to that phone, and `<-sigCh` is the receptionist picking up when it rings.
