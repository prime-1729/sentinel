from typing import List
from .anomaly import AnomalyEvent

def detect(telemetry: dict) -> List[AnomalyEvent]:
    anomalies = []
    if "positions" not in telemetry or telemetry["positions"].empty:
        return anomalies
    if "hud" not in telemetry or telemetry["hud"].empty:
        return anomalies
        
    pos_df = telemetry["positions"].iloc[-1]
    hud_df = telemetry["hud"].iloc[-1]
    timestamp = pos_df.get("timestamp", 0)

    vz = abs(pos_df.get("vz", 0))
    climb_rate = abs(hud_df.get("climb_rate", 0))

    if vz > 1.0 and climb_rate > 1.0:
        diff = abs(vz - climb_rate)
        if diff > 3.0:
            anomalies.append(AnomalyEvent(
                event_type="NavIntegrityMismatch",
                timestamp=timestamp,
                severity="CRITICAL",
                detail=f"GPS vertical velocity ({vz:.1f}m/s) diverges from Barometric climb rate ({climb_rate:.1f}m/s).",
                recommendation="EKF divergence likely. Switch to manual/stabilize mode."
            ))

    return anomalies
