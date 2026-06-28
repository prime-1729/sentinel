from pymavlink import mavutil
import pandas as pd
import time

import asyncio
import json
import nats
from nats.errors import ConnectionClosedError, TimeoutError

async def extract_telemetry_async(connection, duration_seconds=30, publish_to_nats=False, drone_id="drone_0", mission_id=None):
    """
    Read live telemetry from a connected drone.
    Extracts the key message types SENTINEL needs.
    Returns structured DataFrames and publishes to NATS if enabled.
    """
    
    positions = []
    battery = []
    attitude = []
    hud = []
    radio = []
    gps = []
    esc = []
    
    nc = None
    if publish_to_nats:
        nc = await nats.connect("nats://localhost:4222")
        print("SENTINEL: Connected to NATS mesh")

    start_time = time.time()
    print(f"SENTINEL: Extracting telemetry for {duration_seconds} seconds...")
    
    while time.time() - start_time < duration_seconds:
        msg = connection.recv_match(blocking=False)
        if msg is None:
            await asyncio.sleep(0.01)
            continue
            
        msg_type = msg.get_type()
        ts = time.time()
        
        if msg_type == 'GLOBAL_POSITION_INT':
            pos_data = {
                'timestamp': ts,
                'lat': msg.lat / 1e7,
                'lon': msg.lon / 1e7,
                'alt_metres': msg.alt / 1000,
                'relative_alt': msg.relative_alt / 1000,
                'vx': msg.vx / 100,  # m/s
                'vy': msg.vy / 100,
                'vz': msg.vz / 100
            }
            positions.append(pos_data)
            if publish_to_nats and nc:
                await nc.publish(f"sentinel.telemetry.{drone_id}.position", json.dumps(pos_data).encode())
            
        elif msg_type == 'BATTERY_STATUS':
            positions_len = len(positions)
            battery.append({
                'timestamp': ts,
                'voltage': msg.voltages[0] / 1000,  # convert mV to V
                'current': msg.current_battery / 100,  # convert cA to A
                'remaining_pct': msg.battery_remaining
            })
            
        elif msg_type == 'ATTITUDE':
            import math
            attitude.append({
                'timestamp': ts,
                'roll_deg': math.degrees(msg.roll),
                'pitch_deg': math.degrees(msg.pitch),
                'yaw_deg': math.degrees(msg.yaw)
            })
            
            hud.append({
                'timestamp': ts,
                'airspeed': msg.airspeed,
                'groundspeed': msg.groundspeed,
                'altitude': msg.alt,
                'climb_rate': msg.climb,
                'throttle_pct': msg.throttle
            })
            
        elif msg_type == 'RADIO_STATUS':
            radio.append({
                'timestamp': ts,
                'rssi': msg.rssi,
                'remrssi': msg.remrssi,
                'rxerrors': msg.rxerrors,
                'fixed': msg.fixed
            })
            
        elif msg_type == 'GPS_RAW_INT':
            gps.append({
                'timestamp': ts,
                'eph': msg.eph,
                'epv': msg.epv,
                'satellites_visible': msg.satellites_visible,
                'fix_type': msg.fix_type
            })
            
        elif msg_type == 'ESC_TELEMETRY_1_TO_4':
            esc.append({
                'timestamp': ts,
                'rpm1': msg.rpm[0],
                'rpm2': msg.rpm[1],
                'rpm3': msg.rpm[2],
                'rpm4': msg.rpm[3],
                'current1': msg.current[0],
                'current2': msg.current[1],
                'current3': msg.current[2],
                'current4': msg.current[3]
            })
    
    result = {
        'positions': pd.DataFrame(positions),
        'battery': pd.DataFrame(battery),
        'attitude': pd.DataFrame(attitude),
        'hud': pd.DataFrame(hud),
        'radio': pd.DataFrame(radio),
        'gps': pd.DataFrame(gps),
        'esc': pd.DataFrame(esc)
    }
    
    if publish_to_nats and nc:
        await nc.close()
        print("SENTINEL: Closed NATS connection")
    
    # Print summary
    print("\nSENTINEL: Telemetry extracted:")
    for key, df in result.items():
        if len(df) > 0:
            print(f"  {key}: {len(df)} readings")
    
    return result


