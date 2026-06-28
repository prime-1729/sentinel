"""
SENTINEL Reasoning Engine — Rule-based cross-stream correlation.

Named, testable condition → conclusion pairs. No LLM involved.
Each rule checks for multi-stream patterns in a telemetry context
and returns a structured conclusion with evidence and confidence.

Rules are defined in ARCHITECTURE.md and evaluated in priority order
(HIGH confidence first). The query engine builds the context dict
and calls evaluate() after every query.
"""

from dataclasses import dataclass, field
from typing import List, Callable, Dict, Any, Optional


@dataclass
class CorrelationResult:
    """
    Result of evaluating a single correlation rule against a context.
    """
    rule_name: str
    triggered: bool
    conclusion: str
    confidence: str           # HIGH / MEDIUM / LOW
    evidence: List[Dict[str, Any]] = field(default_factory=list)


class CorrelationRule:
    """
    A named correlation rule with conditions and conclusion.
    
    Attributes:
        name: Machine-readable rule identifier (e.g. "signal_induced_deviation")
        description: Human-readable explanation of what this rule detects
        conditions: Callable that takes a context dict and returns bool
        conclusion: What it means operationally if conditions match
        confidence: Expected confidence level when this rule fires
    """
    def __init__(
        self,
        name: str,
        description: str,
        conditions: Callable[[Dict[str, Any]], bool],
        conclusion: str,
        confidence: str
    ):
        self.name = name
        self.description = description
        self.conditions = conditions
        self.conclusion = conclusion
        self.confidence = confidence

    def evaluate(self, context: Dict[str, Any]) -> CorrelationResult:
        """
        Evaluate this rule against a telemetry context.
        Returns a CorrelationResult with triggered=True if conditions match.
        """
        try:
            triggered = self.conditions(context)
        except (KeyError, TypeError, IndexError):
            triggered = False

        evidence = []
        if triggered:
            evidence = self._gather_evidence(context)

        return CorrelationResult(
            rule_name=self.name,
            triggered=triggered,
            conclusion=self.conclusion if triggered else "",
            confidence=self.confidence if triggered else "",
            evidence=evidence
        )

    def _gather_evidence(self, context: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Collect supporting evidence from the context for this rule.
        """
        evidence = []
        
        # Include relevant anomalies
        anomalies = context.get("anomalies", [])
        for a in anomalies:
            evidence.append({
                "type": "anomaly",
                "event_type": a.get("event_type", ""),
                "severity": a.get("severity", ""),
                "detail": a.get("detail", ""),
                "timestamp": a.get("timestamp", 0)
            })

        # Include deviation if present
        deviation = context.get("deviation_metres")
        if deviation is not None:
            evidence.append({
                "type": "measurement",
                "metric": "position_deviation",
                "value_metres": deviation
            })

        # Include throttle if relevant
        avg_throttle = context.get("avg_throttle")
        if avg_throttle is not None:
            evidence.append({
                "type": "measurement",
                "metric": "avg_throttle_pct",
                "value": avg_throttle
            })

        return evidence


# ─── Rule condition functions ────────────────────────────────
# Each takes a context dict and returns bool.
# Context keys:
#   anomalies:        list of anomaly event dicts
#   deviation_metres: float (position deviation, if applicable)
#   avg_throttle:     float (mean throttle % in window)
#   time_window:      (start, end) tuple
#   positions:        list of position dicts
#   battery:          list of battery dicts


def _has_anomaly_type(anomalies: list, event_type: str) -> bool:
    """Check if any anomaly of the given type exists in the list."""
    return any(a.get("event_type") == event_type for a in anomalies)


def _has_anomaly_severity(anomalies: list, event_type: str, severity: str) -> bool:
    """Check if an anomaly of given type AND severity exists."""
    return any(
        a.get("event_type") == event_type and a.get("severity") == severity
        for a in anomalies
    )


def _signal_induced_deviation(ctx: Dict[str, Any]) -> bool:
    """
    Signal-induced position deviation.
    Conditions: deviation > 20m AND SignalDegraded anomaly present.
    Source: ARCHITECTURE.md — signal_induced_deviation rule.
    """
    deviation = ctx.get("deviation_metres", 0)
    anomalies = ctx.get("anomalies", [])
    return deviation > 20 and _has_anomaly_type(anomalies, "SignalDegraded")


def _battery_forced_descent(ctx: Dict[str, Any]) -> bool:
    """
    Battery voltage drop caused altitude loss.
    Conditions: RapidDescent AND BatteryStress both present.
    Source: ARCHITECTURE.md — battery_forced_descent rule.
    """
    anomalies = ctx.get("anomalies", [])
    return (
        _has_anomaly_type(anomalies, "RapidDescent") and
        _has_anomaly_type(anomalies, "BatteryStress")
    )


def _motor_failure_pattern(ctx: Dict[str, Any]) -> bool:
    """
    Partial motor failure — asymmetric thrust.
    Conditions: MotorImbalance OR (ExtremeAttitude AND RapidDescent AND avg throttle > 70%).
    High throttle + attitude breach + descent = motor producing less thrust
    than commanded, causing asymmetric lift.
    Source: ARCHITECTURE.md — motor_failure_pattern rule.
    """
    anomalies = ctx.get("anomalies", [])
    if _has_anomaly_type(anomalies, "MotorImbalance"):
        return True
        
    avg_throttle = ctx.get("avg_throttle", 0)
    return (
        _has_anomaly_type(anomalies, "ExtremeAttitude") and
        _has_anomaly_type(anomalies, "RapidDescent") and
        avg_throttle > 70
    )


def _gps_position_error(ctx: Dict[str, Any]) -> bool:
    """
    GPS accuracy issue causing apparent position deviation.
    Conditions: deviation > 20m AND GPSGlitch AND NO SignalDegraded.
    The absence of signal issues distinguishes GPS error from comm loss.
    Source: ARCHITECTURE.md — gps_position_error rule.
    """
    deviation = ctx.get("deviation_metres", 0)
    anomalies = ctx.get("anomalies", [])
    return (
        deviation > 20 and
        _has_anomaly_type(anomalies, "GPSGlitch") and
        not _has_anomaly_type(anomalies, "SignalDegraded")
    )


def _environmental_drift(ctx: Dict[str, Any]) -> bool:
    """
    Wind or environmental factor causing position deviation.
    Conditions: deviation > 20m AND no anomalies in window.
    This is the catch-all — fires only when no other explanation exists.
    Source: ARCHITECTURE.md — environmental_drift rule.
    """
    deviation = ctx.get("deviation_metres", 0)
    anomalies = ctx.get("anomalies", [])
    return deviation > 20 and len(anomalies) == 0


# ─── Reasoning Engine ────────────────────────────────────────


class ReasoningEngine:
    """
    Evaluates all correlation rules against a telemetry context.
    
    The context dict is built by the query engine from SQLite data
    and passed here for cross-stream pattern detection.
    
    Rules are registered in priority order (HIGH confidence first).
    All triggered rules are returned — the caller decides how to
    present multiple matches.
    """

    def __init__(self):
        self.rules: List[CorrelationRule] = []
        self._register_default_rules()

    def _register_default_rules(self) -> None:
        """Register the five named correlation rules from ARCHITECTURE.md."""
        
        self.rules.append(CorrelationRule(
            name="signal_induced_deviation",
            description="Communication interference caused position deviation. "
                        "SignalDegraded anomaly detected within the same time window "
                        "as significant position deviation (>20m from planned route).",
            conditions=_signal_induced_deviation,
            conclusion="Communication interference caused position deviation. "
                        "The drone likely lost or degraded its telemetry link, "
                        "preventing accurate navigation commands.",
            confidence="HIGH"
        ))

        self.rules.append(CorrelationRule(
            name="battery_forced_descent",
            description="Battery voltage drop caused altitude loss. "
                        "BatteryStress and RapidDescent detected in the same window.",
            conditions=_battery_forced_descent,
            conclusion="Battery voltage drop caused uncontrolled altitude loss. "
                        "The power system could not sustain flight loads, "
                        "resulting in rapid descent.",
            confidence="HIGH"
        ))

        self.rules.append(CorrelationRule(
            name="motor_failure_pattern",
            description="Partial motor failure with asymmetric thrust. "
                        "ExtremeAttitude + RapidDescent + high throttle (>70%).",
            conditions=_motor_failure_pattern,
            conclusion="Partial motor failure suspected. Asymmetric thrust caused "
                        "attitude instability despite high throttle command. "
                        "Inspect all motors and ESCs before next flight.",
            confidence="MEDIUM"
        ))

        self.rules.append(CorrelationRule(
            name="gps_position_error",
            description="GPS accuracy issue caused apparent position deviation. "
                        "GPSGlitch detected with no signal anomaly — deviation is "
                        "measurement error, not actual flight path deviation.",
            conditions=_gps_position_error,
            conclusion="Position deviation is likely a GPS measurement error, not "
                        "an actual flight path issue. HDOP exceeded ArduPilot's "
                        "GPS_HDOP_GOOD threshold during this window.",
            confidence="MEDIUM"
        ))

        self.rules.append(CorrelationRule(
            name="environmental_drift",
            description="Position deviation with no detected anomalies. "
                        "Wind or environmental factors are the probable cause.",
            conditions=_environmental_drift,
            conclusion="Position deviation attributed to environmental factors "
                        "(wind, turbulence). No system anomalies detected. "
                        "Consider wind conditions for future mission planning.",
            confidence="LOW"
        ))

    def evaluate(self, context: Dict[str, Any]) -> List[CorrelationResult]:
        """
        Evaluate all rules against the given context.
        Returns only triggered rules, in registration order (HIGH first).
        """
        results = []
        for rule in self.rules:
            result = rule.evaluate(context)
            if result.triggered:
                results.append(result)
        return results

    def get_rule_names(self) -> List[str]:
        """Return all registered rule names."""
        return [r.name for r in self.rules]
