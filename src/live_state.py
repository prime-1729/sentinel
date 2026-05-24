"""Thread-safe store for live MAVLink telemetry consumed by the API."""

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
        "altitude": 0.0,
        "speed": 0.0,
        "battery": 0.0,
        "voltage": 0.0,
        "lat": None,
        "lon": None,
    },
    "anomalies": [],
    "mission_elapsed_seconds": 0,
}


def update_telemetry(
    *,
    altitude: float | None = None,
    speed: float | None = None,
    battery: float | None = None,
    voltage: float | None = None,
    lat: float | None = None,
    lon: float | None = None,
) -> None:
    with _lock:
        telem = _state["telemetry"]
        if altitude is not None:
            telem["altitude"] = altitude
        if speed is not None:
            telem["speed"] = speed
        if battery is not None:
            telem["battery"] = battery
        if voltage is not None:
            telem["voltage"] = voltage
        if lat is not None:
            telem["lat"] = lat
        if lon is not None:
            telem["lon"] = lon
        _state["updated_at"] = time.time()


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
        return {
            "connected": _state["connected"],
            "connection_error": _state["connection_error"],
            "updated_at": _state["updated_at"],
            "telemetry": dict(_state["telemetry"]),
            "anomalies": list(_state["anomalies"]),
            "mission_elapsed_seconds": _state["mission_elapsed_seconds"],
        }


def reset_anomalies() -> None:
    with _lock:
        _state["anomalies"] = []
