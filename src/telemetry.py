from pymavlink import mavutil
import pandas as pd
import time

def extract_telemetry(connection, duration_seconds=30):
    """
    Read live telemetry from a connected drone.
    Extracts the key message types SENTINEL needs.
    Returns structured DataFrames.
    """
    
    positions = []
    battery = []
    attitude = []
    hud = []
    
    start_time = time.time()
    print(f"SENTINEL: Extracting telemetry for {duration_seconds} seconds...")
    
    while time.time() - start_time < duration_seconds:
        msg = connection.recv_match(blocking=True, timeout=1)
        if msg is None:
            continue
            
        msg_type = msg.get_type()
        ts = time.time()
        
        if msg_type == 'GLOBAL_POSITION_INT':
            positions.append({
                'timestamp': ts,
                'lat': msg.lat / 1e7,
                'lon': msg.lon / 1e7,
                'alt_metres': msg.alt / 1000,
                'relative_alt': msg.relative_alt / 1000,
                'vx': msg.vx / 100,  # m/s
                'vy': msg.vy / 100,
                'vz': msg.vz / 100
            })
            
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
            
        elif msg_type == 'VFR_HUD':
            hud.append({
                'timestamp': ts,
                'airspeed': msg.airspeed,
                'groundspeed': msg.groundspeed,
                'altitude': msg.alt,
                'climb_rate': msg.climb,
                'throttle_pct': msg.throttle
            })
    
    result = {
        'positions': pd.DataFrame(positions),
        'battery': pd.DataFrame(battery),
        'attitude': pd.DataFrame(attitude),
        'hud': pd.DataFrame(hud)
    }
    
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


def extract_telemetry_from_file(filepath: str) -> dict:
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

    return {
        'positions': pd.DataFrame(positions),
        'battery': pd.DataFrame(battery),
        'attitude': pd.DataFrame(attitude),
        'hud': pd.DataFrame(hud)
    }


if __name__ == "__main__":
    from connect import connect_to_drone
    
    conn = connect_to_drone()
    telemetry = extract_telemetry(conn, duration_seconds=15)
    print_mission_summary(telemetry)