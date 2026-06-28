from typing import List
from .anomaly import AnomalyEvent

def detect(telemetry: dict) -> List[AnomalyEvent]:
    anomalies = []
    if "vibration" not in telemetry or telemetry["vibration"].empty:
        return anomalies
        
    link_df = telemetry["vibration"].iloc[-1]
    timestamp = link_df.get("timestamp", 0)

    link_quality = link_df.get("link_quality", 100)
    gps_hdop = link_df.get("gps_hdop", 0.0)

    if link_quality > 0 and link_quality < 30 and gps_hdop > 2.5:
        anomalies.append(AnomalyEvent(
            event_type="EWJammingSuspected",
            timestamp=timestamp,
            severity="CRITICAL",
            detail=f"Simultaneous loss of C2 link (Quality: {link_quality}%) and GPS degradation (HDOP: {gps_hdop:.1f}).",
            recommendation="Possible RF jamming or spoofing environment. Execute pre-planned loss-of-link protocol."
        ))

    return anomalies
