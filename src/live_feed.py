"""Background MAVLink reader for live dashboard telemetry."""

from __future__ import annotations

import math
import threading
import time
from datetime import datetime

import pandas as pd
from pymavlink import mavutil

from anomaly import (
    detect_attitude_anomaly,
    detect_battery_stress,
    detect_idle_drift,
)
import live_state

_monitor_thread: threading.Thread | None = None
_stop_event = threading.Event()
_alerted_keys: set[str] = set()


def _format_timestamp(ts: float) -> str:
    return datetime.fromtimestamp(ts).strftime("%H:%M:%S")


def _anomaly_to_dict(event, index: int) -> dict:
    return {
        "id": f"LIVE-{index:03d}",
        "timestamp": _format_timestamp(event.timestamp),
        "type": event.event_type,
        "severity": event.severity,
        "description": event.detail,
        "recommendation": event.recommendation,
    }


def _monitor_loop(connection_string: str, window_seconds: int) -> None:
    positions: list[dict] = []
    battery: list[dict] = []
    attitude: list[dict] = []
    hud: list[dict] = []
    mission_start = time.time()
    scan_timer = time.time()
    anomaly_counter = 0

    try:
        connection = mavutil.mavlink_connection(connection_string)
        connection.wait_heartbeat(timeout=10)
        live_state.set_connected(True)
    except Exception as exc:  # noqa: BLE001 — surface connection errors to API clients
        live_state.set_connected(
            False,
            f"No heartbeat from drone on {connection_string} ({exc}). "
            "Start SITL (sim_vehicle.py) and ensure the drone is armed.",
        )
        return

    while not _stop_event.is_set():
        msg = connection.recv_match(blocking=True, timeout=1)
        if msg is None:
            continue

        msg_type = msg.get_type()
        ts = time.time()
        live_state.set_mission_elapsed(int(ts - mission_start))

        if msg_type == "GLOBAL_POSITION_INT":
            alt = msg.relative_alt / 1000
            speed = math.sqrt((msg.vx / 100) ** 2 + (msg.vy / 100) ** 2)
            positions.append(
                {
                    "timestamp": ts,
                    "lat": msg.lat / 1e7,
                    "lon": msg.lon / 1e7,
                    "relative_alt": alt,
                }
            )
            live_state.update_telemetry(
                altitude=alt,
                speed=speed,
                lat=msg.lat / 1e7,
                lon=msg.lon / 1e7,
            )

        elif msg_type == "BATTERY_STATUS":
            voltage = msg.voltages[0] / 1000
            remaining = msg.battery_remaining
            battery.append(
                {
                    "timestamp": ts,
                    "voltage": voltage,
                    "current": msg.current_battery / 100,
                    "remaining_pct": remaining,
                }
            )
            live_state.update_telemetry(battery=float(remaining), voltage=voltage)

        elif msg_type == "ATTITUDE":
            attitude.append(
                {
                    "timestamp": ts,
                    "roll_deg": math.degrees(msg.roll),
                    "pitch_deg": math.degrees(msg.pitch),
                    "yaw_deg": math.degrees(msg.yaw),
                }
            )

        elif msg_type == "VFR_HUD":
            hud.append(
                {
                    "timestamp": ts,
                    "groundspeed": msg.groundspeed,
                    "throttle_pct": msg.throttle,
                }
            )
            live_state.update_telemetry(speed=msg.groundspeed)

        if time.time() - scan_timer >= window_seconds:
            scan_timer = time.time()

            if len(battery) > 1:
                for event in detect_battery_stress(pd.DataFrame(battery)):
                    key = f"{event.event_type}_{int(event.timestamp)}"
                    if key not in _alerted_keys:
                        _alerted_keys.add(key)
                        anomaly_counter += 1
                        live_state.add_anomaly(_anomaly_to_dict(event, anomaly_counter))

            if len(attitude) > 0:
                for event in detect_attitude_anomaly(pd.DataFrame(attitude)):
                    key = f"{event.event_type}_{int(event.timestamp)}"
                    if key not in _alerted_keys:
                        _alerted_keys.add(key)
                        anomaly_counter += 1
                        live_state.add_anomaly(_anomaly_to_dict(event, anomaly_counter))

            if len(hud) > 5 and len(positions) > 0:
                for event in detect_idle_drift(
                    pd.DataFrame(positions), pd.DataFrame(hud)
                ):
                    key = f"{event.event_type}_{int(event.timestamp)}"
                    if key not in _alerted_keys:
                        _alerted_keys.add(key)
                        anomaly_counter += 1
                        live_state.add_anomaly(_anomaly_to_dict(event, anomaly_counter))

            cutoff = time.time() - 60
            positions = [p for p in positions if p["timestamp"] > cutoff]
            battery = [b for b in battery if b["timestamp"] > cutoff]
            attitude = [a for a in attitude if a["timestamp"] > cutoff]
            hud = [h for h in hud if h["timestamp"] > cutoff]

    live_state.set_connected(False)


def is_running() -> bool:
    return _monitor_thread is not None and _monitor_thread.is_alive()


def start(connection_string: str = "udpin:127.0.0.1:14551", window_seconds: int = 10) -> bool:
    global _monitor_thread

    if is_running():
        return True

    _stop_event.clear()
    _alerted_keys.clear()
    live_state.reset_anomalies()
    live_state.set_connected(False, None)

    _monitor_thread = threading.Thread(
        target=_monitor_loop,
        args=(connection_string, window_seconds),
        daemon=True,
        name="sentinel-live-feed",
    )
    _monitor_thread.start()
    return True


def stop() -> None:
    _stop_event.set()
    if _monitor_thread is not None:
        _monitor_thread.join(timeout=2)
    live_state.set_connected(False)
