from setuptools import setup
import os
from glob import glob

package_name = 'sentinel_bridge'

setup(
    name=package_name,
    version='0.0.1',
    packages=[package_name],
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        (os.path.join('share', package_name, 'launch'), glob('launch/*.launch.py')),
    ],
    install_requires=['setuptools', 'nats-py'],
    zip_safe=True,
    maintainer='Karan',
    maintainer_email='dev@sentinel.local',
    description='ROS2 to NATS bridge for SENTINEL',
    license='MIT',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            'bridge_node = sentinel_bridge.bridge_node:main'
        ],
    },
)
