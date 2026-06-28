import numpy as np
from typing import List
from .anomaly import AnomalyEvent

def detect(telemetry: dict) -> List[AnomalyEvent]:
    anomalies = []
    if "battery" not in telemetry or len(telemetry["battery"]) < 5:
        return anomalies
    if "hud" not in telemetry or len(telemetry["hud"]) < 5:
        return anomalies
        
    bat_df = telemetry["battery"]
    timestamp = bat_df.iloc[-1].get("timestamp", 0)

    # 1. Internal Impedance Model (Z = dV / dI)
    dV = bat_df["voltage"].diff(periods=3).dropna().values
    dI = bat_df["current"].diff(periods=3).dropna().values
    
    if len(dV) > 0 and len(dI) > 0:
        idx = -1
        if abs(dI[idx]) > 2.0:
            impedance = abs(dV[idx] / dI[idx])
            if impedance > 0.15:
                anomalies.append(AnomalyEvent(
                    event_type="BatteryHighImpedance",
                    timestamp=timestamp,
                    severity="CRITICAL",
                    detail=f"Critically high internal battery impedance detected (Z = {impedance:.3f} Ohms).",
                    recommendation="Battery cells may be degrading rapidly or thermal runaway imminent. Land immediately."
                ))

    # 2. Peukert's Law Capacity Drop Divergence
    pct = bat_df["remaining_pct"].values
    if len(pct) >= 5:
        pct_drop_rate = pct[0] - pct[-1]
        current_mean = bat_df["current"].tail(5).mean()
        
        if pct_drop_rate > 1.0 and current_mean < 20.0:
            anomalies.append(AnomalyEvent(
                event_type="PeukertCapacityAnomalousDrop",
                timestamp=timestamp,
                severity="HIGH",
                detail=f"Battery capacity dropping significantly faster than theoretical Peukert model (Drop: {pct_drop_rate:.1f}%, Current: {current_mean:.1f}A).",
                recommendation="Battery capacity is severely degraded. Return to launch."
            ))

    return anomalies
