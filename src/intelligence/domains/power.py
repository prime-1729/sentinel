import pandas as pd
import numpy as np
from typing import Dict, List
import logging
from .anomaly import AnomalyEvent

logger = logging.getLogger("sentinel.intelligence.domains.power")

class PowerDetector:
    def __init__(self, impedance_threshold: float = 0.05, critical_voltage_per_cell: float = 3.3, num_cells: int = 3):
        self.impedance_threshold = impedance_threshold
        self.critical_voltage = critical_voltage_per_cell * num_cells
        
    def detect(self, telemetry: Dict[str, pd.DataFrame]) -> List[AnomalyEvent]:
        anomalies = []
        
        if "battery" not in telemetry or telemetry["battery"].empty:
            return anomalies
            
        batt_df = telemetry["battery"]
        latest = batt_df.iloc[-1]
        timestamp = float(latest['timestamp'])
        
        voltage = latest.get("voltage", 0)
        current = latest.get("current", 0)
        remaining = latest.get("remaining_pct", 100)
        
        # 1. Critical voltage / capacity detection
        if remaining < 20.0 or (voltage > 0 and voltage < self.critical_voltage):
            anomalies.append(AnomalyEvent(
                event_type="CriticalBattery",
                timestamp=timestamp,
                severity="CRITICAL",
                detail=f"Battery critically low: {remaining}% / {voltage:.1f}V",
                recommendation="Return to launch or emergency land immediately.",
                domain="power"
            ))
            
        # 2. Internal impedance estimation
        if len(batt_df) >= 10:
            recent = batt_df.iloc[-10:]
            # We need variations in current to estimate impedance (dV/dI)
            d_voltage = recent['voltage'].diff().dropna()
            d_current = recent['current'].diff().dropna()
            
            # Filter out near-zero changes in current to avoid division by zero
            valid_idx = np.abs(d_current) > 0.5
            if valid_idx.any():
                d_v = d_voltage[valid_idx]
                d_i = d_current[valid_idx]
                
                # Impedance = -dV / dI (voltage drops as current increases)
                impedances = -d_v / d_i
                
                # Filter negative impedances (non-physical for simple discharge)
                valid_imp = impedances[impedances > 0]
                
                if len(valid_imp) > 0:
                    avg_impedance = valid_imp.mean()
                    if avg_impedance > self.impedance_threshold:
                        anomalies.append(AnomalyEvent(
                            event_type="PowerDegradation",
                            timestamp=timestamp,
                            severity="HIGH",
                            detail=f"High internal impedance detected: {avg_impedance:.3f} Ohms",
                            recommendation="Battery may be damaged or swelling. Replace pack.",
                            domain="power"
                        ))
                        
        # 3. Voltage drop under load check (simplified Peukert's related check)
        # If current is high but voltage drops extremely fast, flag it
        if len(batt_df) >= 2:
            prev = batt_df.iloc[-2]
            dt = timestamp - prev['timestamp']
            if dt > 0:
                v_drop_rate = (prev['voltage'] - voltage) / dt
                if current > 10.0 and v_drop_rate > 0.5: # Drop of 0.5V per second is severe
                    anomalies.append(AnomalyEvent(
                        event_type="VoltageSag",
                        timestamp=timestamp,
                        severity="MEDIUM",
                        detail=f"Severe voltage sag under load: {v_drop_rate:.2f} V/s",
                        recommendation="Reduce throttle. Inspect battery health.",
                        domain="power"
                    ))

        return anomalies
