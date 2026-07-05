# Intelligence Codebase — Deep Dive Explanation & Code Review

> **Audience:** Someone with little ML/math background.  
> **Scope:** Every file in `src/intelligence/` — what it does, why, with examples, plus a brutally honest code quality review.

---

## Table of Contents

1. [The Big Picture](#1-the-big-picture)
2. [ML Models — The Brain](#2-ml-models)
3. [Domains — The Anomaly Pipeline](#3-domains--anomaly-pipeline)
4. [Perception — Computer Vision](#4-perception--computer-vision)
5. [Tracking — Following Objects Across Frames](#5-tracking)
6. [Threat — Behavior Analysis & Scoring](#6-threat-assessment)
7. [Autonomy — Reaction Rules](#7-autonomy--reaction-rules)
8. [Sidecar — The Orchestrator](#8-sidecar--the-orchestrator)
9. [Code Quality Review & Issues Found](#9-code-quality-review)

---

## 1. The Big Picture

The intelligence service has two parallel pipelines:

```
PIPELINE A: "Is my drone healthy?"
  Telemetry numbers → Isolation Forest → LSTM Autoencoder → Domain Classifier → Anomaly Alert

PIPELINE B: "Is something threatening my drone?"
  Camera frames → YOLO Detector → Multi-Object Tracker → Behavior Analyzer → Threat Scorer → Threat Alert
```

Both feed into the **Reaction Engine** which decides: "Do I need to take emergency action?"

---

## 2. ML Models

### 2.1 Isolation Forest (`ml_models/isolation_forest.py`) — Layer 1

**What it is in plain English:**  
Imagine you teach the drone what "normal flying" looks like by showing it hundreds of normal flights. The Isolation Forest memorizes the patterns. Then during a real flight, if something looks weird compared to normal, it raises a flag.

**How Isolation Forest works (no math needed):**
- It builds 100 random decision trees
- Each tree tries to "isolate" (separate) each data point from the others by randomly picking features and split values
- **Normal points** are surrounded by similar points → hard to isolate → need many splits
- **Anomalous points** are far from everything → easy to isolate → need few splits
- The "anomaly score" = how easy it was to isolate. More negative = more anomalous

**Concrete Example:**

Say your drone is flying normally and sending this telemetry every second:
```
altitude=50m, battery=80%, roll=2°, speed=15m/s, vibration=0.3g
```

The Isolation Forest was trained on thousands of rows like this. It knows this is "normal."

Now suddenly:
```
altitude=50m, battery=80%, roll=45°, speed=15m/s, vibration=2.1g
```

Roll jumped to 45° and vibration spiked. The IF says: "This point is easy to isolate from everything I've seen. Score = -0.72 (threshold was -0.50). ANOMALY!"

**Feature Engineering — What features does it use?**

For each of 22 raw sensor values (altitude, vx, vy, vz, voltage, current, battery%, roll, pitch, yaw, airspeed, groundspeed, climb_rate, throttle, rpm_1-4, cur_1-4, vibration_x/y/z), it creates 3 extra derived features:

| Derived Feature | What it captures | Example |
|---|---|---|
| `*_mean` (rolling 10-sample average) | "What's the recent baseline?" | voltage_mean = avg of last 10 voltage readings |
| `*_std` (rolling 10-sample std dev) | "How jumpy is this sensor?" | rpm_1_std = are motor RPMs stable or fluctuating? |
| `*_rate` (first derivative / diff) | "How fast is it changing?" | altitude_rate = is altitude dropping suddenly? |

So: **22 raw × 4 (raw + mean + std + rate) = 88 features per timestep** (the code says 56 because it was written before motor/vibration features were added to the constants — this is a bug, see review section).

**Are these features sufficient for industry standard?**

> [!WARNING]
> **Partially.** The raw features and rolling statistics are a solid foundation — this is exactly what papers like the RADD framework use. But there are gaps:
> - ❌ **No cross-sensor correlation features** — e.g., throttle-vs-climb (if throttle is high but climb is zero → engine failure). Industry systems compute these.
> - ❌ **No frequency-domain features** — FFT of vibration data catches bearing failures that time-domain features miss entirely.
> - ❌ **No GPS integrity features** — HDOP, satellite count, GPS-vs-IMU position disagreement.
> - ❌ **No motor symmetry features** — rpm_1 - rpm_3 (opposing motors should be similar on a quad).
> - The `MOTOR_FEATURES` and `VIBRATION_FEATURES` are defined but **never actually appear in real telemetry** from the MAVLink bridge — they'll always be zero.

---

### 2.2 LSTM Autoencoder (`ml_models/lstm_autoencoder.py`) — Layer 2

**What it is in plain English:**  
While Isolation Forest looks at one moment in time, the LSTM Autoencoder looks at *sequences* — the last 30 seconds of data. It asks: "Does this sequence of events *over time* look normal?"

**How an Autoencoder works (no math):**

Think of it like a game of telephone:
1. **Encoder:** Compresses the last 30 timesteps of 56 sensor values into a tiny "summary" (16 numbers). Like summarizing a paragraph into one sentence.
2. **Decoder:** Tries to reconstruct the original 30 timesteps from just that summary.
3. If the reconstruction is close to the original → the model "understood" the pattern → **Normal**.
4. If the reconstruction is way off → the model has never seen this pattern → **Anomaly**.

The "reconstruction error" is just: how different is the output from the input? (measured by Mean Squared Error — average of squared differences).

**Why LSTM specifically?**

LSTM (Long Short-Term Memory) is a type of neural network designed for sequences. Unlike a regular neural network, it has "memory cells" that can remember things from earlier in the sequence. This is critical for catching anomalies like:
- A slow battery drain that only becomes dangerous over 30 seconds
- Vibration that gradually increases (bearing degradation)
- GPS drift that accumulates over time

**The Architecture:**

```
Input: 30 timesteps × 56 features = matrix of 1,680 numbers
  ↓
Encoder LSTM (56→64 hidden units) — reads the sequence, produces a hidden state
  ↓
Linear layer (64→16) — compresses to latent space (the "summary")
  ↓
Linear layer (16→64) — expands back
  ↓
Decoder LSTM (64→64) — reconstructs the sequence
  ↓
Output Linear (64→56) — maps back to feature space
  ↓
Output: 30 timesteps × 56 features (reconstruction)

Reconstruction Error = mean((input - output)²)
If error > threshold → ANOMALY
```

**Threshold = mean + 3σ** — trained on normal data, so anything with error more than 3 standard deviations above the average is flagged.

**ONNX Export:** The model is exported to ONNX format for edge deployment. ONNX is a universal model format that runs without PyTorch — lighter, faster, works on embedded devices.

---

### 2.3 Domain Classifier (`ml_models/domain_classifier.py`) — Layer 3

**What it is in plain English:**  
After Layer 1 or 2 says "something is wrong," the Domain Classifier answers "what KIND of thing is wrong?" Is it a motor problem? Battery problem? GPS problem?

**How it works:**  
It's a Random Forest Classifier (supervised, unlike the unsupervised Isolation Forest). It was trained on labeled examples: "when the data looked like THIS, it was a propulsion fault. When it looked like THAT, it was a power fault."

**The Domains:**

| Domain | What it means |
|---|---|
| `propulsion` | Motor/ESC failure, blade damage |
| `power` | Battery degradation, voltage drop |
| `navigation` | GPS spoofing, IMU drift, compass interference |
| `dynamics` | Stall, aerodynamic instability, wind shear |
| `ew` | Electronic warfare — RF jamming, signal interference |
| `unknown` | Can't classify |

**Are these domains enough?**

> [!WARNING]
> **No. Missing critical domains for iDEX/defense:**
> - ❌ **Thermal** — motor/ESC overheating, battery thermal runaway
> - ❌ **Communication** — link quality degradation, NATS mesh failures
> - ❌ **Payload** — camera gimbal malfunction, payload release failures
> - ❌ **Environmental** — wind shear, rain/dust interference, icing
> - ❌ **Structural** — airframe stress, vibration-induced fatigue
> - Industry standard (Shield AI, Anduril) typically has 8-12 fault domains

---

## 3. Domains — Anomaly Pipeline

### 3.1 `_extract_features_for_timestamp` — Explained with Example

**What it does:** When Layer 1 (Isolation Forest) flags timestamp T=1234.5 as anomalous, we need to extract the sensor features at that exact moment so Layer 3 (Domain Classifier) can classify what type of fault it is.

**Step-by-step example:**

```python
# Say IF flagged an anomaly at timestamp 1234.5

# Step 1: Merge all telemetry streams into one table
# Input: {"positions": DataFrame, "battery": DataFrame, "attitude": DataFrame, ...}
# Each has different timestamps because sensors report at different rates:
#   positions: [1234.0, 1234.1, 1234.2, ..., 1234.9, 1235.0]
#   battery:   [1234.0, 1234.5, 1235.0]  (slower sensor)
# merge_asof aligns them by nearest timestamp → one row per position timestamp

# Step 2: Engineer features (add rolling mean, std, rate for each column)
# Now we have ~88 columns

# Step 3: Find the row closest to timestamp 1234.5
# idx = row where abs(timestamp - 1234.5) is smallest

# Step 4: Extract only the features the Domain Classifier knows about
# The classifier was trained on specific feature names
# We build a vector matching those names, filling zeros for missing ones

# Output: numpy array like [50.0, 0.1, -0.3, 11.8, 0.02, ...]
# This gets passed to domain_classifier.classify(features)
```

### 3.2 The `run()` function in `anomaly.py` — What it actually does

```
run(telemetry) flow:

1. IF model missing? → return [] (nothing to do)

2. Run Layer 1 (Isolation Forest):
   layer1_events = self.if_model.detect(telemetry)
   → Returns list of {"timestamp": 1234.5, "severity": "HIGH", "score": -0.72, ...}
   → If empty, return [] (no anomalies found)

3. For each Layer 1 event:
   a. Layer 2 (LSTM): Should confirm/deny the anomaly
      → BUT: Currently just sets confirmed=True always (broken — see review)
   
   b. Layer 3 (Domain Classifier): Classifies the fault type
      → Extracts features at the anomaly timestamp
      → Calls domain_model.classify(features)
      → Gets back {"domain": "propulsion", "confidence": 0.85}
      → If confidence > 0.6, overrides the recommendation with domain-specific advice

4. Builds AnomalyEvent objects and returns them
```

> **Layer 2 Integration:** Layer 2 (LSTM) now actively runs inference on the 30-step sequence leading up to an anomaly flagged by Layer 1, providing a robust temporal confirmation step.

---

## 4. Perception — Computer Vision

### `perception/detector.py` — YOLO Object Detection

**What YOLO does (plain English):**  
YOLO (You Only Look Once) is a neural network that looks at a camera image and draws boxes around objects it recognizes, telling you what each object is and how confident it is.

**How the code works:**

```
Camera Frame (640×480 RGB image)
  ↓
_preprocess(): Resize to 640×640 with letterboxing (gray padding),
               convert BGR→RGB, normalize pixel values to 0-1
  ↓
ONNX Runtime: Run the YOLO model (returns raw predictions)
  ↓
_postprocess(): 
  1. Filter predictions by confidence (> 0.5)
  2. Convert bounding box format (center-x,y,w,h → x1,y1,x2,y2)
  3. Undo the letterboxing transformation
  4. Apply NMS (Non-Maximum Suppression — removes duplicate overlapping boxes)
  ↓
List of Detection objects: [{bbox, class_name, confidence, frame_id}, ...]
```

**The Sentinel Classes:**

| ID | Class | What it means |
|---|---|---|
| 0 | `hostile_uas` | Enemy drone |
| 1 | `vehicle` | Ground vehicle (car, truck, tank) |
| 2 | `person` | Human |
| 3 | `infrastructure` | Building, tower, bridge |
| 4 | `unknown` | Unclassified object |

**Are these classes sufficient?**

> [!WARNING]
> **No. Major gaps for defense/surveillance:**
> - ❌ **friendly_uas** — Must distinguish friendly vs hostile drones. Currently ANY drone = hostile.
> - ❌ **weapon/ordnance** — Critical for threat assessment
> - ❌ **boat/maritime** — If operating in coastal environments
> - ❌ **animal/bird** — Huge source of false positives (birds misclassified as drones)
> - ❌ **No sub-categories** — "vehicle" lumps civilian cars with military vehicles
> - Industry standard (military ISR): typically 15-30+ classes with IFF (Identification Friend or Foe)

---

## 5. Tracking

### `tracking/tracker.py` — Multi-Object Tracker

**What tracking does (plain English):**  
YOLO runs on each frame independently — it doesn't know that the drone it detected in frame 1 is the same drone in frame 2. The tracker's job is to maintain **identity** across frames: "Object #7 is the same hostile_uas I saw 30 frames ago, and it's moving northeast at 5 pixels/frame."

**How it works (ByteTrack-inspired):**

```
Frame N arrives with new YOLO detections
  ↓
1. PREDICT: Move each existing track's bounding box forward
   based on its velocity (simple linear prediction)
   "Track #3 was at (100,200) moving right at 5px/frame → predict it's at (105,200)"
  ↓
2. MATCH: Compare predicted track boxes with new detection boxes using IoU
   IoU = Intersection over Union (how much do two boxes overlap?)
   
   Example:
   Track #3 predicted box: (103, 198, 153, 248)
   Detection box:          (107, 200, 157, 250)
   Overlap area / Total area = 0.75 → Good match! (threshold = 0.3)
   
   Uses the Hungarian Algorithm (`scipy.optimize.linear_sum_assignment`) for globally optimal matching.
  ↓
3. UPDATE matched tracks: Update box, velocity (smoothed), hit count
   Velocity smoothing: new_vel = 0.4 * old_vel + 0.6 * measured_vel
   After 3 consecutive matches → track becomes "confirmed"
  ↓
4. CREATE new tracks for unmatched detections (confidence > 0.6)
   Start as "tentative" until confirmed
  ↓
5. DELETE tracks not seen for 30 frames
```

**IoU Example (visual):**
```
Box A:          Box B:          Overlap:
┌─────────┐                    
│         │    ┌─────────┐     
│    ┌────┼────┼────┐    │     ┌────┐
│    │XXXX│    │    │    │     │XXXX│ ← Intersection
└────┼────┘    │    │    │     └────┘
     │         │    │    │     
     └─────────┘    │    │     
                    └────┘     
IoU = Area(XXXX) / Area(A + B - XXXX)
```

### `tracking/visual_servo.py` — Visual Servoing Controller

**What it does (plain English):**  
Once you're tracking a target, how do you fly the drone to keep it centered in the camera? Visual servoing generates velocity commands (move forward, turn left, go up) to keep the target in the middle of the frame.

**How it works — PD Controller:**

A PD controller is like a thermostat with two parts:
- **P (Proportional):** "The target is 30% to the right of center → turn right proportionally"
- **D (Derivative):** "The error is getting bigger → turn harder" / "The error is shrinking → ease off"

```
Target is at pixel (400, 300) in a 640×480 frame
Center is (320, 240)

error_x = (400-320)/320 = +0.25  → target is 25% right of center → yaw right
error_y = (300-240)/240 = +0.25  → target is 25% below center → descend
error_z = desired_size - actual_size → target too small → move forward

Commands:
  yaw_rate = kp * 0.25 + kd * (change in error_x)
  vz = -(kp * 0.25 + kd * (change in error_y))  
  vx = only if target is roughly centered (|error| < 0.3)
  vy = 0 (no strafing — "point and shoot" style)
```

---

## 6. Threat Assessment

### `threat/behavior_analyzer.py` — What is the target doing?

**Purpose:** Given a tracked object's position history (last 30 frames), classify its *behavior pattern* to understand intent.

**How it works:**

It computes two key metrics from the trajectory:
1. **Displacement** = straight-line distance from start point to end point
2. **Path length** = total distance actually traveled (following the wiggly path)
3. **Meandering ratio** = path_length / displacement

```
Example trajectories:

TRANSIT (straight line):          LOITERING (circling):
Start ──────────────► End         Start ──╮  ╭──╮
displacement=100, path=105            │  │  │
meandering=1.05                       ╰──╯  ╰── (back near start)
→ NOT a threat                    displacement=15, path=200
                                  meandering=13.3
                                  → THREAT (surveillance)

APPROACHING (heading toward us):  ERRATIC (evasive maneuvers):
        ╔══Our Drone══╗               ╱╲  ╱╲
        ║  (center)   ║              ╱  ╲╱  ╲
Start───║─────►End    ║             ╱        ╲
        ╚═════════════╝            Start      End
dist_to_center shrinking          meandering=4.2, path=300
→ THREAT (approaching)            → THREAT (erratic)
```

**Classification rules:**

| Condition | Behavior | Threat? |
|---|---|---|
| displacement < 20, path > 50 | `loitering` | ✅ Yes |
| meandering > 3.0, path > 100 | `erratic` | ✅ Yes |
| meandering < 1.2, displacement > 100, getting closer to frame center | `approaching` | ✅ Yes |
| meandering < 1.2, displacement > 100, not approaching | `transit` | ❌ No |
| Everything else | `surveillance` | ✅ Yes |

### `threat/threat_scorer.py` — How dangerous is it?

**Purpose:** Combine class, proximity, and behavior into a single 0-1 threat score.

**Formula:**
```
threat_score = (base_score + proximity_modifier + behavior_modifier) × confidence_gate

Where:
  base_score = {hostile_uas: 0.8, vehicle: 0.5, person: 0.3, infrastructure: 0.1, unknown: 0.4}
  
  proximity_modifier = (bbox_area / frame_area × 5.0, capped at 1.0) × 0.3
    → Bigger bounding box = object is closer = more threatening
    → Max contribution: 0.3
  
  behavior_modifier = {approaching: 0.3, erratic: 0.2, loitering: 0.15, other: 0.0}
  
  confidence_gate = min(1.0, hits/10) × detection_confidence
    → Penalizes tracks we haven't seen many times yet
```

**Example:**
```
hostile_uas, detected 15 times, confidence 0.9, bbox fills 4% of frame, approaching

base = 0.8
proximity = min(1.0, 0.04 × 5.0) × 0.3 = 0.2 × 0.3 = 0.06
behavior = 0.3 (approaching)
confidence_gate = min(1.0, 15/10) × 0.9 = 1.0 × 0.9 = 0.9

raw = 0.8 + 0.06 + 0.3 = 1.16
final = min(1.0, 1.16 × 0.9) = min(1.0, 1.044) = 1.0

→ Priority: CRITICAL, Action: INTERCEPT
```

**Priority thresholds:**

| Score | Priority | Action |
|---|---|---|
| ≥ 0.8 | Critical | Intercept (if hostile_uas) or Evade |
| ≥ 0.6 | High | Track |
| ≥ 0.4 | Medium | Track |
| < 0.4 | Low | Monitor |

---

## 7. Autonomy — Reaction Rules

### `autonomy/reaction_rules.py`

**Is it "dumb hardcoding"?**

**Yes AND no.** It's *intentionally* hardcoded — and that's actually correct for safety-critical rules. Here's why:

In aerospace/defense, you have two categories of decisions:
1. **Deterministic safety rules** — MUST be hardcoded. If a motor fails, you ALWAYS emergency land. No ML model should be able to override this. This is FAA/military doctrine.
2. **Tactical decisions** — CAN be learned/adaptive.

The `ReactionEngine` is category 1. The rules are:

| Trigger | Action | Tier | Why hardcoded? |
|---|---|---|---|
| collision_imminent | emergency_stop | 1 | Can't let ML debate whether to stop |
| gps_spoofing_detected | switch_to_vio_nav | 1 | Immediate navigation fallback |
| rf_jamming_detected | execute_loss_of_link | 1 | Standard military procedure |
| motor_failure | emergency_land | 1 | Physics — can't fly with dead motor |
| low_battery_critical | rtl | 1 | Will fall from sky otherwise |
| hostile_uas_approaching | evasive_maneuver | 2 | Tactical but time-critical |
| target_acquired | begin_tracking | 3 | Tactical |

**What's ACTUALLY wrong with it** is not that it's hardcoded, but that:
- The mapping from anomaly domains to rule triggers (lines 42-53) is too simplistic — a navigation anomaly isn't always GPS spoofing
- There's no concept of rule chaining or escalation
- No hysteresis (debouncing) — a flickering sensor could trigger/untrigger rapidly
- Missing many rules that should exist (geofence breach, airspace violation, low fuel, comms lost)

---

## 8. Sidecar — The Orchestrator

`sidecar.py` ties everything together. It:
1. Connects to NATS mesh
2. Subscribes to `sentinel.telemetry.{drone_id}.>` and `sentinel.telemetry.{drone_id}.camera`
3. Buffers telemetry into DataFrames and buffers camera JPEG frames
4. Every 2 seconds, runs the anomaly pipeline on the telemetry buffer
5. At ~10 FPS, runs the YOLO CV perception pipeline on the camera frame
6. If anomalies or threats are found, runs the reaction engine
7. Publishes alerts and commands back to NATS

---

## 9. Code Quality Review

### ✅ CRITICAL Issues (Resolved)

**1. LSTM Layer 2 Dead Code Fixed:** The LSTM Autoencoder is now fully integrated and executes inference correctly in `anomaly.py`.

**2. Bounding Box Math Fixed:** The YOLO bounding box coordinate conversion math in `detector.py` has been patched to correctly compute `x2, y2`.

**3. Missing import in behavior_analyzer.py** (line 16)
```python
self.track_histories: Dict[int, List[Tuple[float, float]]] = {}
```
`Tuple` is used in the type hint but never imported. `from typing import List, Dict, Any` is there but `Tuple` is missing. This will crash on Python 3.8 and cause type-checking failures.

**4. Feature count mismatch** (`isolation_forest.py` vs `lstm_autoencoder.py`)
- IF defines `MOTOR_FEATURES` (8) + `VIBRATION_FEATURES` (3) = 11 extra raw features
- LSTM defaults to `n_features=56` (the old count without motor/vibration)
- If IF trains with motor+vibration features, the feature count will be ~88, but LSTM expects 56
- These models can't work together as Layer 1 → Layer 2 without matching feature spaces

### 🟠 Major Issues

**5. `has_data` check requires ALL streams** (`sidecar.py` line 177)
```python
has_data = all(not df.empty for df in self.telemetry_history.values())
```
Anomaly detection won't run until ALL 6 telemetry streams (positions, battery, attitude, hud, motors, vibration) have data. Motors and vibration may NEVER arrive from some autopilots. The pipeline will never execute.

**6. Domain classification recommendations are hardcoded strings** (`anomaly.py` lines 133-142)
Same problem as reaction_rules but worse — these are in the ML pipeline. Domain-specific recommendations should be configurable or come from the reaction engine, not duplicated here.

**7. Hungarian Matching in tracker:** The tracker was upgraded from greedy matching to the Hungarian algorithm, resolving the O(n²) suboptimal assignment issue.

**8. Hardcoded frame center assumption** (`behavior_analyzer.py` line 97)
```python
center = np.array([320, 240])  # Assuming 640x480 frame
```
Frame size is hardcoded. If the camera is 1920×1080, all "approaching" calculations are wrong.

**9. Perception Loop Wired:** `sidecar.py` now includes a `_perception_loop` that decodes JPEG frames from NATS and runs YOLO inference and tracking.

### 🟡 Minor Issues

**10.** `reaction_rules.py` imports `from domains.anomaly import AnomalyEvent` — relative import will fail depending on how Python path is configured.

**11.** `threat_scorer.py` and `behavior_analyzer.py` import from `perception.detector` and `tracking.tracker` — these are sibling packages with no common parent on sys.path.

**12.** `domain_classifier.py` uses `class_weight="balanced"` which is good, but there's no train/test split — it reports training accuracy only, which is meaningless for a Random Forest (it will always be ~100%).

**13.** The Isolation Forest threshold learning (line 88-93) has a `pass` for the validation set path — it never actually optimizes the threshold against labeled data.

**14.** `telemetry_history` trimming in sidecar uses `pd.concat` on every single incoming message — this is extremely slow (creates a new DataFrame each time). Should use a deque or pre-allocated buffer.

**15.** No thread safety on `latest_telemetry_dict` (sidecar line 138) — read by reaction engine while written by NATS callback. Needs a lock.
