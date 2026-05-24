# SENTINEL
Mission Intelligence System for Autonomous Drone Operations

## What SENTINEL Does
Connects to drone fleets, reads mission telemetry, detects anomalies,
and generates plain-language intelligence reports for operators.

---

## Project Structure
sentinel/
├── src/
│   ├── connect.py      # MAVLink connection and telemetry reading
│   ├── telemetry.py    # Live and log-file telemetry extraction
│   ├── anomaly.py      # Anomaly detection
│   ├── report.py       # Intelligence report generation (Ollama)
│   ├── monitor.py      # CLI live mission monitor
│   ├── live_feed.py    # Background MAVLink feed for the API
│   ├── live_state.py   # Shared live telemetry state
│   └── api.py          # FastAPI backend for the dashboard
├── drone-mission-dashboard/  # Next.js operator dashboard (https://v0.app/chat/drone-mission-dashboard-vcQCSDzmdrR)
├── data/               # Store drone log files here
├── tests/              # Tests
├── venv-sentinel/      # Python virtual environment
└── README.md

---

## Environment Setup
Run these once when setting up on a new machine.

### 1. Install system dependencies
```bash
sudo apt-get update
sudo apt-get install -y git python3-pip python3-dev python3-venv
sudo apt-get install -y gcc g++ make cmake
sudo apt-get install -y libtool libxml2-dev libxslt1-dev
sudo apt-get install -y python3-future python3-lxml
```

### 2. Clone and build ArduPilot (one time only)
```bash
cd ~/drone-projects
git clone https://github.com/ArduPilot/ardupilot.git
cd ardupilot
git submodule update --init --recursive
Tools/environment_install/install-prereqs-ubuntu.sh -y
. ~/.profile
./waf configure --board sitl
./waf copter
```

### 3. Set up SENTINEL Python environment (one time only)
```bash
cd ~/drone-projects/sentinel
python3 -m venv venv-sentinel
source venv-sentinel/bin/activate
pip install pymavlink pandas anthropic fastapi uvicorn python-multipart
```

---

## Every Day: Starting Everything

### Step 1: Start SITL (Terminal 1)
Open a terminal and run:
```bash
cd ~/drone-projects/ardupilot
. ~/.profile
cd ArduCopter
sim_vehicle.py -v ArduCopter --console --map
```

Wait until you see `STABILIZE>` prompt.
This terminal must stay open while you work.

### Step 2: Fly a test mission (in the SITL terminal)
Type these commands into the STABILIZE> prompt:
mode guided
arm throttle
takeoff 20

Wait for `height 20` to appear. Drone is now flying.
Leave it flying while you run SENTINEL.

### Step 3: Activate SENTINEL environment (Terminal 2)
Open a second terminal and run:
```bash
cd ~/drone-projects/sentinel
source venv-sentinel/bin/activate
```

You should see `(venv-sentinel)` in your prompt.
You are ready to run SENTINEL code.

---

## Running SENTINEL

### Connect to live drone
```bash
python3 src/connect.py
```

### Telemetry of live drone
```bash
python3 src/telemetry.py
```

### Detect anomaly in drone from telemetry data
```bash
python3 src/anomaly.py
```

### Analyze a log file (coming soon)
```bash
python3 src/parser.py data/mission.tlog
```

### Start the API
```bash
uvicorn src.api:app --reload --host 127.0.0.1 --port 8000
```

### Start the dashboard (Terminal 3)

