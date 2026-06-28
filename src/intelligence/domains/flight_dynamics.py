import numpy as np
from typing import List
from .anomaly import AnomalyEvent

def detect(telemetry: dict) -> List[AnomalyEvent]:
    anomalies = []
    if "attitude" not in telemetry or len(telemetry["attitude"]) < 10:
        return anomalies
    if "hud" not in telemetry or len(telemetry["hud"]) < 10:
        return anomalies
        
    att_df = telemetry["attitude"]
    hud_df = telemetry["hud"]
    timestamp = att_df.iloc[-1].get("timestamp", 0)

    # 1. Aerodynamic Covariance (System ID)
    # Pitch rate should correlate with airspeed changes.
    # If airspeed drops but pitch rate is highly volatile, aerodynamic stall is occurring.
    pitch_rates = np.diff(att_df["pitch_deg"].values)
    airspeeds = hud_df["airspeed"].values[-len(pitch_rates):] # Align arrays
    
    min_len = min(len(pitch_rates), len(airspeeds))
    if min_len >= 5:
        p_rates = pitch_rates[-min_len:]
        a_speeds = airspeeds[-min_len:]
        
        cov_matrix = np.cov(p_rates, a_speeds)
        if cov_matrix.shape == (2, 2):
            covariance = cov_matrix[0, 1]
            
            mean_airspeed = np.mean(a_speeds)
            
            if mean_airspeed < 5.0 and covariance < -5.0:
                anomalies.append(AnomalyEvent(
                    event_type="AerodynamicStallDetected",
                    timestamp=timestamp,
                    severity="CRITICAL",
                    detail=f"Negative covariance between pitch rate and airspeed at low speeds (Cov: {covariance:.2f}, Airspeed: {mean_airspeed:.1f}m/s).",
                    recommendation="Loss of control effectiveness detected (Stall). Pitch down immediately to regain airspeed."
                ))

    return anomalies
