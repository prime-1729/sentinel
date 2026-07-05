# Intelligence Sidecar — Low-Level Design & Codeflow

> **Scope:** Complete technical breakdown of `src/intelligence/` — every file, every class, every function, and how data flows from raw telemetry/video to anomaly and threat alerts.

Last Updated: 2026-07-05

---

## 1. High-Level Overview

The Intelligence Sidecar is the **ML and Computer Vision brain running on every drone**. It is a pure Python daemon that subscribes to telemetry and camera feeds via NATS, runs parallel anomaly detection and perception pipelines, evaluates threats, and publishes alerts and autonomous reactions into the NATS mesh.

| Component | Location | Status | Responsibility |
|---|---|---|---|
| **NATS Sidecar** | `sidecar.py` | ✅ Implemented | Daemon subscribing to NATS telemetry/camera and running the async loops |
| **Anomaly Pipeline** | `domains/anomaly.py` | ✅ Implemented | Orchestrator: runs Physics Detectors → IF (Layer 1) → LSTM (Layer 2) → Domain (Layer 3) |
| **Physics Detectors** | `domains/*.py` | ✅ Implemented | Domain-specific checks (Propulsion, Power, Navigation, Dynamics, EW) |
| **Perception CV** | `perception/detector.py` | ✅ Implemented | YOLOv8 ONNX object detection (80 COCO + 6 Sentinel classes) |
| **Tracking** | `tracking/tracker.py` | ✅ Implemented | Hungarian + Kalman filter multi-object tracker |
| **Threat Assessment** | `threat/*.py` | ✅ Implemented | Trajectory behavior classification and multi-factor threat scoring |
| **Reaction Engine** | `autonomy/reaction_rules.py`| ✅ Implemented | Deterministic safety rule evaluation based on anomalies and threats |

```
┌──────────────────────────────────────────────────────────────────────┐
│                  DRONE (EDGE NODE)                                   │
│                                                                      │
│  ┌─────────────────────────────────────────────────────────────┐     │
│  │            Python Intelligence Sidecar                      │     │
│  │                                                             │     │
│  │            NATS Subscription (Telemetry + Camera)           │     │
│  │                 sentinel.telemetry.>                        │     │
│  │                           │                                 │     │
│  │          ┌────────────────┴───────────────┐                 │     │
│  │          ▼                                ▼                 │     │
│  │  ┌──────────────┐                 ┌──────────────┐          │     │
│  │  │   Anomaly    │                 │  Perception  │          │     │
│  │  │   Pipeline   │                 │   Pipeline   │          │     │
│  │  │  (IF + LSTM) │                 │(YOLO+Tracker)│          │     │
│  │  └──────┬───────┘                 └──────┬───────┘          │     │
│  │         │                                │                  │     │
│  │         ▼                                ▼                  │     │
│  │  ┌──────────────┐                 ┌──────────────┐          │     │
│  │  │ Domain Class │                 │ Threat Score │          │     │
│  │  └──────┬───────┘                 └──────┬───────┘          │     │
│  │         │                                │                  │     │
│  │         └────────────────┬───────────────┘                  │     │
│  │                          ▼                                  │     │
│  │                  ┌──────────────┐                           │     │
│  │                  │   Reaction   │                           │     │
│  │                  │    Engine    │                           │     │
│  │                  └──────┬───────┘                           │     │
│  │                         │                                   │     │
│  │                         ▼                                   │     │
│  │         NATS Publish (Threat Alerts & Commands)             │     │
│  │     sentinel.threats.alert / sentinel.command.drone_id      │     │
│  └─────────────────────────────────────────────────────────────┘     │
│                                                                      │
│  ┌──────────────────────────────┐                                    │
│  │  Go Edge Agent               │◄── Subscribes to commands & alerts │
│  │  (NATS mesh, TAPP, CBBA)     │                                    │
│  └──────────────────────────────┘                                    │
└──────────────────────────────────────────────────────────────────────┘
```

---

## 2. Directory Structure

