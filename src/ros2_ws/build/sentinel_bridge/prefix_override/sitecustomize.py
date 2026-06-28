import sys
if sys.prefix == '/usr':
    sys.real_prefix = sys.prefix
    sys.prefix = sys.exec_prefix = '/home/karan/drone-projects/sentinel/src/ros2_ws/install/sentinel_bridge'
