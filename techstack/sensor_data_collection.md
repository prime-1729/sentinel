# Sensor Data Collection & Autopilot Integration

> **Purpose:** Research existing frameworks for extracting sensor data from drones. We don't need to build this from scratch.

Last Updated: 2026-06-21

---

## 1. The Key Insight: Use Existing Stacks

The drone sensor data collection problem is SOLVED. Multiple mature frameworks exist:

| Framework | Autopilot | Transport | Language | Maturity |
|---|---|---|---|---|
| **MAVROS** | ArduPilot, PX4 | MAVLink → ROS2 topics | C++/Python | Production (10+ years) |
| **uXRCE-DDS** | PX4 | DDS (native) → ROS2 topics | C/C++ | Production (PX4 native) |
| **MAVSDK** | ArduPilot, PX4 | MAVLink (high-level API) | C++/Python/Rust/Go/Java | Production |
| **PyMAVLink** | ArduPilot, PX4 | MAVLink (low-level) | Python | What we use today |
| **Aerostack2** | ArduPilot, PX4 | ROS2 abstraction | C++/Python | Research-production |
| **DroneKit** | ArduPilot | MAVLink (high-level) | Python | Deprecated but still used |

---

## 2. MAVLink — What We Have Today

MAVLink is a binary protocol for drone ↔ GCS communication. We use PyMAVLink directly.

**What MAVLink gives us:**
- Position (GPS), Battery, Attitude, HUD, Radio Status, GPS Quality, ESC telemetry
- ~200+ message types defined in the protocol
- Works with ANY MAVLink-compatible autopilot

**What MAVLink does NOT give us:**
- Camera feeds (separate video stream, usually RTSP/GStreamer)
- LiDAR point clouds (separate data path, usually via ROS2)
- Thermal/IR imagery (separate sensor, usually via SDK)
- Acoustic data (not part of drone telemetry)

---

## 3. ROS2 + DDS — The Industry Standard

ROS2 (Robot Operating System 2) with DDS middleware is the industry standard for robotics, including drones.

### Why ROS2 Matters for SENTINEL

| Problem | Without ROS2 | With ROS2 |
|---|---|---|
| Adding a new sensor (LiDAR) | Write custom parser, integrate manually | Install ROS2 driver package, subscribe to topic |
| Computer vision pipeline | Build from scratch in Python | Use `cv_bridge`, subscribe to camera topics |
| Multi-sensor fusion | Manual timestamp alignment | ROS2 message filters handle time sync |
| Simulation | SITL only | Gazebo/AirSim with full physics |

### ROS2 for ArduPilot (Our Autopilot)

```
ArduPilot FC  ←serial→  MAVROS Node  ←DDS→  ROS2 Topics
                                              ↓
                                    Your Python/C++ Nodes
                                    (anomaly detection, etc.)
```

Available ROS2 topics via MAVROS:
- `/mavros/imu/data` — Accelerometer + Gyroscope
- `/mavros/global_position/global` — GPS position
- `/mavros/battery` — Battery state
- `/mavros/state` — Armed/disarmed, flight mode
- `/mavros/local_position/pose` — Local frame position
- `/mavros/rc/in` — RC input channels
- Plus 50+ more topics

### ROS2 for PX4 (Alternative Autopilot)

```
PX4 FC  ←serial→  MicroXRCEAgent  ←DDS→  ROS2 Topics
                                           ↓
                                   Your ROS2 Nodes
```

PX4 publishes uORB topics directly as ROS2 topics — no translation layer needed.

---

## 4. MAVSDK — High-Level Alternative

MAVSDK is a cleaner, higher-level API than raw PyMAVLink. Available in Python, C++, Rust, Go, Java.

```python
# MAVSDK (clean, typed, async)
from mavsdk import System
drone = System()
await drone.connect(system_address="udp://:14540")

async for position in drone.telemetry.position():
    print(f"Lat: {position.latitude_deg}, Lon: {position.longitude_deg}")

async for battery in drone.telemetry.battery():
    print(f"Voltage: {battery.voltage_v}, Remaining: {battery.remaining_percent}")
```

**vs PyMAVLink (what we use today):**
```python
# PyMAVLink (low-level, raw)
msg = conn.recv_match(type='GLOBAL_POSITION_INT', blocking=True)
lat = msg.lat / 1e7
lon = msg.lon / 1e7
```

### Recommendation
- **Keep PyMAVLink** for the edge agent (lowest overhead, direct control)
- **Use MAVSDK** for higher-level fleet management services
- **Add ROS2/MAVROS** when we need camera/LiDAR/multi-sensor fusion

---

## 5. Frameworks We Should NOT Build

| Capability | Existing Solution | Don't Build |
|---|---|---|
| MAVLink parsing | PyMAVLink, MAVSDK | ❌ Custom MAVLink parser |
| Sensor abstraction | ROS2 + MAVROS | ❌ Custom sensor framework |
| Video streaming | GStreamer + RTSP | ❌ Custom video pipeline |
| Simulation | ArduPilot SITL + Gazebo | ❌ Custom simulator |
| Path planning lib | OMPL (ROS2 integrated) | ❌ Custom planner from scratch |
| Computer vision | OpenCV + ROS2 cv_bridge | ❌ Custom CV pipeline |

---

## 6. Architecture Decision: ROS2 is Core Table Stakes

| Phase | Stack | Reason |
|---|---|---|
| Core Telemetry | PyMAVLink | Efficient parsing for FC flight state (`RAW_IMU`, `ESC_STATUS`). |
| Advanced Sensors | ROS2 + MAVROS | **Table stakes for SENTINEL.** Required for computer vision, LiDAR point clouds, and multi-sensor fusion. |
| Fleet State | NATS + CRDTs | High-level fleet coordination and CBBA auction state. |

### Key Consideration
We are no longer treating ROS2 as a "future adoption." To compete with industry leaders (Shield AI, Anduril) and implement edge-native 5-domain intelligence, sensor-agnostic ingestion is mandatory. ROS2 forms the core internal bus on every companion computer, bridging complex sensors (cameras, LiDAR, external radar) into the Python/Go intelligence sidecars, before distilled anomalies are broadcast over the NATS mesh.
