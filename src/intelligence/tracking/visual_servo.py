"""
Image-Based Visual Servoing (IBVS) Controller.
Generates velocity commands to keep a tracked target centered in the field of view.
"""

from typing import Tuple, Dict, Any
from .tracker import Track

class VisualServo:
    """
    PID controller for Image-Based Visual Servoing (with anti-windup).
    Generates MAVLink-compatible velocity commands based on target bounding box.
    """
    def __init__(self, gain_p: float = 0.5, gain_i: float = 0.05, gain_d: float = 0.1, desired_target_size_ratio: float = 0.1):
        self.kp = gain_p
        self.ki = gain_i
        self.kd = gain_d
        self.desired_target_size = desired_target_size_ratio
        
        # State for integral and derivative terms
        self.integral_error_x = 0.0
        self.integral_error_y = 0.0
        self.integral_error_z = 0.0
        
        self.prev_error_x = 0.0
        self.prev_error_y = 0.0
        self.prev_error_z = 0.0
        self.max_integral = 1.0 # Anti-windup
        
    def compute_command(self, track: Track, frame_shape: Tuple[int, int]) -> Dict[str, float]:
        """
        Compute velocity commands (vx, vy, vz, yaw_rate) to track the target.
        
        Args:
            track: The target to track
            frame_shape: (height, width) of the camera frame
            
        Returns:
            Dictionary with velocity commands (in body frame)
        """
        img_h, img_w = frame_shape
        center_x = img_w / 2
        center_y = img_h / 2
        
        # Target center
        x1, y1, x2, y2 = track.bbox
        target_cx = (x1 + x2) / 2
        target_cy = (y1 + y2) / 2
        
        # Target size (normalized to image area)
        target_area = (x2 - x1) * (y2 - y1)
        img_area = img_w * img_h
        target_size_ratio = target_area / img_area if img_area > 0 else 0
        
        # Calculate errors (normalized -1 to 1)
        # Positive error_x means target is to the right -> positive yaw_rate
        error_x = (target_cx - center_x) / (img_w / 2)
        
        # Positive error_y means target is below center -> negative vz (descend)
        error_y = (target_cy - center_y) / (img_h / 2)
        
        # Positive error_z means target is too small -> positive vx (move forward)
        error_z = self.desired_target_size - target_size_ratio
        
        # Calculate derivative terms
        d_error_x = error_x - self.prev_error_x
        d_error_y = error_y - self.prev_error_y
        d_error_z = error_z - self.prev_error_z
        
        self.prev_error_x = error_x
        self.prev_error_y = error_y
        self.prev_error_z = error_z
        
        # Calculate integral terms
        self.integral_error_x += error_x
        self.integral_error_y += error_y
        self.integral_error_z += error_z
        
        # Anti-windup
        self.integral_error_x = max(-self.max_integral, min(self.max_integral, self.integral_error_x))
        self.integral_error_y = max(-self.max_integral, min(self.max_integral, self.integral_error_y))
        self.integral_error_z = max(-self.max_integral, min(self.max_integral, self.integral_error_z))
        
        # Compute control outputs (P + I + D)
        # Note: These values need to be scaled by max velocity in the action bridge
        yaw_rate = (self.kp * error_x) + (self.ki * self.integral_error_x) + (self.kd * d_error_x)
        vz = -((self.kp * error_y) + (self.ki * self.integral_error_y) + (self.kd * d_error_y))
        
        # Only move forward/backward if the target is roughly centered
        if abs(error_x) < 0.3 and abs(error_y) < 0.3:
            vx = (self.kp * 2.0 * error_z) + (self.ki * self.integral_error_z) + (self.kd * d_error_z)
        else:
            vx = 0.0
            
        # Keep vy at 0 to prioritize "point and shoot" flying style over strafing
        vy = 0.0
        
        # Clamp outputs to sensible normalized ranges (-1.0 to 1.0)
        return {
            "vx": float(max(-1.0, min(1.0, vx))),
            "vy": float(vy),
            "vz": float(max(-1.0, min(1.0, vz))),
            "yaw_rate": float(max(-1.0, min(1.0, yaw_rate)))
        }
