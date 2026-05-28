from pymavlink import mavutil
import time
import math
import pandas as pd
from datetime import datetime
from anomaly import (
    run_all_detectors,
    store_anomalies
)
from dotenv import load_dotenv

load_dotenv()

# Track what we have already alerted on
alerted_events = set()

def format_time(ts):
    return datetime.fromtimestamp(ts).strftime('%H:%M:%S')

def print_alert(severity, event_type, detail, recommendation):
    icons = {
        'CRITICAL': '🔴',
        'HIGH': '🟠', 
        'MEDIUM': '🟡',
        'LOW': '🟢'
    }
    icon = icons.get(severity, '⚪')
    print(f"\n{icon} [{format_time(time.time())}] {severity} — {event_type}")
    print(f"   {detail}")
    print(f"   → {recommendation}")

def monitor_live(connection_string='udpin:127.0.0.1:14551', window_seconds=10):
    """
    Monitor a live drone mission in real time.
    Runs anomaly detection every window_seconds.
    Alerts operator immediately when something is detected.
    """
    print("=" * 60)
    print("SENTINEL LIVE MISSION MONITOR")
    print("=" * 60)
    print(f"Connecting to {connection_string}...")

    connection = mavutil.mavlink_connection(connection_string)
    connection.wait_heartbeat()

    print(f"Connected. Monitoring live mission.")
    print(f"Anomaly scan every {window_seconds} seconds.")
    print("Press Ctrl+C to stop.\n")

    # Rolling data buffers
    positions = []
    battery = []
    attitude = []
    hud = []
    radio = []
    gps = []

    scan_timer = time.time()
    mission_start = time.time()

    while True:
        msg = connection.recv_match(blocking=True, timeout=1)
        if msg is None:
            continue

        msg_type = msg.get_type()
        ts = time.time()

        # Collect telemetry into rolling buffers
        if msg_type == 'GLOBAL_POSITION_INT':
            positions.append({
                'timestamp': ts,
                'lat': msg.lat / 1e7,
                'lon': msg.lon / 1e7,
                'relative_alt': msg.relative_alt / 1000,
                'vx': msg.vx / 100,
                'vy': msg.vy / 100,
            })

        elif msg_type == 'BATTERY_STATUS':
            battery.append({
                'timestamp': ts,
                'voltage': msg.voltages[0] / 1000,
                'current': msg.current_battery / 100,
                'remaining_pct': msg.battery_remaining
            })

        elif msg_type == 'ATTITUDE':
            attitude.append({
                'timestamp': ts,
                'roll_deg': math.degrees(msg.roll),
                'pitch_deg': math.degrees(msg.pitch),
                'yaw_deg': math.degrees(msg.yaw)
            })

        elif msg_type == 'VFR_HUD':
            hud.append({
                'timestamp': ts,
                'airspeed': msg.airspeed,
                'groundspeed': msg.groundspeed,
                'altitude': msg.alt,
                'climb_rate': msg.climb,
                'throttle_pct': msg.throttle
            })
            
        elif msg_type == "RADIO_STATUS":
            radio.append({
                "timestamp": ts,
                "rssi": msg.rssi,
            })

        elif msg_type == "GPS_RAW_INT":
            gps.append({
                "timestamp": ts,
                "eph": msg.eph,
            })

        # Print live status every 5 seconds
        elapsed = int(time.time() - mission_start)
        if elapsed % 5 == 0 and len(positions) > 0:
            latest_pos = positions[-1]
            latest_bat = battery[-1] if battery else {}
            latest_hud = hud[-1] if hud else {}
            print(
                f"[{format_time(ts)}] "
                f"T+{elapsed}s | "
                f"Alt: {latest_pos.get('relative_alt', 0):.1f}m | "
                f"Speed: {latest_hud.get('groundspeed', 0):.1f}m/s | "
                f"Battery: {latest_bat.get('remaining_pct', 0)}% | "
                f"Voltage: {latest_bat.get('voltage', 0):.2f}V",
                end='\r'
            )

        # Run anomaly detection every window_seconds
        if time.time() - scan_timer >= window_seconds:
            scan_timer = time.time()
            new_anomalies = []

            # Create telemetry dictionary
            telemetry = {}
            if len(battery) > 1: telemetry['battery'] = pd.DataFrame(battery)
            if len(positions) > 1: telemetry['positions'] = pd.DataFrame(positions)
            if len(attitude) > 0: telemetry['attitude'] = pd.DataFrame(attitude)
            if len(hud) > 0: telemetry['hud'] = pd.DataFrame(hud)
            if len(radio) > 0: telemetry['radio'] = pd.DataFrame(radio)
            if len(gps) > 0: telemetry['gps'] = pd.DataFrame(gps)

            # We need at least the core 4 dataframes for full detection (including ML)
            if all(k in telemetry for k in ['battery', 'positions', 'attitude', 'hud']):
                all_anomalies = run_all_detectors(telemetry, enable_ml=True, model_path="data/ml_model.joblib")
                
                for a in all_anomalies:
                    event_key = f"{a.event_type}_{int(a.timestamp)}"
                    if event_key not in alerted_events:
                        alerted_events.add(event_key)
                        new_anomalies.append(a)
                        print_alert(
                            a.severity,
                            a.event_type,
                            a.detail,
                            a.recommendation
                        )
                        
            if new_anomalies:
                try:
                    store_anomalies(new_anomalies, drone_id="drone_monitor", mission_id="mission_monitor")
                except Exception as e:
                    print(f"Failed to store anomalies in database: {e}")

            # Keep only last 60 seconds of data in buffer
            cutoff = time.time() - 60
            positions = [p for p in positions if p['timestamp'] > cutoff]
            battery = [b for b in battery if b['timestamp'] > cutoff]
            attitude = [a for a in attitude if a['timestamp'] > cutoff]
            hud = [h for h in hud if h['timestamp'] > cutoff]
            radio = [r for r in radio if r['timestamp'] > cutoff]
            gps = [g for g in gps if g['timestamp'] > cutoff]


if __name__ == "__main__":
    try:
        monitor_live()
    except KeyboardInterrupt:
        print("\n\nSENTINEL: Monitor stopped.")
        print("Run report.py to generate after-action intelligence report.")