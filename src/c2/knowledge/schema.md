# SENTINEL Database Schema

The SENTINEL intelligence system stores drone telemetry and anomalies in a local SQLite database (`data/sentinel.db`). 

## Tables
- `missions`: Contains mission metadata (`mission_id`, `drone_id`, `start_time`, `end_time`, `status`).
- `positions`: Timestamps, `lat`, `lon`, `alt_metres`, `relative_alt` (altitude above home), and velocities (`vx`, `vy`, `vz` in m/s).
- `battery`: Timestamps, `voltage` (in volts), `current`, `remaining_pct` (0-100).
- `attitude`: Timestamps, `roll_deg`, `pitch_deg`, `yaw_deg` (all in degrees).
- `hud`: Timestamps, `airspeed`, `groundspeed`, `altitude`, `climb_rate`, `throttle_pct`.
- `anomaly_events`: Identified issues (`timestamp`, `event_type`, `severity`, `detail`, `recommendation`).

## Relationships
All telemetry tables link back to `missions` via the `mission_id` foreign key. Querying by `mission_id` is the standard way to retrieve data for a specific flight.
