# SITL — Software In The Loop Reference

A living cheat sheet for ArduPilot SITL. Commands, explanations, and notes
accumulated while building and testing SENTINEL.

> **Add new entries here as you use new commands.**  
> Mark anything you're unsure about with a `?` and fill it in later.

---

## What is SITL? (60 seconds)

**SITL (Software In The Loop)** runs the real ArduPilot firmware on your laptop
— but instead of talking to real motors and sensors, it talks to a **physics
simulation** that fakes the drone's behaviour.

- No real hardware needed — the sim provides fake GPS, IMU, battery, and motors.
- The simulated drone obeys real physics (gravity, drag, wind) so anomaly
  detection code trained on sim data transfers to real flights.
- `sim_vehicle.py` is the script that starts everything.

**How the pieces connect:**

```
sim_vehicle.py (ArduPilot firmware + physics sim)
       ↕
MAVProxy (console you type into: STABILIZE> or GUIDED>)
       ↕  forwards MAVLink
SENTINEL (reads telemetry on port 14551)
```

**Practical rule:** MAVProxy's built-in console/map occupies port **14550**.
SENTINEL listens on **14551**. Once per session, run this in the MAVProxy
terminal to route telemetry to SENTINEL:

```text
output add 127.0.0.1:14551
```

---

## Starting SITL

```bash
cd ~/ardupilot/ArduCopter
sim_vehicle.py -v ArduCopter --console --map
```

| Flag | What it does |
|------|--------------|
| `-v ArduCopter` | Use the quadcopter firmware (as opposed to Plane, Rover, etc.) |
| `--console` | Opens a text console window showing live telemetry values |
| `--map` | Opens a map window so you can watch the drone fly |

Once you see `STABILIZE>` in the terminal, SITL is running and ready for commands.

---

## Pre-flight Setup Block

Run this **every new SITL session** before arming. SITL starts with defaults
that block arming (low voltage, GPS checks). These params disable those guards
so you can focus on testing mission logic.

```text
param set SIM_BATT_VOLTAGE 12.6
param set BATT_LOW_VOLT 0
param set BATT_CRT_VOLT 0
param set ARMING_CHECK 0      # if this fails, try: param set ARMING_CHECK_ENABLED 0
param set DISARM_DELAY 0
```

| Command | What it does | Why we need it |
|---------|--------------|----------------|
| `param set SIM_BATT_VOLTAGE 12.6` | Sets simulated battery to 12.6 V (full 3S LiPo) | SITL defaults to low voltage → arms fail with "low voltage failsafe" |
| `param set BATT_LOW_VOLT 0` | Disables the low-voltage arming threshold | Value of `0` = threshold off; otherwise ArduPilot blocks arming below ~10.5 V |
| `param set BATT_CRT_VOLT 0` | Disables critical-voltage threshold | Same logic as above but for the stricter "critical" tier |
| `param set ARMING_CHECK 0` | Skips all pre-arm checks (GPS lock, compass, etc.) | Sim GPS can take time to lock; `0` bypasses the whole bitmask. **If `ARMING_CHECK` is not found**, use `param set ARMING_CHECK_ENABLED 0` instead — newer ArduPilot versions renamed it. |
| `param set DISARM_DELAY 0` | No auto-disarm when idle | Default is 10 s; drone disarms while you're still typing `takeoff` |

---

## Basic Flight Sequence

After the pre-flight block above:

```text
mode guided
arm throttle
takeoff 20
```

| Command | What it does |
|---------|--------------|
| `mode guided` | Switches to **GUIDED** mode — autopilot accepts coordinate/altitude commands from the ground station. Required before `takeoff`. |
| `arm throttle` | Arms the motors. `throttle` means "use the throttle channel to arm" — this is MAVProxy's way of sending the `COMPONENT_ARM_DISARM` command. |
| `takeoff 20` | Commands the drone to climb to **20 metres** above its home point and hold there. Wait until the console shows ~20 m before sending more commands. |
| `disarm` | Immediately stops motors and returns to safe state. Use to reset if something goes wrong. |
| `mode stabilize` | Returns to manual-style stabilised mode (the default when SITL starts). In this mode the autopilot only levels the drone; position/altitude are not held. |
| `mode loiter` | Holds current GPS position and altitude. Like GUIDED but without accepting new coordinate commands. |
| `mode rtl` | Return To Launch — drone flies back to home point and lands automatically. |
| `mode land` | Commands an immediate descent and landing at the current position. |
| `mode althold` | Holds altitude using barometer only; no GPS position hold. Useful when GPS is deliberately degraded for testing. |

---

## Navigation Commands (GUIDED mode only)

