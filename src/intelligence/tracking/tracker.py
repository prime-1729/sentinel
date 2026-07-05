"""
Multi-Object Tracking using a ByteTrack-inspired logic.
Associates YOLO detections across frames to maintain track IDs.
"""

import numpy as np
from scipy.optimize import linear_sum_assignment
from dataclasses import dataclass
from typing import Tuple, List, Dict
from ..perception.detector import Detection

@dataclass
class Track:
    track_id: int
    bbox: Tuple[int, int, int, int]
    class_name: str
    confidence: float
    velocity: Tuple[float, float]  # Pixel velocity (vx, vy)
    age: int                       # Frames since creation
    hits: int                      # Total matched frames
    time_since_update: int         # Frames since last match
    state: str                     # "tentative", "confirmed", "deleted"
    state_vector: np.ndarray       # [cx, cy, w, h, vx, vy]
    covariance: np.ndarray         # 6x6 covariance matrix

def box_iou(box1: Tuple[int, int, int, int], box2: Tuple[int, int, int, int]) -> float:
    """Calculate Intersection over Union (IoU) between two bounding boxes."""
    x1_1, y1_1, x2_1, y2_1 = box1
    x1_2, y1_2, x2_2, y2_2 = box2
    
    # Calculate intersection
    x1_i = max(x1_1, x1_2)
    y1_i = max(y1_1, y1_2)
    x2_i = min(x2_1, x2_2)
    y2_i = min(y2_1, y2_2)
    
    if x2_i <= x1_i or y2_i <= y1_i:
        return 0.0
        
    intersection_area = (x2_i - x1_i) * (y2_i - y1_i)
    
    # Calculate union
    box1_area = (x2_1 - x1_1) * (y2_1 - y1_1)
    box2_area = (x2_2 - x1_2) * (y2_2 - y1_2)
    
    union_area = box1_area + box2_area - intersection_area
    
    if union_area <= 0:
        return 0.0
        
    return intersection_area / union_area

class MultiObjectTracker:
    """
    Tracks multiple objects across frames using simple IoU and velocity prediction.
    A simplified version of ByteTrack.
    """
    def __init__(self, max_age: int = 30, min_hits: int = 3, iou_threshold: float = 0.3):
        self.max_age = max_age
        self.min_hits = min_hits
        self.iou_threshold = iou_threshold
        self.tracks: List[Track] = []
        self.next_id = 1
        
        # Kalman Filter Parameters
        self.dt = 1.0
        self.F = np.array([
            [1, 0, 0, 0, self.dt, 0],
            [0, 1, 0, 0, 0, self.dt],
            [0, 0, 1, 0, 0, 0],
            [0, 0, 0, 1, 0, 0],
            [0, 0, 0, 0, 1, 0],
            [0, 0, 0, 0, 0, 1]
        ], dtype=np.float64)
        
        self.H = np.array([
            [1, 0, 0, 0, 0, 0],
            [0, 1, 0, 0, 0, 0],
            [0, 0, 1, 0, 0, 0],
            [0, 0, 0, 1, 0, 0]
        ], dtype=np.float64)
        
        self.Q = np.eye(6, dtype=np.float64) * 1.0
        self.R = np.eye(4, dtype=np.float64) * 10.0
        
    def _predict(self):
        """Update track bounding boxes using Kalman Filter predict step."""
        for track in self.tracks:
            track.time_since_update += 1
            track.age += 1
            
            # Predict state
            track.state_vector = self.F @ track.state_vector
            track.covariance = self.F @ track.covariance @ self.F.T + self.Q
            
            # Update bbox from predicted state
            cx, cy, w, h = track.state_vector[:4]
            track.bbox = (
                int(cx - w/2),
                int(cy - h/2),
                int(cx + w/2),
                int(cy + h/2)
            )

    def update(self, detections: List[Detection], frame_id: int) -> List[Track]:
        """
        Update tracks with new detections.
        """
        # 1. Predict new locations
        self._predict()
        
        # 2. Associate detections to tracks
        matched_tracks = []
        matched_detections = []
        unmatched_tracks = list(range(len(self.tracks)))
        unmatched_detections = list(range(len(detections)))
        
        if len(self.tracks) > 0 and len(detections) > 0:
            # Build IoU cost matrix
            iou_matrix = np.zeros((len(self.tracks), len(detections)))
            for t, track in enumerate(self.tracks):
                for d, det in enumerate(detections):
                    # Only match same class
                    if track.class_name == det.class_name:
                        iou_matrix[t, d] = box_iou(track.bbox, det.bbox)
            
            # Hungarian algorithm matching
            # scipy linear_sum_assignment minimizes cost, so we pass 1.0 - iou_matrix
            cost_matrix = 1.0 - iou_matrix
            row_ind, col_ind = linear_sum_assignment(cost_matrix)
            
            for t, d in zip(row_ind, col_ind):
                if iou_matrix[t, d] > self.iou_threshold:
                    matched_tracks.append(t)
                    matched_detections.append(d)
                    if t in unmatched_tracks:
                        unmatched_tracks.remove(t)
                    if d in unmatched_detections:
                        unmatched_detections.remove(d)
                
        # 3. Update matched tracks
        for t, d in zip(matched_tracks, matched_detections):
            track = self.tracks[t]
            det = detections[d]
            
            # Kalman Filter Update Step
            x1, y1, x2, y2 = det.bbox
            w = x2 - x1
            h = y2 - y1
            cx = x1 + w/2
            cy = y1 + h/2
            z = np.array([cx, cy, w, h], dtype=np.float64)
            
            y = z - (self.H @ track.state_vector)
            S = self.H @ track.covariance @ self.H.T + self.R
            K = track.covariance @ self.H.T @ np.linalg.inv(S)
            
            track.state_vector = track.state_vector + (K @ y)
            track.covariance = (np.eye(6) - (K @ self.H)) @ track.covariance
            
            # Update the simple velocity field for compatibility with other modules
            track.velocity = (float(track.state_vector[4]), float(track.state_vector[5]))
            
            track.bbox = det.bbox
            track.confidence = det.confidence
            track.hits += 1
            track.time_since_update = 0
            
            if track.hits >= self.min_hits:
                track.state = "confirmed"
                
        # 4. Create new tracks for unmatched detections
        for d in unmatched_detections:
            det = detections[d]
            # Only create tracks for high confidence detections
            if det.confidence > 0.6:
                x1, y1, x2, y2 = det.bbox
                w = x2 - x1
                h = y2 - y1
                cx = x1 + w/2
                cy = y1 + h/2
                state_vec = np.array([cx, cy, w, h, 0.0, 0.0], dtype=np.float64)
                cov = np.eye(6, dtype=np.float64) * 100.0
                
                new_track = Track(
                    track_id=self.next_id,
                    bbox=det.bbox,
                    class_name=det.class_name,
                    confidence=det.confidence,
                    velocity=(0.0, 0.0),
                    age=1,
                    hits=1,
                    time_since_update=0,
                    state="tentative" if self.min_hits > 1 else "confirmed",
                    state_vector=state_vec,
                    covariance=cov
                )
                self.tracks.append(new_track)
                self.next_id += 1
                
        # 5. Mark old tracks as deleted
        for t in unmatched_tracks:
            track = self.tracks[t]
            if track.time_since_update > self.max_age:
                track.state = "deleted"
                
        # Remove deleted tracks
        self.tracks = [t for t in self.tracks if t.state != "deleted"]
        
        # Return only confirmed tracks for external use
        return [t for t in self.tracks if t.state == "confirmed"]
