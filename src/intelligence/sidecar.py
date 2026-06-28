import threading
import time
import logging
import asyncio
import json
import pandas as pd
from typing import Dict, Any

import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), "..", "edge-agent", "internal", "crdt"))
try:
    import live_state
except ImportError:
    live_state = None

from domains.anomaly import run_all_detectors

try:
    import nats
    from nats.errors import ConnectionClosedError, TimeoutError
except ImportError:
    print("Warning: nats-py is required for sidecar. Please install it.")
    nats = None

logger = logging.getLogger("sentinel.intelligence.sidecar")

_stop_event = threading.Event()
_monitor_thread = None
_nats_loop = None

_telemetry_history: Dict[str, pd.DataFrame] = {
    "positions": pd.DataFrame(),
    "battery": pd.DataFrame(),
    "attitude": pd.DataFrame(),
    "hud": pd.DataFrame(),
    "motors": pd.DataFrame(),
    "vibration": pd.DataFrame()
}
_max_history_seconds = 60
_history_lock = threading.Lock()


async def _anomaly_detection_loop(nc):
    """Periodically run anomaly detectors on the buffered telemetry."""
    detect_interval = 5.0
    while not _stop_event.is_set():
        await asyncio.sleep(detect_interval)
        
        with _history_lock:
            has_data = all(not df.empty for df in _telemetry_history.values())
            if not has_data:
                continue
                
            # Copy history to avoid blocking the NATS subscriber during detection
            history_copy = {k: v.copy() for k, v in _telemetry_history.items()}
            
        anomalies = run_all_detectors(history_copy)
        if anomalies:
            logger.warning(f"Detected {len(anomalies)} anomalies. Publishing to NATS...")
            for a in anomalies:
                alert_payload = {
                    "id": f"{a.event_type}_{a.timestamp}",
                    "timestamp": a.timestamp,
                    "type": a.event_type,
                    "severity": a.severity,
                    "detail": a.detail,
                    "recommendation": a.recommendation
                }
                
                # Publish to NATS mesh
                if nc and nc.is_connected:
                    await nc.publish("sentinel.threats.alert", json.dumps(alert_payload).encode())
                
                # Also update local dashboard state
                if live_state:
                    live_state.add_anomaly(alert_payload)


