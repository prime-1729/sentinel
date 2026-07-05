import pytest
import sys
import os
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
from intelligence.threat.behavior_analyzer import BehaviorAnalyzer
from intelligence.tracking.tracker import Track

def test_behavior_analyzer():
    analyzer = BehaviorAnalyzer()
    
    # Create a track that is loitering (not moving much over many frames)
    track = Track(
        track_id=1,
        bbox=(100, 100, 150, 150),
        class_name="drone",
        confidence=0.9,
        velocity=(0.0, 0.0),
        age=20,
        hits=20,
        time_since_update=0,
        state="confirmed",
        state_vector=np.zeros(6),
        covariance=np.eye(6)
    )
    
    # Simulate history with small random movements around the same spot
    for i in range(30):
        # Oscillate to build path_length > 50 but keep displacement < 20
        offset = np.sin(i) * 5.0
        track.bbox = (100 + offset, 100 + offset, 150 + offset, 150 + offset)
        res = analyzer.analyze(track)
        
    # After enough frames of not moving, should be classified as loitering
    assert res["behavior"] == "loitering"
    assert res["threat_indicator"] == True