```
src/intelligence/
├── __init__.py
├── sidecar.py                    # NATS daemon — orchestrates all pipelines
├── pb/                           # Protobuf Python bindings (threat_pb2, fleet_pb2)
├── domains/                      # Anomaly detection
│   ├── anomaly.py                # AnomalyPipeline (IF → LSTM → Domain)
│   ├── propulsion.py             # FFT vibration + MCSA motor current
│   ├── power.py                  # Impedance estimation + voltage sag
│   ├── navigation.py             # GPS jump + GPS-IMU cross-val + alt divergence
│   ├── flight_dynamics.py        # Stall detection + wind shear + attitude rate
│   └── electronic_warfare.py     # GPS satellite drop + HDOP + RSSI jamming
├── ml_models/                    # ML model implementations
│   ├── isolation_forest.py       # Layer 1 — Isolation Forest
│   ├── lstm_autoencoder.py       # Layer 2 — LSTM Autoencoder (PyTorch + ONNX)
│   └── domain_classifier.py      # Layer 3 — Random Forest domain classifier
├── perception/                   # Computer vision
│   └── detector.py               # YOLO ONNX detection (80 COCO + 6 Sentinel classes)
├── tracking/                     # Multi-object tracking
│   ├── tracker.py                # Hungarian + Kalman tracker
│   └── visual_servo.py           # PID visual servoing controller
├── threat/                       # Threat assessment
│   ├── behavior_analyzer.py      # Trajectory behavior classification
│   └── threat_scorer.py          # Multi-factor threat scoring
├── autonomy/                     # Reaction engine
│   └── reaction_rules.py         # Deterministic safety rules (debounce + escalation)
└── evaluation/                   # Metrics
    └── metrics.py                # Evaluation functions
```

---

## 3. Dependencies

| Library | Version | Purpose |
|---|---|---|
| `nats-py` | — | NATS client for subscribing to telemetry and publishing alerts |
| `pandas` | — | Telemetry DataFrames: time-series manipulation, rolling windows |
| `numpy` | — | Array ops, matrix math, bounding box manipulation |
| `scikit-learn` | — | `IsolationForest`, `RandomForestClassifier`, metrics |
| `torch` | — | PyTorch for LSTM Autoencoder training |
| `onnxruntime` | — | High-performance inference for YOLO and LSTM |
| `opencv-python` | — | Image processing, NMS, resizing, JPEG decoding |
| `scipy` | — | Hungarian algorithm (`linear_sum_assignment`) for tracking |

---

## 4. Pipeline Execution Flows

### 4.1 NATS Daemon (`sidecar.py`)

The sidecar runs multiple asynchronous loops:
- `_on_telemetry`: Buffers incoming JSON telemetry into rolling `collections.deque` (60s retention) for 7 streams.
- `_on_camera_frame`: Decodes base64 JPEG strings from `sentinel.telemetry.drone_id.camera` and stores the latest OpenCV frame.
- `_anomaly_loop`: Every 2 seconds, converts buffers to DataFrames and runs `AnomalyPipeline`.
- `_perception_loop`: At ~10 FPS, processes the latest camera frame through YOLO, tracks objects, and scores threats.
- `_heartbeat_loop`: Publishes a health status to `sentinel.fleet.health`.

### 4.2 Anomaly Pipeline (`domains/anomaly.py`)

1. Executes 5 Physics-based domain detectors (`propulsion`, `power`, `navigation`, `dynamics`, `ew`).
2. Runs **Layer 1** Isolation Forest. If normal, stops.
3. For anomalous timestamps, runs **Layer 2** LSTM Autoencoder on the 30-step sequence leading up to the anomaly. If reconstruction error is normal, denies the anomaly.
4. If confirmed by Layer 2, extracts features and runs **Layer 3** Random Forest Domain Classifier to label the fault.
5. Emits `AnomalyEvent` objects.

### 4.3 Perception Pipeline (`perception/` & `tracking/` & `threat/`)

1. **YOLO Detection:** `ObjectDetector.detect()` resizes and normalizes the image, runs the ONNX model, and applies NMS. Emits `Detection` bounding boxes.
2. **Tracking:** `MultiObjectTracker.update()` runs Kalman filter predict steps on existing tracks, matches detections using IoU and the Hungarian algorithm, and runs Kalman filter update steps.
3. **Behavior Analysis:** `BehaviorAnalyzer` calculates path meandering and displacement to classify tracks as `approaching`, `loitering`, `erratic`, etc.
4. **Scoring:** `ThreatScorer` combines object class base score, proximity (bounding box area), and behavior to produce a 0.0 - 1.0 threat score.

### 4.4 Reaction Engine (`autonomy/reaction_rules.py`)

Consumes `AnomalyEvent`s and `Threat`s. Maps them to deterministic rules (e.g., `WindShear` → `maintain_altitude`, `battery_critical` → `rtl`). Includes hysteresis (debounce) to avoid flickering commands, and escalation logic if a condition persists. Commands are published to `sentinel.command.{drone_id}`.

---

## 5. Interaction with Other Services

| Service | How Intelligence Interacts |
|---|---|
| **ROS2 Bridge** | Publishes raw sensor data into NATS `sentinel.telemetry.>` which sidecar consumes. |
| **Edge Agent (Go)** | Go subscribes to `sentinel.threats.alert` and `sentinel.command.>` to execute reactions via MAVLink, and broadcasts TAPP alerts to the swarm. |

---

## 6. Legacy Migration Note

The legacy monolithic files (`live_feed.py`, `monitor.py`, `live_state.py`) have been entirely superseded by this `sidecar.py` implementation, providing a clean separation where ROS2 collects, Python analyzes via NATS, and Go acts.