async def _telemetry_handler(msg):
    """Process incoming NATS telemetry and buffer it."""
    subject = msg.subject
    try:
        data = json.loads(msg.data.decode())
    except json.JSONDecodeError:
        return

    current_time = time.time()
    new_row = {"timestamp": current_time}

    with _history_lock:
        if "position" in subject or "odom" in subject:
            new_pos = {**new_row, "lat": data.get("lat", 0), "lon": data.get("lon", 0), 
                       "relative_alt": data.get("relative_alt", data.get("z", 0)), 
                       "vx": data.get("vx", 0), "vy": data.get("vy", 0), "vz": data.get("vz", 0)}
            _telemetry_history["positions"] = pd.concat([_telemetry_history["positions"], pd.DataFrame([new_pos])], ignore_index=True)
            if live_state: live_state.update_telemetry(lat=new_pos["lat"], lon=new_pos["lon"], altitude=new_pos["relative_alt"], vx=new_pos["vx"], vy=new_pos["vy"], vz=new_pos["vz"])

        elif "battery" in subject:
            new_bat = {**new_row, "voltage": data.get("voltage", 0), "current": data.get("current", 0), "remaining_pct": data.get("remaining_pct", 0)}
            _telemetry_history["battery"] = pd.concat([_telemetry_history["battery"], pd.DataFrame([new_bat])], ignore_index=True)
            if live_state: live_state.update_telemetry(voltage=new_bat["voltage"], current=new_bat["current"], battery=new_bat["remaining_pct"])
            
        elif "attitude" in subject:
            new_att = {**new_row, "roll_deg": data.get("roll_deg", 0), "pitch_deg": data.get("pitch_deg", 0), "yaw_deg": data.get("yaw_deg", 0)}
            _telemetry_history["attitude"] = pd.concat([_telemetry_history["attitude"], pd.DataFrame([new_att])], ignore_index=True)
            if live_state: live_state.update_imu(roll=new_att["roll_deg"], pitch=new_att["pitch_deg"], yaw=new_att["yaw_deg"])
            
        elif "hud" in subject:
            new_hud = {**new_row, "airspeed": data.get("airspeed", 0), "groundspeed": data.get("groundspeed", 0), 
                       "climb_rate": data.get("climb_rate", 0), "throttle_pct": data.get("throttle_pct", 0)}
            _telemetry_history["hud"] = pd.concat([_telemetry_history["hud"], pd.DataFrame([new_hud])], ignore_index=True)
            if live_state: live_state.update_telemetry(airspeed=new_hud["airspeed"], speed=new_hud["groundspeed"], climb_rate=new_hud["climb_rate"], throttle_pct=new_hud["throttle_pct"])
            
        elif "esc" in subject or "motor" in subject:
            new_mot = {**new_row, "rpm_1": data.get("rpm1", 0), "rpm_2": data.get("rpm2", 0), "rpm_3": data.get("rpm3", 0), "rpm_4": data.get("rpm4", 0),
                       "cur_1": data.get("current1", 0), "cur_2": data.get("current2", 0), "cur_3": data.get("current3", 0), "cur_4": data.get("current4", 0)}
            _telemetry_history["motors"] = pd.concat([_telemetry_history["motors"], pd.DataFrame([new_mot])], ignore_index=True)
            if live_state: live_state.update_motors(motor_rpm=[new_mot["rpm_1"], new_mot["rpm_2"], new_mot["rpm_3"], new_mot["rpm_4"]], motor_current=[new_mot["cur_1"], new_mot["cur_2"], new_mot["cur_3"], new_mot["cur_4"]])
            
        elif "radio" in subject or "vibration" in subject:
            new_vib = {**new_row, "vibration_x": data.get("vibration_x", 0), "vibration_y": data.get("vibration_y", 0), "vibration_z": data.get("vibration_z", 0),
                       "rssi": data.get("rssi", 0), "link_quality": data.get("link_quality", 100), "gps_hdop": data.get("gps_hdop", 0)}
            _telemetry_history["vibration"] = pd.concat([_telemetry_history["vibration"], pd.DataFrame([new_vib])], ignore_index=True)
            if live_state: live_state.update_radio(rssi=new_vib["rssi"], link_quality=new_vib["link_quality"])

        # Trim history
        for key in _telemetry_history:
            df = _telemetry_history[key]
            if not df.empty:
                _telemetry_history[key] = df[df["timestamp"] >= current_time - _max_history_seconds]


async def _run_nats_client(nats_url: str):
    """Main async NATS loop."""
    if not nats:
        logger.error("nats-py not installed. Cannot run sidecar.")
        return
        
    nc = await nats.connect(nats_url)
    logger.info(f"Sidecar connected to NATS mesh at {nats_url}")
    if live_state:
        live_state.set_connected(True)
        
    await nc.subscribe("sentinel.telemetry.>", cb=_telemetry_handler)
    
    # Run the anomaly detection as a background task
    detect_task = asyncio.create_task(_anomaly_detection_loop(nc))
    
    # Wait until asked to stop
    while not _stop_event.is_set():
        await asyncio.sleep(0.5)
        
    detect_task.cancel()
    await nc.close()
    if live_state:
        live_state.set_connected(False)
    logger.info("Sidecar disconnected from NATS.")


def _start_async_loop(nats_url: str):
    """Thread target to run the asyncio event loop."""
    global _nats_loop
    _nats_loop = asyncio.new_event_loop()
    asyncio.set_event_loop(_nats_loop)
    try:
        _nats_loop.run_until_complete(_run_nats_client(nats_url))
    except Exception as e:
        logger.error(f"Sidecar crashed: {e}")
    finally:
        _nats_loop.close()


def start(connection_string: str = "nats://localhost:4222", window_seconds: int = 10) -> bool:
    """Start the true NATS background daemon."""
    global _monitor_thread
    if is_running():
        return False
        
    _stop_event.clear()
    if live_state:
        live_state.reset_anomalies()
        
    _monitor_thread = threading.Thread(
        target=_start_async_loop,
        args=(connection_string,),
        daemon=True,
        name="SidecarNatsDaemon"
    )
    _monitor_thread.start()
    return True


def stop():
    """Stop the background sidecar."""
    global _monitor_thread
    if is_running():
        _stop_event.set()
        if _monitor_thread:
            _monitor_thread.join(timeout=2.0)


def is_running() -> bool:
    """Check if the sidecar is running."""
    return _monitor_thread is not None and _monitor_thread.is_alive()