These tell the autopilot *where* and *how* to fly. The drone must be in GUIDED mode and airborne.

> **Important:** Many online examples show `guided alt`, `guided yaw`, etc. as
> subcommands. These **do not work** in MAVProxy. The correct commands are listed
> below — verified against actual SITL sessions.

### Fly to a GPS coordinate

```text
guided <lat> <lon> [alt]
```

**Example:** `guided -35.362 149.164 30`  
Flies to those GPS coordinates at 30 m altitude (above home).  
The lat/lon defaults used in SITL are near Canberra, Australia (ArduPilot's dev campus). Adjust to wherever your sim home is set.

### Change altitude only

```text
guided <altitude>
```

**Example:** `guided 45`  
Stays at the current GPS position but commands a new altitude of 45 m.
You can also specify the frame: `guided 45 AboveHome` or `guided 45 AGL`.

> **Note:** `guided alt 45` does NOT work — it returns a `Usage:` error.
> Just use `guided <number>` directly.

### Change heading (yaw)

```text
setyaw <degrees> <angular_speed> <mode>
```

- `degrees`: Target heading (0–360)
- `angular_speed`: Rotation speed in deg/sec
- `mode`: `0` = absolute heading, `1` = relative rotation

**Examples:**

| Command | What happens |
|---------|-------------|
| `setyaw 90 10 0` | Rotate to face East (90°) at 10 deg/sec |
| `setyaw 180 20 0` | Rotate to face South at 20 deg/sec |
| `setyaw 45 10 1` | Rotate 45° clockwise from current heading |

> **Note:** `guided yaw 90` does NOT work.

### Change maximum flight speed

```text
setspeed <speed_m/s>
```

**Example:** `setspeed 8`  
Sets the maximum horizontal speed the autopilot will use when flying to a target.

> **Note:** `guided speed 8` does NOT work.

### Velocity vector (fly in a direction continuously)

```text
velocity <vx> <vy> <vz>
```

- `vx`: Northward speed in m/s (negative = South)
- `vy`: Eastward speed in m/s (negative = West)
- `vz`: Vertical speed in m/s (**negative = climbing**, positive = descending — NED frame)

**Examples:**

| Command | What happens |
|---------|-------------|
| `velocity 5 0 0` | Flies North at 5 m/s |
| `velocity 0 5 0` | Flies East at 5 m/s |
| `velocity 3 3 0` | Flies North-East diagonally |
| `velocity 0 0 -2` | Climbs at 2 m/s |
| `velocity 0 0 3` | Descends at 3 m/s |
| `velocity 0 0 0` | Stops all motion, holds position |

> **Note:** `guided velocity 5 0 0` does NOT work. Use `velocity` directly.

### Position offset (move relative to current position)

```text
position <north_m> <east_m> <down_m>
```

Moves the drone by the specified offset from its current position (NED frame).

**Examples:**

| Command | What happens |
|---------|-------------|
| `position 50 0 0` | Move 50 m North |
| `position 0 50 0` | Move 50 m East |
| `position 0 0 -20` | Climb 20 m (negative down = up) |
| `position 50 50 -10` | Move NE and climb 10 m |

---

## Environmental Simulation (Wind & Turbulence)

Wind forces the drone to continuously tilt and vary motor RPMs to maintain
position. This is the best way to exercise the ML detector and motor imbalance
logic in SENTINEL without failing a real motor.

```text
param set SIM_WIND_SPD 15
param set SIM_WIND_DIR 270
param set SIM_WIND_TURB 1.5
```

| Command | What it does | Notes |
|---------|--------------|-------|
| `param set SIM_WIND_SPD <n>` | Wind speed in m/s | 0 = calm. 5 = light breeze. 15 = strong wind. 25+ = storm conditions that may cause instability. |
| `param set SIM_WIND_DIR <deg>` | Direction wind blows **from** (compass degrees) | 0 = North wind (blows South). 270 = West wind (blows East). |
| `param set SIM_WIND_TURB <n>` | Turbulence intensity (0–5 scale) | 0 = steady laminar wind. 1–2 = moderate gusts. 3+ = highly chaotic. Causes jerky attitude readings. |

**SENTINEL relevance:** Strong wind + turbulence causes RPM differential across
motors (motor imbalance), attitude oscillations (`ExtremeAttitude` detector),
and idle-drift events (`IdleDrift` detector) if the drone can't hold position.

---

## Failure Injection (Stress Testing SENTINEL Detectors)

These params let you simulate specific hardware/sensor failures to verify the
anomaly detectors in `src/anomaly.py` are triggering correctly.

### Battery Failures → tests `BatteryStress` and `LowBattery` detectors

| Command | What it does |
|---------|--------------|
| `param set SIM_BATT_VOLTAGE 10.8` | Forces the simulated voltage to drop suddenly. Values below 11.1 V (3.7 V/cell) for a 3S LiPo represent a nearly depleted pack. |
| `param set SIM_BATT_VOLTAGE 9.9` | Forces a critical-level voltage. At this level SENTINEL should flag `BatteryStress` and potentially `LowBattery`. |
| `param set SIM_BATT_CAPY 300` | Sets simulated battery capacity to 300 mAh (very small). The percentage drains rapidly during flight, quickly hitting the 20% and 10% thresholds. |

> Reset with: `param set SIM_BATT_VOLTAGE 12.6` and `param set SIM_BATT_CAPY 3500`

### GPS Failures → tests `GPSGlitch` detector

| Command | What it does |
|---------|--------------|
| `param set SIM_GPS_NUM 4` | Reduces simulated satellite count to 4. Below 6 sats, HDOP degrades significantly. |
| `param set SIM_GPS_HDOP 300` | Forces HDOP to 3.0 (SENTINEL's warning threshold is HDOP > 2.0 / eph > 200). |
| `param set SIM_GPS_HDOP 500` | Forces HDOP to 5.0 (SENTINEL's critical threshold is HDOP > 4.0 / eph > 400). |
| `param set SIM_GPS_DISABLE 1` | Completely cuts the GPS signal. ArduPilot will trigger GPS failsafe. |
| `param set SIM_GPS_GLITCH_X 25` | Injects a 25 m North position jump — simulates GPS spoofing/glitch. |
| `param set SIM_GPS_GLITCH_Y 25` | Same for East direction. |

> Reset with: `param set SIM_GPS_DISABLE 0`, `param set SIM_GPS_HDOP 100`

### Motor/ESC Failures → tests `MotorImbalance` detector

| Command | What it does |
|---------|--------------|
| `param set SIM_SERVO_FAIL 1` | Locks servo/motor channel 1 at its current output. The other 3 motors spike to compensate → large RPM imbalance. The drone will likely tip and crash if left long enough. |
| `param set SIM_SERVO_FAIL 2` | Same for motor 2. |
| `param set SIM_ENGINE_FAIL 1` | Cuts the simulated engine entirely. Results in rapid descent — good for testing `RapidDescent` detector. |

> Reset with: `param set SIM_SERVO_FAIL 0`, `param set SIM_ENGINE_FAIL 0`

### IMU / Sensor Failures

| Command | What it does |
|---------|--------------|
| `param set SIM_ACC_FAIL 1` | Fails the primary accelerometer. ArduPilot switches to backup if available; attitude estimation degrades. |
| `param set SIM_GYR_FAIL 1` | Fails the primary gyroscope. Dramatic attitude oscillations begin. Tests `ExtremeAttitude` detector. |
| `param set SIM_BARO_FAIL 1` | Fails the barometer. ArduPilot loses altitude reference and may descend unexpectedly. |

> Reset with: `param set SIM_ACC_FAIL 0`, `param set SIM_GYR_FAIL 0`, `param set SIM_BARO_FAIL 0`

---

## RC Stick Override (Manual Channel Control)

You can directly inject RC (remote control) channel values from the MAVProxy
terminal, as if moving physical sticks on a radio controller.

**PWM range:** `1000` (full low/left) → `1500` (neutral/centre) → `2000` (full high/right)

```text
rc <channel> <pwm_value>
```

| Channel | Controls | 1000 | 1500 | 2000 |
|---------|----------|------|------|------|
| `rc 1 <pwm>` | Roll (left/right tilt) | Full roll left | Level | Full roll right |
| `rc 2 <pwm>` | Pitch (forward/back tilt) | Full pitch forward | Level | Full pitch backward |
| `rc 3 <pwm>` | Throttle (altitude in manual modes) | Min throttle (descend/idle) | Mid throttle | Max throttle (climb) |
| `rc 4 <pwm>` | Yaw (rotation) | Full yaw left | No yaw | Full yaw right |
| `rc 5 <pwm>` | Flight mode switch (configurable) | — | — | — |

**Examples:**

```text
rc 1 1700       # Roll right moderately
rc 2 1300       # Pitch forward moderately
rc 4 1800       # Rotate clockwise (yaw right)
rc all 0        # Release all overrides — return to autopilot control
```

> **Warning:** RC overrides bypass the autopilot's position/altitude hold.
> In GUIDED mode the autopilot will fight against your RC inputs. Switch to
> STABILIZE mode first if you want raw stick control.

---

## Inspection & Monitoring Commands

Commands for reading state without changing anything.

| Command | What it does |
|---------|--------------|
| `param show <NAME>` | Prints the current value of a single parameter. E.g. `param show BATT_LOW_VOLT` |
| `param show SIM_*` | Lists all simulation-related parameters with current values. |
| `param show BATT_*` | Lists all battery-related parameters. |
| `status` | Prints general vehicle status: mode, armed state, battery, link quality. |
| `watch ATTITUDE` | Streams the ATTITUDE MAVLink message to the console in real time. Press `Ctrl+C` to stop. |
| `watch GLOBAL_POSITION_INT` | Streams live GPS position and altitude. |
| `watch BATTERY_STATUS` | Streams live battery readings (voltage, current, %). |
| `watch VFR_HUD` | Streams airspeed, groundspeed, altitude, climb rate, and throttle. |
| `wp list` | Lists any loaded waypoints (AUTO mission mode). |

---

## COMMAND_ACK — Reading the Autopilot's Replies

After you send a command (arm, takeoff, mode change), ArduPilot always replies
with a `COMMAND_ACK` message:

```text
Got COMMAND_ACK: DO_SET_MODE: ACCEPTED
Got COMMAND_ACK: COMPONENT_ARM_DISARM: FAILED
Got COMMAND_ACK: NAV_TAKEOFF: ACCEPTED
```

| Part | Meaning |
|------|---------|
| `DO_SET_MODE` | The "change flight mode" command |
| `COMPONENT_ARM_DISARM` | The "arm or disarm motors" command |
| `NAV_TAKEOFF` | The "take off to altitude" command |
| `ACCEPTED` | Command was accepted and is executing |
| `FAILED` | Command was rejected — read the `AP:` line below for the reason |

**Common failure reasons and fixes:**

| `AP:` message | Meaning | Fix |
|---------------|---------|-----|
| `Battery 1 low voltage failsafe` | Voltage too low to arm | `param set SIM_BATT_VOLTAGE 12.6` and `param set BATT_LOW_VOLT 0` |
| `PreArm: Need 3D Fix` | No GPS lock yet | Wait a moment, or `param set ARMING_CHECK 0` |
| `Not in GUIDED mode` | `takeoff` only works in GUIDED | `mode guided` first |
| `Already armed` | Tried to arm twice | Issue `disarm` first if you need to reset |

---

## Quick-Reference Troubleshooting

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| `waiting for heartbeat` (SENTINEL) | SITL not running or wrong port | Start `sim_vehicle.py`, then `output add 127.0.0.1:14551` |
| `COMPONENT_ARM_DISARM: FAILED` | Pre-arm check blocking | Run the pre-flight param block at the top |
| `NAV_TAKEOFF: FAILED` | Not armed or not in GUIDED | `mode guided` → `arm throttle` → `takeoff 20` |
| Drone won't hold position | Not enough GPS sats or in STABILIZE | Switch to `mode guided` or `mode loiter` |
| Altitude stuck at 0 (SENTINEL live) | Drone not airborne | Arm and takeoff in SITL first |
| SENTINEL connects but no data | `output add` not run | Run `output add 127.0.0.1:14551` in MAVProxy |

---

## Flight Mode Glossary

| Mode | What it does | When to use it |
|------|-------------|----------------|
| `STABILIZE` | Autopilot levels the drone; pilot controls roll/pitch/throttle/yaw directly | Default on startup. Raw stick testing. |
| `GUIDED` | Autopilot follows GCS commands (coordinates, altitude, velocity) | Standard test mode for SENTINEL |
| `LOITER` | Holds current GPS position and altitude autonomously | Hovering in place without issuing commands |
| `ALTHOLD` | Holds altitude via barometer; no GPS position hold | Testing when GPS is intentionally degraded |
| `RTL` | Return To Launch — flies back to home point and lands | Emergency recovery; end of mission |
| `LAND` | Descends and lands at current position | Immediate landing needed |
| `AUTO` | Executes a pre-loaded waypoint mission | Running scripted multi-waypoint missions |

---

## Changelog

Add a row here whenever you use something new.

| Date | Command / Topic | Notes |
|------|-----------------|-------|
| 2026-06-13 | Full command reference created | Initial doc from SITL learning session |
| | | |

---

## Further Reading

- [ArduPilot SITL docs](https://ardupilot.org/dev/docs/sitl-simulator-software-in-the-loop.html)
- [sim_vehicle.py options](https://ardupilot.org/dev/docs/using-sitl-for-ardupilot-testing.html)
- [ArduPilot flight modes](https://ardupilot.org/copter/docs/flight-modes.html)
- [MAVProxy docs](https://ardupilot.org/mavproxy/)
- [SIM_* parameter list](https://ardupilot.org/copter/docs/parameters.html) (search "SIM_")
