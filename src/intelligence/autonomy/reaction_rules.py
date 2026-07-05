"""
Reaction Engine.
Deterministic safety reactions. These ALWAYS override learned policies.
"""

import logging
from typing import List, Dict, Any, Optional
from ..domains.anomaly import AnomalyEvent

logger = logging.getLogger("sentinel.autonomy.reaction")

class ReactionEngine:
    """
    Evaluates current state against hard safety rules to output immediate actions.
    """
    
    # Tier 1 = Safety Critical (Immediate override)
    # Tier 2 = Mission Critical (Task re-allocation/abort)
    # Tier 3 = Tactical (Evasion/Pursuit)
    
    RULES = {
        "collision_imminent": {"action": "emergency_stop", "tier": 1},
        "gps_spoofing_detected": {"action": "switch_to_vio_nav", "tier": 1},
        "rf_jamming_detected": {"action": "execute_loss_of_link", "tier": 1},
        "motor_failure": {"action": "emergency_land", "tier": 1},
        "low_battery_critical": {"action": "rtl", "tier": 1},
        "geofence_breach": {"action": "auto_reverse", "tier": 1},
        "comms_lost": {"action": "rtl", "tier": 1},
        "airspace_violation": {"action": "descend_and_loiter", "tier": 1},
        "hostile_uas_approaching": {"action": "evasive_maneuver", "tier": 2},
        "target_acquired": {"action": "begin_tracking", "tier": 3},
    }

    def __init__(self, debounce_frames: int = 3, cooldown_frames: int = 10):
        self.debounce_frames = debounce_frames
        self.cooldown_frames = cooldown_frames
        self.trigger_history = {}
        self.last_action_time = 0
        self.escalation_level = {}

    def evaluate(self, threats: List[Dict[str, Any]], anomalies: List[AnomalyEvent], telemetry: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Check all rules against current state.
        Returns the highest-priority (lowest tier number) action, or None.
        """
        import time
        current_time = time.time()
        triggered_rules = []
        
        # 1. Check Anomalies (Hardware/System State)
        for anomaly in anomalies:
            if anomaly.severity == "CRITICAL" or anomaly.severity == "HIGH":
                domain = anomaly.domain
                
                if domain == "propulsion":
                    triggered_rules.append(("motor_failure", anomaly.detail))
                elif domain == "power":
                    triggered_rules.append(("low_battery_critical", anomaly.detail))
                elif domain == "navigation":
                    if "Altitude" in anomaly.event_type:
                        triggered_rules.append(("airspace_violation", anomaly.detail))
                    else:
                        triggered_rules.append(("gps_spoofing_detected", anomaly.detail))
                elif domain == "ew":
                    triggered_rules.append(("rf_jamming_detected", anomaly.detail))
                elif domain == "communication":
                    triggered_rules.append(("comms_lost", anomaly.detail))
                elif domain == "environmental":
                    triggered_rules.append(("geofence_breach", anomaly.detail))
                elif domain == "dynamics":
                    triggered_rules.append(("motor_failure", anomaly.detail))
                    
        # 2. Check Threats (External State)
        for threat in threats:
            if threat["priority"] == "critical":
                # Need to act on this threat
                if threat["recommended_action"] == "evade":
                    triggered_rules.append(("hostile_uas_approaching", f"Threat score {threat['threat_score']:.2f}"))
            elif threat["priority"] == "high":
                triggered_rules.append(("target_acquired", f"Tracking object with score {threat['threat_score']:.2f}"))
                
        # Update history for debouncing
        current_triggers = {rule_id: reason for rule_id, reason in triggered_rules}
        
        # Increment counters for current rules, reset others
        for rule_id in self.RULES:
            if rule_id in current_triggers:
                self.trigger_history[rule_id] = self.trigger_history.get(rule_id, 0) + 1
            else:
                self.trigger_history[rule_id] = 0
                
        # Filter triggered_rules by debounce threshold
        debounced_rules = [(r, current_triggers[r]) for r in current_triggers if self.trigger_history[r] >= self.debounce_frames]
                
        # 3. Resolve Priorities
        if not debounced_rules:
            return None
            
        best_rule = None
        best_tier = 99
        best_reason = ""
        
        for rule_id, reason in debounced_rules:
            if rule_id in self.RULES:
                tier = self.RULES[rule_id]["tier"]
                if tier < best_tier:
                    best_tier = tier
                    best_rule = self.RULES[rule_id]["action"]
                    best_reason = reason
                    
        if best_rule:
            # Check cooldown (allow Tier 1 to bypass cooldown)
            if best_tier > 1 and (current_time - self.last_action_time) < (self.cooldown_frames * 0.1):
                return None
                
            # Escalation logic
            self.escalation_level[best_rule] = self.escalation_level.get(best_rule, 0) + 1
            if self.escalation_level[best_rule] > 5 and best_tier > 1:
                # Escalate tier 2/3 to tier 1 emergency
                best_rule = "rtl" if best_rule != "rtl" else "emergency_land"
                best_tier = 1
                best_reason += " [ESCALATED]"
                
            self.last_action_time = current_time
            logger.warning(f"REACTION ENGINE TRIGGERED: {best_rule} (Tier {best_tier}) - {best_reason}")
            return {
                "action": best_rule,
                "tier": best_tier,
                "reason": best_reason
            }
            
        return None
