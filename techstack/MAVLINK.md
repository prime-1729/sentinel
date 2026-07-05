# MAVLink reference for SENTINEL

A living cheat sheet for MAVLink, SITL, and the commands we actually use in this project.
Add new entries here whenever we use something new in a session.

---

## What is MAVLink? (30 seconds)

**MAVLink** is the language drones use to talk to ground stations and tools like SENTINEL.

- Not human text — small binary **messages** (packets).
- Each message has a **type** (e.g. position, battery) and **fields** (e.g. altitude, voltage).
- Programs send **commands** (arm, change mode, takeoff) and get **acks** (accepted / failed).

Think of it like REST for drones: many message types, sent over UDP/serial, constantly streaming.

---

## Our setup (who talks to whom)

```
SENTINEL (Python / dashboard API)
    ↕  udp:127.0.0.1:14550
MAVProxy (console + map + proxy)
    ↕
ArduPilot SITL (simulated autopilot)
    ↕
Simulated motors, GPS, battery, etc.
```

| Piece | Role |
|-------|------|
| **SITL** | Fake drone + autopilot on your laptop |
| **MAVProxy** | Middleman; you type commands at `STABILIZE>` |
| **SENTINEL** | Reads telemetry, does not fly the drone (yet) |
| **`.tlog` file** | Saved MAVLink traffic from a past flight |

**Connection string SENTINEL uses:**

```
udpin:127.0.0.1:14551
```

Meaning: listen for MAVLink on localhost port **14551**.

**Important:** MAVProxy’s console and map already use **14550**. A second program must
not bind to 14550 — that causes errors (including `Permission denied` on some setups).

**Once per SITL session**, in the MAVProxy terminal (`STABILIZE>`):

```text
output add 127.0.0.1:14551
```

That tells MAVProxy to forward telemetry to SENTINEL on port 14551.

---

## Two places you run commands

### 1. SITL terminal (`STABILIZE>`) — you fly the sim

Typed into the window started by `sim_vehicle.py`. These are **MAVProxy** commands (shortcuts that send MAVLink commands for you).

### 2. SENTINEL (Python) — you read data

SENTINEL uses **pymavlink** to connect and **listen** to messages. It does not replace the SITL terminal for arming/takeoff in our current workflow.

---

## SITL / MAVProxy commands we use

Run these at the `STABILIZE>` (or `GUIDED>`) prompt **after** SITL is up.

### Flight commands

| Command | What it does |
|---------|----------------|
| `mode guided` | Switch to **GUIDED** mode — autopilot accepts altitude/position commands from the ground station. Required before `takeoff` in sim. |
| `arm throttle` | **Arm** the motors (spin-up allowed). `throttle` means “arm using throttle stick semantics” in MAVProxy. |
| `takeoff 20` | Climb to **20 metres** above home (GUIDED takeoff). Wait until you see height ~20 m. |
| `disarm` | Stop motors / safe state (if you need to reset). |
| `mode stabilize` | Back to manual-style stabilised mode (common default when SITL starts). |

**Typical session sequence** (after battery/param fixes if needed):

```text
mode guided
arm throttle
takeoff 20
```

### Parameter commands (`param set`)

ArduPilot stores settings as **parameters**. `param set NAME VALUE` changes one setting (until SITL restarts, unless saved to a file).

| Command | Meaning | Why we use it in SITL |
|---------|---------|------------------------|
| `param set SIM_BATT_VOLTAGE 12.6` | Simulated battery voltage (volts) | Stops “low voltage” false alarms in the sim |
| `param set BATT_LOW_VOLT 0` | Low-voltage failsafe threshold; `0` = off | Don’t block arm on voltage in bench testing |
| `param set BATT_CRT_VOLT 0` | Critical voltage threshold; `0` = off | Same, for the stricter tier |
| `param set ARMING_CHECK 0` | Pre-arm check bitmask; `0` = skip checks | SITL often fails GPS/calibration checks we don’t care about for dev |
| `param set DISARM_DELAY 0` | Seconds before auto-disarm when idle | Stops the sim disarming before you finish typing `takeoff` |

**Example — full pre-flight block** (run each new SITL session if arm fails):

```text
param set SIM_BATT_VOLTAGE 12.6
param set BATT_LOW_VOLT 0
param set BATT_CRT_VOLT 0
param set ARMING_CHECK 0
param set DISARM_DELAY 0
mode guided
arm throttle
takeoff 20
```

### Useful inspection commands

| Command | What it does |
|---------|----------------|
| `param show BATT_LOW_VOLT` | Print current value of one parameter |
| `param show SIM_*` | List simulation-related parameters |
| `status` | General vehicle / link status (MAVProxy) |
| `output add 127.0.0.1:14551` | Forward MAVLink to SENTINEL (run once after SITL starts) |

---

## Replies you may see (COMMAND_ACK)

When you arm or takeoff, MAVProxy often prints lines like:

```text
Got COMMAND_ACK: DO_SET_MODE: ACCEPTED
Got COMMAND_ACK: COMPONENT_ARM_DISARM: FAILED
Got COMMAND_ACK: NAV_TAKEOFF: FAILED
```

| Part | Meaning |
|------|---------|
| `COMMAND_ACK` | Autopilot answered a command |
| `DO_SET_MODE` | “Change flight mode” |
| `COMPONENT_ARM_DISARM` | “Arm or disarm” |
| `NAV_TAKEOFF` | “Take off to altitude” |
| `ACCEPTED` | Command OK |
| `FAILED` | Command rejected — read the next `AP:` line for reason |

