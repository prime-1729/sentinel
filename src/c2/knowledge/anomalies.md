# SENTINEL Anomaly Definitions

The SENTINEL system runs ML-based detectors over telemetry streams to identify operational anomalies.

## Recognized Anomalies
1. **LowBattery**: Triggered when `remaining_pct` drops below 20% (MEDIUM) or 10% (CRITICAL), or voltage drops below 10.5V.
2. **IdleDrift**: Occurs when the drone moves significantly (groundspeed > 2m/s) while throttle is low (< 10%). Indicates wind drift or poor position hold.
3. **RapidDescent**: Descent rate exceeds 3 m/s (climb_rate < -3.0). Can cause vortex ring state (VRS) or crashes.
4. **ExtremeAttitude**: Roll or pitch exceeds 45 degrees. Indicates aggressive maneuvering or loss of stability.
5. **GPSGlitch**: EPH (horizontal precision) > 2.5m or rapid jumps in position without matching velocity.
6. **MotorImbalance**: One ESC RPM/current differs significantly from the average (> 25% deviation). Indicates hardware wear or extreme wind compensation.
7. **SignalDegraded**: Radio RSSI drops below 40% (MEDIUM) or 20% (CRITICAL).

## Severity Levels
- **INFO**: Minor observations
- **MEDIUM**: Issues that degrade performance but don't threaten the asset
- **CRITICAL**: Issues requiring immediate operator intervention or RTB (Return to Base)
