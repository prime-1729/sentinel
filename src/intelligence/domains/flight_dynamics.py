import pandas as pd
import numpy as np
from typing import Dict, List
import logging
from .anomaly import AnomalyEvent

logger = logging.getLogger("sentinel.intelligence.domains.flight_dynamics")

class FlightDynamicsDetector:
    def __init__(self, stall_throttle_threshold: float = 70.0, rate_limit_deg_s: float = 45.0, wind_shear_threshold: float = 15.0):
        self.stall_throttle = stall_throttle_threshold
        self.rate_limit = rate_limit_deg_s
        self.wind_shear_threshold = wind_shear_threshold
        
    def detect(self, telemetry: Dict[str, pd.DataFrame]) -> List[AnomalyEvent]:
        anomalies = []
        
        # 1. Commanded vs achieved attitude analysis (Stall/Structural issue)
        if "hud" in telemetry and not telemetry["hud"].empty:
            hud_df = telemetry["hud"]
            
            if len(hud_df) >= 5:
                recent = hud_df.iloc[-5:]
                avg_throttle = recent['throttle_pct'].mean()
                avg_climb = recent['climb_rate'].mean()
                
                # If throttle is very high but we are not climbing or even falling
                if avg_throttle > self.stall_throttle and avg_climb <= 0.5:
                    anomalies.append(AnomalyEvent(
                        event_type="PropulsionStall",
                        timestamp=float(recent.iloc[-1]['timestamp']),
                        severity="CRITICAL",
                        detail=f"High throttle ({avg_throttle:.1f}%) but no climb ({avg_climb:.1f} m/s)",
                        recommendation="Likely stall, overload, or severe motor failure.",
                        domain="dynamics"
                    ))
                    
                # Wind shear detection
                latest_hud = hud_df.iloc[-1]
                airspeed = latest_hud.get("airspeed", 0)
                groundspeed = latest_hud.get("groundspeed", 0)
                
                if abs(airspeed - groundspeed) > self.wind_shear_threshold:
                    anomalies.append(AnomalyEvent(
                        event_type="WindShear",
                        timestamp=float(latest_hud['timestamp']),
                        severity="MEDIUM",
                        detail=f"Airspeed ({airspeed:.1f}) vs Groundspeed ({groundspeed:.1f}) diff > {self.wind_shear_threshold}",
                        recommendation="Prepare for turbulence, maintain altitude.",
                        domain="dynamics"
                    ))
                    
        # 2. Attitude rate monitoring
        if "attitude" in telemetry and not telemetry["attitude"].empty:
            att_df = telemetry["attitude"]
            if len(att_df) >= 2:
                latest = att_df.iloc[-1]
                prev = att_df.iloc[-2]
                dt = latest['timestamp'] - prev['timestamp']
                
                if dt > 0:
                    roll_rate = abs(latest['roll_deg'] - prev['roll_deg']) / dt
                    pitch_rate = abs(latest['pitch_deg'] - prev['pitch_deg']) / dt
                    yaw_diff = abs(latest['yaw_deg'] - prev['yaw_deg'])
                    yaw_diff = min(yaw_diff, 360.0 - yaw_diff)
                    yaw_rate = yaw_diff / dt
                    
                    max_rate = max(roll_rate, pitch_rate, yaw_rate)
                    if max_rate > self.rate_limit:
                        anomalies.append(AnomalyEvent(
                            event_type="ControlInstability",
                            timestamp=float(latest['timestamp']),
                            severity="HIGH",
                            detail=f"Extreme attitude rate: {max_rate:.1f} deg/s",
                            recommendation="Switch to stabilized mode immediately.",
                            domain="dynamics"
                        ))
                        
        return anomalies
