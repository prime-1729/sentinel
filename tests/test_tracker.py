import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
from intelligence.tracking.tracker import MultiObjectTracker
from intelligence.perception.detector import Detection

def test_tracker_basic():
    tracker = MultiObjectTracker(min_hits=1)
    
    # Frame 1
    dets = [Detection(bbox=(10, 10, 50, 50), class_id=0, class_name="person", confidence=0.9, frame_id=1)]
    tracks = tracker.update(dets, frame_id=1)
    
    assert len(tracks) == 1
    assert tracks[0].track_id == 1
    assert tracks[0].bbox == (10, 10, 50, 50)
    
    # Frame 2 (slight movement)
    dets2 = [Detection(bbox=(12, 12, 52, 52), class_id=0, class_name="person", confidence=0.9, frame_id=2)]
    tracks2 = tracker.update(dets2, frame_id=2)
    
    assert len(tracks2) == 1
    assert tracks2[0].track_id == 1 # ID maintained
    assert tracks2[0].bbox == (12, 12, 52, 52)
    assert tracks2[0].hits == 2
