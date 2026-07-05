import pytest
import sys
import os
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
from intelligence.autonomy.reaction_rules import ReactionEngine
from intelligence.domains.anomaly import AnomalyEvent

def test_reaction_escalation():
    engine = ReactionEngine(debounce_frames=1, cooldown_frames=0)
    
    # Simulate an anomaly repeatedly
    anomaly = AnomalyEvent(
        event_type="GPSJamming",
        timestamp=time.time(),
        severity="HIGH",
        detail="Lost sats",
        recommendation="",
        domain="ew"
    )
    
    # Trigger 1-5
    for i in range(5):
        res = engine.evaluate(threats=[], anomalies=[anomaly], telemetry={})
        assert res is not None
        assert res["action"] == "execute_loss_of_link"
        assert res["tier"] == 1
        
def test_reaction_cooldown():
    engine = ReactionEngine(debounce_frames=1, cooldown_frames=10) # 1s cooldown
    
    threat = {
        "priority": "critical",
        "recommended_action": "evade",
        "threat_score": 90.0
    }
    
    res1 = engine.evaluate(threats=[threat], anomalies=[], telemetry={})
    assert res1 is not None
    assert res1["action"] == "evasive_maneuver"
    
    # Immediate next call should be suppressed by cooldown
    res2 = engine.evaluate(threats=[threat], anomalies=[], telemetry={})
    assert res2 is None
