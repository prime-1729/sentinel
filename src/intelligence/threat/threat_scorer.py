"""
Threat Scorer.
Multi-factor threat prioritization based on class, proximity, and behavior.
"""

from typing import Dict, Any
from ..perception.detector import Detection
from ..tracking.tracker import Track

class ThreatScorer:
    """Prioritize threats to determine the required level of response."""
    
    def __init__(self, frame_shape=(480, 640)):
        self.frame_h, self.frame_w = frame_shape
        
        # Base threat values by class
        self.class_threat_base = {
            "hostile_uas": 0.8,
            "friendly_uas": 0.1,
            "vehicle_military": 0.7,
            "vehicle": 0.5,
            "car": 0.4,
            "truck": 0.5,
            "person": 0.3,
            "weapon": 0.9,
            "bird": 0.05,
            "infrastructure": 0.1,
            "unknown": 0.4
        }
        
    def score(self, track: Track, behavior: Dict[str, Any]) -> Dict[str, Any]:
        """
        Calculate total threat score (0.0 to 1.0).
        """
        # 1. Base score from classification
        base_score = self.class_threat_base.get(track.class_name, 0.4)
        
        # 2. Proximity score (larger bbox = closer)
        x1, y1, x2, y2 = track.bbox
        area = (x2 - x1) * (y2 - y1)
        max_area = self.frame_w * self.frame_h
        
        # Normalize area (0 to 1), but apply non-linear scaling
        # so objects don't have to fill the screen to be a threat
        area_ratio = min(1.0, (area / max_area) * 5.0) 
        proximity_modifier = area_ratio * 0.3 # Max 0.3 added for proximity
        
        # 3. Behavior modifier
        behavior_modifier = 0.0
        if behavior["threat_indicator"]:
            b_type = behavior["behavior"]
            if b_type == "approaching":
                behavior_modifier = 0.3
            elif b_type == "erratic":
                behavior_modifier = 0.2
            elif b_type == "loitering":
                behavior_modifier = 0.15
        
        # 4. Confidence gating
        # Lower the score if we aren't confident in the track
        track_confidence = min(1.0, track.hits / 10.0) * track.confidence
        
        # Calculate final score (clamped to 1.0)
        raw_score = base_score + proximity_modifier + behavior_modifier
        final_score = min(1.0, raw_score * track_confidence)
        
        # Determine priority and action
        priority = "low"
        action = "monitor"
        
        if final_score >= 0.8:
            priority = "critical"
            if track.class_name == "hostile_uas":
                action = "intercept"
            else:
                action = "evade"
        elif final_score >= 0.6:
            priority = "high"
            action = "track"
        elif final_score >= 0.4:
            priority = "medium"
            action = "track"
            
        return {
            "threat_score": float(final_score),
            "priority": priority,
            "recommended_action": action,
            "factors": {
                "base_score": float(base_score),
                "proximity": float(proximity_modifier),
                "behavior": float(behavior_modifier),
                "confidence_gate": float(track_confidence)
            }
        }
