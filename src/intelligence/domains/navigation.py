import pandas as pd
import numpy as np
from typing import Dict, List
import logging
from .anomaly import AnomalyEvent

logger = logging.getLogger("sentinel.intelligence.domains.navigation")

class NavigationDetector:
    def __init__(self, velocity_disagreement_threshold: float = 2.0, altitude_disagreement_threshold: float = 10.0, max_speed: float = 50.0):
        self.vel_thresh = velocity_disagreement_threshold
        self.alt_thresh = altitude_disagreement_threshold
        self.max_speed = max_speed
        
    def detect(self, telemetry: Dict[str, pd.DataFrame]) -> List[AnomalyEvent]:
        anomalies = []
        
        if "positions" not in telemetry or telemetry["positions"].empty:
            return anomalies
            
        pos_df = telemetry["positions"]
        if len(pos_df) < 2:
            return anomalies
            
        latest = pos_df.iloc[-1]
        prev = pos_df.iloc[-2]
        timestamp = float(latest['timestamp'])
        dt = timestamp - prev['timestamp']
        
        # 1. Position jump detection (GPS spoofing/glitch)
        if dt > 0 and dt < 5.0: # Ensure valid dt and not a huge time gap
            # Simple Haversine or equirectangular approximation could be used. 
            # Assuming lat/lon in degrees, rough conversion: 1 deg ~ 111km
            dlat_m = (latest['lat'] - prev['lat']) * 111000
            dlon_m = (latest['lon'] - prev['lon']) * 111000 * np.cos(np.radians(latest['lat']))
            
            dist = np.sqrt(dlat_m**2 + dlon_m**2)
            speed = dist / dt
            
            if speed > self.max_speed:
                anomalies.append(AnomalyEvent(
                    event_type="GPSJump",
                    timestamp=timestamp,
                    severity="CRITICAL",
                    detail=f"Impossible position jump: {speed:.1f} m/s > {self.max_speed} m/s",
                    recommendation="Potential GPS spoofing or multi-path error. Switch to VIO/Dead Reckoning.",
                    domain="navigation"
                ))
                
        # 2. GPS-IMU Cross Validation (if we have enough history to smooth)
        if len(pos_df) >= 3:
            recent = pos_df.iloc[-3:]
            dt_recent = recent.iloc[-1]['timestamp'] - recent.iloc[0]['timestamp']
            
            if dt_recent > 0:
                dlat_m = (recent.iloc[-1]['lat'] - recent.iloc[0]['lat']) * 111000
                dlon_m = (recent.iloc[-1]['lon'] - recent.iloc[0]['lon']) * 111000 * np.cos(np.radians(recent.iloc[-1]['lat']))
                
                # GPS derived velocity
                gps_vx = dlat_m / dt_recent # Rough North
                gps_vy = dlon_m / dt_recent # Rough East
                
                # IMU reported velocity (from EKF, presumably)
                imu_vx = recent['vx'].mean()
                imu_vy = recent['vy'].mean()
                
                # Compare magnitudes
                gps_speed = np.sqrt(gps_vx**2 + gps_vy**2)
                imu_speed = np.sqrt(imu_vx**2 + imu_vy**2)
                
                if abs(gps_speed - imu_speed) > self.vel_thresh:
                    anomalies.append(AnomalyEvent(
                        event_type="VelocityDisagreement",
                        timestamp=timestamp,
                        severity="HIGH",
                        detail=f"GPS vs IMU velocity mismatch: |{gps_speed:.1f} - {imu_speed:.1f}| > {self.vel_thresh}",
                        recommendation="EKF divergence likely. Check GPS integrity.",
                        domain="navigation"
                    ))
                    
        # 3. Altitude divergence
        if "hud" in telemetry and not telemetry["hud"].empty:
            hud_df = telemetry["hud"]
            # Align timestamps
            idx = (np.abs(hud_df['timestamp'] - timestamp)).idxmin()
            if abs(hud_df.iloc[idx]['timestamp'] - timestamp) < 1.0:
                baro_climb = hud_df.iloc[idx].get('climb_rate', 0)
                gps_alt = latest.get('relative_alt', 0)
                prev_gps_alt = prev.get('relative_alt', 0)
                
                if dt > 0:
                    gps_climb = (gps_alt - prev_gps_alt) / dt
                    
                    if abs(gps_climb - baro_climb) > self.alt_thresh:
                        anomalies.append(AnomalyEvent(
                            event_type="AltitudeDisagreement",
                            timestamp=timestamp,
                            severity="MEDIUM",
                            detail=f"GPS vs Baro climb rate mismatch: |{gps_climb:.1f} - {baro_climb:.1f}|",
                            recommendation="Monitor altitude sensors.",
                            domain="navigation"
                        ))

        return anomalies