def print_mission_summary(telemetry):
    """
    Print a human readable summary of extracted telemetry.
    """
    pos = telemetry['positions']
    bat = telemetry['battery']
    hud = telemetry['hud']
    
    print("\n" + "="*50)
    print("SENTINEL: MISSION SUMMARY")
    print("="*50)
    
    if len(pos) > 0:
        duration = pos['timestamp'].max() - pos['timestamp'].min()
        max_alt = pos['relative_alt'].max()
        print(f"Duration:     {duration:.1f} seconds")
        print(f"Max altitude: {max_alt:.1f} metres")
    
    if len(bat) > 0:
        print(f"Battery start: {bat['remaining_pct'].iloc[0]}%")
        print(f"Battery end:   {bat['remaining_pct'].iloc[-1]}%")
        print(f"Voltage range: {bat['voltage'].min():.2f}V - {bat['voltage'].max():.2f}V")
    
    if len(hud) > 0:
        print(f"Max groundspeed: {hud['groundspeed'].max():.1f} m/s")
        print(f"Max climb rate:  {hud['climb_rate'].max():.1f} m/s")
    
    print("="*50)


def extract_telemetry_from_file(filepath: str, store_in_db=False, db_path="data/sentinel.db", drone_id="drone_0", mission_id=None) -> dict:
    """
    Extract telemetry from a saved log file.
    Works with .tlog and .bin files from ArduPilot.
    """
    from pymavlink import mavutil
    import math

    positions = []
    battery = []
    attitude = []
    hud = []
    radio = []
    gps = []
    esc = []

    mlog = mavutil.mavlink_connection(filepath)

    while True:
        msg = mlog.recv_match(blocking=False)
        if msg is None:
            break

        msg_type = msg.get_type()
        ts = getattr(msg, '_timestamp', 0)

        if msg_type == 'GLOBAL_POSITION_INT':
            positions.append({
                'timestamp': ts,
                'lat': msg.lat / 1e7,
                'lon': msg.lon / 1e7,
                'alt_metres': msg.alt / 1000,
                'relative_alt': msg.relative_alt / 1000,
                'vx': msg.vx / 100,
                'vy': msg.vy / 100,
                'vz': msg.vz / 100
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
            
        elif msg_type == 'RADIO_STATUS':
            radio.append({
                'timestamp': ts,
                'rssi': msg.rssi,
                'remrssi': msg.remrssi,
                'rxerrors': msg.rxerrors,
                'fixed': msg.fixed
            })
            
        elif msg_type == 'GPS_RAW_INT':
            gps.append({
                'timestamp': ts,
                'eph': msg.eph,
                'epv': msg.epv,
                'satellites_visible': msg.satellites_visible,
                'fix_type': msg.fix_type
            })
            
        elif msg_type == 'ESC_TELEMETRY_1_TO_4':
            esc.append({
                'timestamp': ts,
                'rpm1': msg.rpm[0],
                'rpm2': msg.rpm[1],
                'rpm3': msg.rpm[2],
                'rpm4': msg.rpm[3],
                'current1': msg.current[0],
                'current2': msg.current[1],
                'current3': msg.current[2],
                'current4': msg.current[3]
            })

    result = {
        'positions': pd.DataFrame(positions),
        'battery': pd.DataFrame(battery),
        'attitude': pd.DataFrame(attitude),
        'hud': pd.DataFrame(hud),
        'radio': pd.DataFrame(radio),
        'gps': pd.DataFrame(gps),
        'esc': pd.DataFrame(esc)
    }
    
    if store_in_db:
        from telemetry_store import TelemetryStore
        import uuid
        import os
        if mission_id is None:
            base = os.path.splitext(os.path.basename(filepath))[0]
            mission_id = f"mission_{base}_{int(time.time())}"
        store = TelemetryStore(db_path)
        store.ingest_dataframes(result, drone_id, mission_id)
        store.complete_mission(mission_id)
        store.close()
        
    return result


if __name__ == "__main__":
    from connect import connect_to_drone
    
    conn = connect_to_drone()
    # Run the async test wrapper
    telemetry = asyncio.run(extract_telemetry_async(conn, duration_seconds=15, publish_to_nats=True))
    print_mission_summary(telemetry)