**Example we hit:**

```text
AP: Arm: Battery 1 low voltage failsafe
Flight battery 100 percent
```

| Message | Meaning |
|---------|---------|
| `Flight battery 100 percent` | State of charge looks fine |
| `Battery 1 low voltage failsafe` | **Voltage** too low for arming — fix with `SIM_BATT_VOLTAGE` / `BATT_LOW_VOLT` (see README troubleshooting) |

---

## MAVLink messages SENTINEL cares about

SENTINEL does not need every MAVLink message — only types that carry mission data. Defined in `src/telemetry.py`, `src/monitor.py`, `src/live_feed.py`.

| Message type | What it tells us | Fields we use |
|--------------|------------------|---------------|
| **GLOBAL_POSITION_INT** | GPS position + velocity | `lat`, `lon`, `alt`, `relative_alt`, `vx`, `vy`, `vz` |
| **BATTERY_STATUS** | Power state | `voltages[0]` → volts, `current_battery`, `battery_remaining` (%) |
| **ATTITUDE** | Orientation | `roll`, `pitch`, `yaw` (radians in MAVLink; we convert to degrees) |
| **VFR_HUD** | Pilot-style HUD | `groundspeed`, `airspeed`, `alt`, `climb`, `throttle` |
| **HEARTBEAT** | “I am alive” | Used only to confirm connection (`wait_heartbeat`) |

### How SENTINEL reads them (Python / pymavlink)

| Code | Meaning |
|------|---------|
| `mavutil.mavlink_connection('udp:127.0.0.1:14550')` | Open MAVLink link |
| `connection.wait_heartbeat()` | Block until first **HEARTBEAT** (proves link works) |
| `connection.recv_match(blocking=True, timeout=1)` | Wait up to 1 s for **any** next message |
| `msg.get_type()` | Message name, e.g. `'BATTERY_STATUS'` |
| `msg.lat / 1e7` | MAVLink often stores lat/lon as integers × 10⁷ |

### Units (easy to get wrong)

| Field | Raw | We convert to |
|-------|-----|----------------|
| Latitude / longitude | degrees × 1e7 | degrees (`/ 1e7`) |
| Altitude | millimetres | metres (`/ 1000`) |
| Velocity vx, vy, vz | cm/s | m/s (`/ 100`) |
| Voltage | millivolts | volts (`/ 1000`) |

---

## Log files (`.tlog`)

| Item | Detail |
|------|--------|
| **Extension** | `.tlog` |
| **Contents** | Timestamped MAVLink messages from a flight or sim session |
| **SENTINEL use** | Upload in dashboard → `POST /analyze` replays messages via `extract_telemetry_from_file()` |
| **Also works** | `.bin` (ArduPilot dataflash) per API, but we mostly use `.tlog` in docs |

Reading a log is the same as live: loop `recv_match()` until no more messages, filter by type.

---

## Flight modes (short glossary)

| Mode | When we use it |
|------|----------------|
| **STABILIZE** | Default when SITL starts; pilot-style control |
| **GUIDED** | We switch here before `takeoff` — autopilot follows GCS commands |

Other modes (LOITER, RTL, LAND, AUTO) exist but are not in our default workflow yet.

---

## SENTINEL API ↔ MAVLink

| API endpoint | MAVLink side |
|--------------|----------------|
| `POST /monitor/start` | Background thread connects to `udp:127.0.0.1:14550`, same messages as `monitor.py` |
| `GET /telemetry/live` | Latest snapshot from that thread (not a separate MAVLink message type) |
| `POST /analyze` | Reads **file**, no live link |

---

## Quick troubleshooting ↔ MAVLink

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| `waiting for heartbeat` | SITL not running or wrong port | Start `sim_vehicle.py`; check `14550` |
| `COMPONENT_ARM_DISARM: FAILED` | Pre-arm check (battery, GPS, etc.) | `param set` block above |
| `NAV_TAKEOFF: FAILED` | Not armed or not GUIDED | `mode guided` → `arm throttle` → `takeoff` |
| SENTINEL connects but altitude 0 | Drone on ground / disarmed | Arm and takeoff in SITL first for live demo |
| 100% battery but won’t arm | Voltage failsafe vs % | `SIM_BATT_VOLTAGE`, `BATT_LOW_VOLT 0` |
| `[Errno 13] Permission denied` on LIVE | Port 14550 in use by MAVProxy | `output add 127.0.0.1:14551`; SENTINEL uses 14551 |

---

## Changelog (commands & messages we’ve used)

| Date | Added |
|------|--------|
| 2026-05-24 | Initial doc: connection string, guided/arm/takeoff, battery/arm params, four telemetry message types, COMMAND_ACK notes, `.tlog` |
| 2026-05-24 | SENTINEL port 14551 + `output add`; avoid sharing 14550 with MAVProxy |

*When you use a new command or message in the project, add a row to the changelog and a line in the tables above.*

---

## Further reading

- [ArduPilot MAVLink overview](https://ardupilot.org/dev/docs/mavlink-basics.html)
- [ArduPilot SITL](https://ardupilot.org/dev/docs/sitl-simulator-software-in-the-loop.html)
- [Battery failsafe params](https://ardupilot.org/copter/docs/failsafe-battery.html)
- [pymavlink](https://mavlink.io/en/mavgen_python/)
