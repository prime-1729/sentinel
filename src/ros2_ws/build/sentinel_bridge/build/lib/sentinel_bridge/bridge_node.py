import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Image, Imu
from nav_msgs.msg import Odometry
import asyncio
import nats
import json
import threading

class BridgeNode(Node):
    def __init__(self):
        super().__init__('sentinel_bridge_node')
        self.get_logger().info("SENTINEL ROS2-NATS Bridge initializing...")
        
        # Subscribe to simulated high-bandwidth topics
        self.odom_sub = self.create_subscription(
            Odometry,
            '/mavros/local_position/odom',
            self.odom_callback,
            10
        )
        
        self.image_sub = self.create_subscription(
            Image,
            '/camera/depth/image_raw',
            self.image_callback,
            10
        )

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
            self.get_logger().info("Connected to NATS")
        except Exception as e:
            self.get_logger().error(f"Failed to connect to NATS: {e}")

    def publish_to_nats(self, subject, payload):
        if self.nc and self.nc.is_connected:
            # Schedule publish in the async event loop
            asyncio.run_coroutine_threadsafe(
                self.nc.publish(subject, json.dumps(payload).encode('utf-8')),
                self.nats_loop
            )

    def odom_callback(self, msg):
        payload = {
            'type': 'odom',
            'x': msg.pose.pose.position.x,
            'y': msg.pose.pose.position.y,
            'z': msg.pose.pose.position.z,
        }
        self.publish_to_nats('sentinel.telemetry.ros.odom', payload)

    def image_callback(self, msg):
        # We wouldn't publish raw images to NATS normally, just metadata or compressed
        payload = {
            'type': 'depth_image',
            'width': msg.width,
            'height': msg.height,
            'frame_id': msg.header.frame_id
        }
        self.publish_to_nats('sentinel.telemetry.ros.camera', payload)


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
