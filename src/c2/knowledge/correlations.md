# SENTINEL Correlation Rules

The intelligence system cross-references telemetry streams to find complex operational patterns that isolated threshold detectors miss.

## Known Correlations
1. **signal_induced_deviation**: When `SignalDegraded` (low RSSI) happens at the same time as `IdleDrift`. This suggests the drone is losing its connection to the Ground Control Station and may be drifting in the wind due to a failsafe delay.
2. **stress_induced_imbalance**: When `MotorImbalance` happens simultaneously with `LowBattery` or high current draw. Indicates the propulsion system is struggling, possibly due to a failing motor drawing excessive amps.
3. **weather_induced_drift**: When `MotorImbalance` (working hard to stabilize) correlates with `IdleDrift` and `ExtremeAttitude`. This is a strong indicator of high wind/turbulence overpowering the drone.
4. **vortex_ring_state**: When `RapidDescent` correlates with `ExtremeAttitude` (wobbling). Indicates the drone is descending into its own prop wash, causing aerodynamic instability.