**Requires Node.js 20.9+** (check with `node -v`). Ubuntu’s default `v18` will show
`EBADENGINE` warnings and `next dev` may fail — upgrade with [NodeSource](https://github.com/nodesource/distributions) or [nvm](https://github.com/nvm-sh/nvm) before continuing.

```bash
cd ~/drone-projects/sentinel/drone-mission-dashboard
cp .env.local.example .env.local   # first time only
```

**Package manager** — use one of these (first time only, then `dev`):

```bash
# Option A: pnpm (matches pnpm-lock.yaml) — enable via Node corepack
corepack enable
pnpm install
pnpm dev

# Option B: npm (if you already have npm, no pnpm needed)
npm install
npm run dev
```

If `corepack` is not found, install Node 20 LTS from https://nodejs.org or run
`sudo apt install npm` and use Option B.

**Upgrade Node 18 → 20 on Ubuntu (one-time):**
```bash
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt install -y nodejs
node -v   # should show v20.x
cd ~/drone-projects/sentinel/drone-mission-dashboard
rm -rf node_modules package-lock.json
npm install
npm run dev
```

Open http://localhost:3000

**Dashboard workflow**
1. Upload a `.tlog` file and click **ANALYZE** — calls `POST /analyze` (telemetry, anomalies, AI report).
2. With SITL flying, click **START LIVE** — calls `POST /monitor/start` and polls `GET /telemetry/live` every 1.5s.

Set `NEXT_PUBLIC_SENTINEL_API_URL` in `drone-mission-dashboard/.env.local` if the API is not on port 8000.

---

## MAVLink Connection Details
- SITL runs ArduPilot on your laptop
- MAVProxy sits in the middle and splits the connection
- MAVProxy **console/map uses UDP 14550** — do not point SENTINEL at that port
- SENTINEL listens on **UDP 14551** (`udpin:127.0.0.1:14551`)

After SITL starts, in the **MAVProxy** (`STABILIZE>`) terminal run **once per session**:
```text
output add 127.0.0.1:14551
```

```
SENTINEL (listens on 14551)
↕
MAVProxy (14550 = console, 14551 = SENTINEL feed)
↕
ArduPilot SITL
```

---

## Troubleshooting

### `sim_vehicle.py: command not found`
You need to reload your profile:
```bash
. ~/.profile
```

### `(venv-ardupilot)` appears instead of `(venv-sentinel)`
You are in the wrong environment. Run:
```bash
deactivate
cd ~/drone-projects/sentinel
source venv-sentinel/bin/activate
```

### SENTINEL says `waiting for heartbeat` and hangs
SITL is not running. Go to Terminal 1 and start it first.
SENTINEL cannot connect if the drone is not flying.

### Live monitor: `[Errno 13] Permission denied` or no telemetry
MAVProxy already owns port **14550**. In the SITL terminal run:
```text
output add 127.0.0.1:14551
```
Restart the API (`uvicorn`), click **START LIVE** again. See [MAVLINK.md](MAVLINK.md).

### `Arm: Battery 1 low voltage failsafe` (but battery shows 100%)
Capacity (%) and voltage are different checks. SITL often simulates a low pack
voltage while still reporting 100% remaining. In the **SITL terminal** (`STABILIZE>`), run:

```bash
param set SIM_BATT_VOLTAGE 12.6
param set BATT_LOW_VOLT 0
param set BATT_CRT_VOLT 0
param set ARMING_CHECK 0
param set DISARM_DELAY 0
mode guided
arm throttle
takeoff 20
```

`SIM_BATT_VOLTAGE` sets the simulated cell/pack voltage (try `16.8` for a 4S pack).
`BATT_LOW_VOLT 0` disables the low-voltage failsafe in simulation.
These params reset when SITL restarts — run them each session before arming.

### Takeoff fails immediately
The drone auto-disarmed. Type commands faster, or run:
```bash
param set ARMING_CHECK 0
mode guided
arm throttle
takeoff 20
```

### Drone arms but immediately disarms, takeoff fails
Run these params first, then arm:
```bash
param set DISARM_DELAY 0
param set ARMING_CHECK 0
mode guided
arm throttle
takeoff 20
```
These params reset every time SITL restarts so run them
each session before arming.


### Map window does not open
Harmless. SENTINEL works without the map.
The map is just for visual reference.

---

## Key Concepts

**ArduPilot**: The autopilot brain. Normally runs on drone hardware.
In SITL it runs on your laptop simulating a real drone.

**SITL**: Software In The Loop. Simulates drone hardware so you can
develop and test without a physical drone.

**MAVLink**: The communication protocol drones use. Like HTTP but
for drone telemetry and commands.

**MAVProxy**: Ground control station that also acts as a proxy.
Lets multiple programs connect to one drone simultaneously.

**pymavlink**: Python library that speaks MAVLink.
SENTINEL uses this to read drone data.

For a project-specific cheat sheet (commands, message types, parameters), see [MAVLINK.md](MAVLINK.md).

---

## What We Are Building Toward
SENTINEL addresses iDEX DISC Challenge 21:
"AI Enabled Multi Agent Module for UAS Functions"

Core pipeline:
1. Connect to drone fleet via MAVLink
2. Parse telemetry into structured data
3. Detect anomalies (BatteryStress, IdleDrift, NearMiss)
4. Generate intelligence reports via Claude API
5. Expose everything via FastAPI
6. Scale to multi-drone coordination
