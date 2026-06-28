from launch import LaunchDescription
from launch_ros.actions import Node

def generate_launch_description():
    return LaunchDescription([
        Node(
            package='sentinel_bridge',
            executable='bridge_node',
            name='sentinel_bridge_node',
            output='screen'
        ),
        # MAVROS node is commented out since we don't have it installed locally
        # Node(
        #     package='mavros',
        #     executable='mavros_node',
        #     name='mavros',
        #     output='screen',
        #     parameters=[{'fcu_url': 'udp://127.0.0.1:14551@14555'}]
        # )
    ])
