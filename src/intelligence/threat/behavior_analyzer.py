"""
Behavior Analyzer.
Classifies the intent/behavior of tracked targets based on their trajectory history.
"""

import math
import numpy as np
from typing import List, Dict, Any, Tuple
from ..tracking.tracker import Track

class BehaviorAnalyzer:
    """Classify target behavior from track history."""
    
    def __init__(self, history_frames: int = 30, frame_shape: Tuple[int, int] = (480, 640)):
        self.history_frames = history_frames
        self.frame_shape = frame_shape
        self.track_histories: Dict[int, List[Tuple[float, float]]] = {}
        
    def _update_history(self, track: Track) -> List[Tuple[float, float]]:
        """Maintain a sliding window of positions for the track."""
        tid = track.track_id
        
        # Calculate center position
        x1, y1, x2, y2 = track.bbox
        cx = (x1 + x2) / 2
        cy = (y1 + y2) / 2
        
        if tid not in self.track_histories:
            self.track_histories[tid] = []
            
        history = self.track_histories[tid]
        history.append((cx, cy))
        
        if len(history) > self.history_frames:
            history.pop(0)
            
        return history
        
    def analyze(self, track: Track) -> Dict[str, Any]:
        """
        Analyze a track's behavior pattern.
        Returns behavior type, confidence, and whether it's a threat.
        """
        history = self._update_history(track)
        
        # Need enough history to make a judgment
        if len(history) < 10:
            return {
                "behavior": "unknown",
                "confidence": 0.0,
                "threat_indicator": False
            }
            
        # 1. Calculate basic metrics
        pts = np.array(history)
        
        # Total distance traveled along the path
        path_length = np.sum(np.sqrt(np.sum(np.diff(pts, axis=0)**2, axis=1)))
        
        # Straight line distance from start to end
        start_pt = pts[0]
        end_pt = pts[-1]
        displacement = np.sqrt(np.sum((end_pt - start_pt)**2))
        
        # Bounding box of the trajectory
        min_x, min_y = np.min(pts, axis=0)
        max_x, max_y = np.max(pts, axis=0)
        area_covered = (max_x - min_x) * (max_y - min_y)
        
        # 2. Classify based on heuristics
        
        # Meandering ratio (how straight the path is)
        # 1.0 = perfectly straight line
        # > 3.0 = very meandering
        meandering_ratio = path_length / displacement if displacement > 0.1 else 100.0
        
        behavior = "transit"
        confidence = 0.5
        is_threat = False
        
        if displacement < 20.0 and path_length > 50.0:
            # Moving around but not going anywhere -> Loitering
            behavior = "loitering"
            confidence = min(0.9, path_length / 100.0)
            is_threat = True
            
        elif meandering_ratio > 3.0 and path_length > 100.0:
            # High variance in path -> Erratic / Evasive
            behavior = "erratic"
            confidence = min(0.9, meandering_ratio / 5.0)
            is_threat = True
            
        elif meandering_ratio < 1.2 and displacement > 100.0:
            # Straight line
            
            # Is it approaching center? (assuming ownship is roughly center frame)
            # This is a simplification; true approach needs 3D pose relative to ownship
            center = np.array([self.frame_shape[1] / 2, self.frame_shape[0] / 2]) 
            dist_start = np.linalg.norm(start_pt - center)
            dist_end = np.linalg.norm(end_pt - center)
            
            if dist_end < dist_start - 30.0:
                behavior = "approaching"
                confidence = 0.8
                is_threat = True
            else:
                behavior = "transit"
                confidence = 0.8
                is_threat = False
                
        else:
            behavior = "surveillance"
            confidence = 0.6
            is_threat = True
            
        return {
            "behavior": behavior,
            "confidence": float(confidence),
            "threat_indicator": is_threat,
            "metrics": {
                "meandering_ratio": float(meandering_ratio),
                "displacement": float(displacement)
            }
        }
        
    def cleanup(self, active_track_ids: List[int]):
        """Remove history for dead tracks."""
        dead_ids = [tid for tid in self.track_histories.keys() if tid not in active_track_ids]
        for tid in dead_ids:
            del self.track_histories[tid]
