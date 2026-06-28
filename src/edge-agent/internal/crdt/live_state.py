"""Thread-safe store for live drone telemetry. Comprehensive state for drone self-awareness."""

from __future__ import annotations

import threading
import time
from typing import Any

_lock = threading.Lock()
_state: dict[str, Any] = {
    "connected": False,
    "connection_error": None,
    "updated_at": None,
    "telemetry": {
        # --- Position & Navigation ---
        "lat": None,
        "lon": None,
        "altitude": 0.0,           # relative altitude (m)
        "altitude_msl": 0.0,       # MSL altitude (m)
        "heading": 0.0,            # degrees
        "speed": 0.0,              # ground speed (m/s)
        "airspeed": 0.0,           # airspeed (m/s)
        "climb_rate": 0.0,         # vertical speed (m/s)
        "vx": 0.0, "vy": 0.0, "vz": 0.0,  # velocity components (m/s)

        # --- Attitude (IMU) ---
        "roll": 0.0,               # degrees
        "pitch": 0.0,              # degrees
        "yaw": 0.0,                # degrees
        "roll_rate": 0.0,          # deg/s (gyro)
        "pitch_rate": 0.0,         # deg/s
        "yaw_rate": 0.0,           # deg/s
        "accel_x": 0.0,            # m/s² (accelerometer)
        "accel_y": 0.0,
        "accel_z": 0.0,
        "vibration_x": 0.0,        # vibration levels
        "vibration_y": 0.0,
        "vibration_z": 0.0,

        # --- Power System ---
        "battery": 0.0,            # remaining %
        "voltage": 0.0,            # total voltage (V)
        "current": 0.0,            # current draw (A)
        "power_consumed": 0.0,     # mAh consumed

        # --- Propulsion (ESC per-motor) ---
        "motor_rpm": [0, 0, 0, 0],
        "motor_current": [0.0, 0.0, 0.0, 0.0],
        "motor_temperature": [0.0, 0.0, 0.0, 0.0],

        # --- GPS Quality ---
        "gps_fix_type": 0,         # 0=no fix, 3=3D fix, 4=DGPS, 5=RTK
        "satellites_visible": 0,
        "gps_hdop": 0.0,           # horizontal dilution of precision
        "gps_vdop": 0.0,           # vertical dilution of precision

        # --- Radio / Link ---
        "rssi": 0,                 # signal strength
        "remote_rssi": 0,
        "rx_errors": 0,
        "link_quality": 0.0,       # 0-100%

        # --- Flight Status ---
        "flight_mode": "",         # STABILIZE, GUIDED, AUTO, RTL, LAND, etc.
        "armed": False,
        "ekf_ok": False,           # EKF health
        "throttle_pct": 0,

        # --- Magnetometer ---
        "mag_x": 0.0, "mag_y": 0.0, "mag_z": 0.0,

        # --- Barometer ---
        "baro_pressure": 0.0,      # hPa
        "baro_temperature": 0.0,   # °C
        "baro_altitude": 0.0,      # barometric altitude (m)
    },
    "anomalies": [],
    "mission_elapsed_seconds": 0,
}


def _update_fields(updates: dict[str, Any]) -> None:
    with _lock:
        telem = _state["telemetry"]
        for k, v in updates.items():
            if v is not None and k in telem:
                telem[k] = v
        _state["updated_at"] = time.time()


def update_telemetry(**kwargs: Any) -> None:
    """Generic update for any telemetry fields."""
    _update_fields(kwargs)


def update_imu(**kwargs: Any) -> None:
    """Update IMU/Attitude fields."""
    _update_fields(kwargs)


def update_motors(**kwargs: Any) -> None:
    """Update ESC/motor fields."""
    _update_fields(kwargs)


def update_gps_quality(**kwargs: Any) -> None:
    """Update GPS quality metrics."""
    _update_fields(kwargs)


def update_radio(**kwargs: Any) -> None:
    """Update radio link metrics."""
    _update_fields(kwargs)


def update_flight_status(**kwargs: Any) -> None:
    """Update general flight status."""
    _update_fields(kwargs)


def set_connected(connected: bool, error: str | None = None) -> None:
    with _lock:
        _state["connected"] = connected
        _state["connection_error"] = error
        if connected:
            _state["connection_error"] = None


def set_mission_elapsed(seconds: int) -> None:
    with _lock:
        _state["mission_elapsed_seconds"] = seconds


def add_anomaly(anomaly: dict[str, Any]) -> None:
    with _lock:
        existing_ids = {a["id"] for a in _state["anomalies"]}
        if anomaly["id"] not in existing_ids:
            _state["anomalies"].insert(0, anomaly)
            _state["anomalies"] = _state["anomalies"][:50]


def snapshot() -> dict[str, Any]:
    with _lock:
        # Deepish copy
        telem_copy = dict(_state["telemetry"])
        telem_copy["motor_rpm"] = list(_state["telemetry"]["motor_rpm"])
        telem_copy["motor_current"] = list(_state["telemetry"]["motor_current"])
        telem_copy["motor_temperature"] = list(_state["telemetry"]["motor_temperature"])
        
        return {
            "connected": _state["connected"],
            "connection_error": _state["connection_error"],
            "updated_at": _state["updated_at"],
            "telemetry": telem_copy,
            "anomalies": list(_state["anomalies"]),
            "mission_elapsed_seconds": _state["mission_elapsed_seconds"],
        }


def reset_anomalies() -> None:
    with _lock:
        _state["anomalies"] = []
