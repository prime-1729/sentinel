import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Image, Imu, BatteryState, NavSatFix
from nav_msgs.msg import Odometry
from std_msgs.msg import String, Float32
import asyncio
import nats
import json
import threading
import time

class BridgeNode(Node):
    def __init__(self):
        super().__init__('sentinel_bridge_node')
        self.get_logger().info("SENTINEL ROS2-NATS Bridge initializing...")
        self.drone_id = self.declare_parameter('drone_id', 'drone_0').value
        
        # Subscribe to all relevant MAVROS topics for full sensor extraction
        
        # Local Odometry (high freq)
        self.odom_sub = self.create_subscription(
            Odometry, '/mavros/local_position/odom', self.odom_callback, 10)
            
        # Global Position
        self.global_sub = self.create_subscription(
            NavSatFix, '/mavros/global_position/global', self.global_callback, 10)
            
        # IMU Data
        self.imu_sub = self.create_subscription(
            Imu, '/mavros/imu/data', self.imu_callback, 50)
            
        # Battery State
        self.battery_sub = self.create_subscription(
            BatteryState, '/mavros/battery', self.battery_callback, 2)
            
        # VFR HUD (airspeed, groundspeed, throttle, climb rate)
        # Note: In ROS2 MAVROS this is often a custom message, using Float32 as a placeholder
        # for airspeed to represent the concept
        self.hud_sub = self.create_subscription(
            Float32, '/mavros/vfr_hud/airspeed', self.hud_callback, 10)
            
        # Camera Feed (for Perception)
        self.image_sub = self.create_subscription(
            Image, '/camera/image_raw', self.image_callback, 10)

        # Rate limiting variables for high-frequency topics
        self.last_img_time = 0
        self.last_imu_time = 0
        self.fps_limit = 15.0

        # Setup NATS event loop in a separate thread
        self.nats_loop = asyncio.new_event_loop()
        self.nats_thread = threading.Thread(target=self.run_nats_loop, daemon=True)
        self.nc = None
        self.nats_thread.start()

    def run_nats_loop(self):
        asyncio.set_event_loop(self.nats_loop)
        self.nats_loop.run_until_complete(self.connect_nats())
        self.nats_loop.run_forever()

    async def connect_nats(self):
        try:
            self.nc = await nats.connect("nats://localhost:4222")
            self.get_logger().info("Connected to NATS Mesh")
        except Exception as e:
            self.get_logger().error(f"Failed to connect to NATS: {e}")

    def publish_to_nats(self, subject, payload):
        if self.nc and self.nc.is_connected:
            asyncio.run_coroutine_threadsafe(
                self.nc.publish(subject, json.dumps(payload).encode('utf-8')),
                self.nats_loop
            )

    def odom_callback(self, msg):
        payload = {
            'x': msg.pose.pose.position.x,
            'y': msg.pose.pose.position.y,
            'z': msg.pose.pose.position.z,
            'vx': msg.twist.twist.linear.x,
            'vy': msg.twist.twist.linear.y,
            'vz': msg.twist.twist.linear.z,
            'timestamp': msg.header.stamp.sec + (msg.header.stamp.nanosec / 1e9)
        }
        self.publish_to_nats(f'sentinel.telemetry.{self.drone_id}.odom', payload)

    def global_callback(self, msg):
        payload = {
            'lat': msg.latitude,
            'lon': msg.longitude,
            'alt': msg.altitude,
            'timestamp': msg.header.stamp.sec + (msg.header.stamp.nanosec / 1e9)
        }
        self.publish_to_nats(f'sentinel.telemetry.{self.drone_id}.position', payload)

    def imu_callback(self, msg):
        now = time.time()
        # Rate limit IMU to ~20Hz for NATS to save bandwidth
        if now - self.last_imu_time < 0.05:
            return
        self.last_imu_time = now
        
        payload = {
            'ax': msg.linear_acceleration.x,
            'ay': msg.linear_acceleration.y,
            'az': msg.linear_acceleration.z,
            'gx': msg.angular_velocity.x,
            'gy': msg.angular_velocity.y,
            'gz': msg.angular_velocity.z,
            'timestamp': msg.header.stamp.sec + (msg.header.stamp.nanosec / 1e9)
        }
        self.publish_to_nats(f'sentinel.telemetry.{self.drone_id}.imu', payload)

    def battery_callback(self, msg):
        payload = {
            'voltage': msg.voltage,
            'current': msg.current,
            'remaining_pct': msg.percentage * 100.0,
            'temperature': msg.temperature,
            'timestamp': msg.header.stamp.sec + (msg.header.stamp.nanosec / 1e9)
        }
        self.publish_to_nats(f'sentinel.telemetry.{self.drone_id}.battery', payload)
        
    def hud_callback(self, msg):
        payload = {
            'airspeed': msg.data,
            'timestamp': time.time()
        }
        self.publish_to_nats(f'sentinel.telemetry.{self.drone_id}.hud', payload)

    def image_callback(self, msg):
        # We DO NOT publish raw images to NATS.
        # This callback exists so the camera adapter can grab frames for YOLO.
        # Here we just publish a heartbeat/metadata.
        now = time.time()
        if now - self.last_img_time < (1.0 / self.fps_limit):
            return
        self.last_img_time = now
        
        payload = {
            'width': msg.width,
            'height': msg.height,
            'frame_id': msg.header.frame_id,
            'encoding': msg.encoding,
            'timestamp': msg.header.stamp.sec + (msg.header.stamp.nanosec / 1e9)
        }
        self.publish_to_nats(f'sentinel.telemetry.{self.drone_id}.camera_meta', payload)


def main(args=None):
    rclpy.init(args=args)
    node = BridgeNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()

if __name__ == '__main__':
    main()
