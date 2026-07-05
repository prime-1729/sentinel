import pandas as pd
import numpy as np
from typing import Dict, List
import logging
from .anomaly import AnomalyEvent

logger = logging.getLogger("sentinel.intelligence.domains.electronic_warfare")

class EWDetector:
    def __init__(self, max_hdop: float = 5.0, sat_drop_threshold: int = 3, rssi_drop_dbm: float = 10.0):
        self.max_hdop = max_hdop
        self.sat_drop_threshold = sat_drop_threshold
        self.rssi_drop_dbm = rssi_drop_dbm
        
    def detect(self, telemetry: Dict[str, pd.DataFrame]) -> List[AnomalyEvent]:
        anomalies = []
        
        # 1. GPS Integrity Monitoring
        if "positions" in telemetry and not telemetry["positions"].empty:
            pos_df = telemetry["positions"]
            
            if len(pos_df) >= 3:
                latest = pos_df.iloc[-1]
                prev = pos_df.iloc[-3]  # Check drop over a slightly longer window
                timestamp = float(latest['timestamp'])
                
                # These might not exist in a simple position payload, but we'll try
                latest_sats = latest.get("satellites", -1)
                prev_sats = prev.get("satellites", -1)
                latest_hdop = latest.get("hdop", 0.0)
                
                if latest_sats != -1 and prev_sats != -1:
                    if (prev_sats - latest_sats) >= self.sat_drop_threshold:
                        anomalies.append(AnomalyEvent(
                            event_type="GPSJamming",
                            timestamp=timestamp,
                            severity="HIGH",
                            detail=f"Sudden loss of {prev_sats - latest_sats} satellites",
                            recommendation="Probable GPS jamming. Switch to local navigation.",
                            domain="ew"
                        ))
                        
                if latest_hdop > self.max_hdop:
                    anomalies.append(AnomalyEvent(
                        event_type="GPSDegraded",
                        timestamp=timestamp,
                        severity="MEDIUM",
                        detail=f"HDOP spiked to {latest_hdop} > {self.max_hdop}",
                        recommendation="GPS signal unreliable.",
                        domain="ew"
                    ))
                    
        # 2. Link Quality Monitoring
        # Assuming link quality might be in 'hud' or a dedicated 'comms' stream
        if "comms" in telemetry and not telemetry["comms"].empty:
            comms_df = telemetry["comms"]
            if len(comms_df) >= 2:
                latest = comms_df.iloc[-1]
                prev = comms_df.iloc[-2]
                dt = latest['timestamp'] - prev['timestamp']
                
                if dt > 0 and dt < 2.0:
                    latest_rssi = latest.get("rssi", 0)
                    prev_rssi = prev.get("rssi", 0)
                    
                    if (prev_rssi - latest_rssi) >= self.rssi_drop_dbm:
                        anomalies.append(AnomalyEvent(
                            event_type="RFJamming",
                            timestamp=float(latest['timestamp']),
                            severity="CRITICAL",
                            detail=f"Rapid RSSI drop of {prev_rssi - latest_rssi} dBm",
                            recommendation="Likely RF jamming attack. Execute loss-of-link procedure.",
                            domain="ew"
                        ))
                        
        return anomalies
