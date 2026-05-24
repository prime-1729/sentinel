from pymavlink import mavutil
import time

def connect_to_drone(connection_string='udpin:127.0.0.1:14551'):
    """
    Connect to a drone via MAVLink.
    connection_string: where to find the drone
    - udupin:127.0.0.1:14551 for SITL (second MAVProxy output; see MAVLINK.md)
    - MAVProxy console/map already uses 14550 — do not share that port
    - Later: serial port for real hardware
    """
    print(f"SENTINEL: Connecting to drone at {connection_string}")
    
    connection = mavutil.mavlink_connection(connection_string)
    
    # Wait for first heartbeat
    # This confirms the drone is alive and talking
    print("SENTINEL: Waiting for heartbeat...")
    connection.wait_heartbeat()
    
    print(f"SENTINEL: Connected.")
    print(f"  System ID: {connection.target_system}")
    print(f"  Component ID: {connection.target_component}")
    
    return connection

def read_telemetry(connection, duration_seconds=10):
    """
    Read raw telemetry for a set duration.
    Returns list of all messages received.
    """
    messages = []
    start_time = time.time()
    
    print(f"\nSENTINEL: Reading telemetry for {duration_seconds} seconds...")
    
    while time.time() - start_time < duration_seconds:
        msg = connection.recv_match(blocking=True, timeout=1)
        if msg is not None:
            msg_dict = msg.to_dict()
            msg_dict['_type'] = msg.get_type()
            msg_dict['_timestamp'] = time.time()
            messages.append(msg_dict)
    
    print(f"SENTINEL: Received {len(messages)} messages")
    return messages

if __name__ == "__main__":
    # Make sure SITL is running before executing this
    conn = connect_to_drone()
    messages = read_telemetry(conn, duration_seconds=5)
    
    # Show what message types we received
    types = {}
    for msg in messages:
        t = msg['_type']
        types[t] = types.get(t, 0) + 1
    
    print("\nSENTINEL: Message types received:")
    for msg_type, count in sorted(types.items()):
        print(f"  {msg_type}: {count} messages")