import numpy as np
import pandas as pd
from typing import Dict, List, Optional
import logging
from .anomaly import AnomalyEvent

logger = logging.getLogger("sentinel.intelligence.domains.propulsion")

class PropulsionDetector:
    def __init__(self, fft_threshold_multiplier: float = 3.0, rpm_imbalance_threshold: float = 1000.0, current_deviation_pct: float = 0.20):
        self.fft_threshold_multiplier = fft_threshold_multiplier
        self.rpm_imbalance_threshold = rpm_imbalance_threshold
        self.current_deviation_pct = current_deviation_pct

    def detect(self, telemetry: Dict[str, pd.DataFrame]) -> List[AnomalyEvent]:
        anomalies = []
        
        # 1. FFT Vibration Analysis
        if "vibration" in telemetry and not telemetry["vibration"].empty:
            vibe_df = telemetry["vibration"]
            if len(vibe_df) >= 64:
                # Need at least 64 samples for a meaningful FFT
                # Use the latest 64 samples
                recent_vibe = vibe_df.iloc[-64:]
                
                for axis in ['vibration_x', 'vibration_y', 'vibration_z']:
                    if axis in recent_vibe.columns:
                        signal = recent_vibe[axis].values
                        # Apply Hanning window
                        windowed_signal = signal * np.hanning(len(signal))
                        fft_result = np.fft.rfft(windowed_signal)
                        psd = np.abs(fft_result) ** 2
                        
                        median_psd = np.median(psd)
                        max_psd = np.max(psd)
                        
                        if max_psd > median_psd * self.fft_threshold_multiplier and max_psd > 0.5:
                            # Heuristic: Find which band the max_psd falls into
                            # Normally we'd use sample rate to find actual frequencies
                            # Here we just flag the high PSD
                            anomalies.append(AnomalyEvent(
                                event_type="VibrationAnomaly",
                                timestamp=float(recent_vibe.iloc[-1]['timestamp']),
                                severity="HIGH",
                                detail=f"High vibration detected on {axis}. Max PSD {max_psd:.2f} > threshold {median_psd * self.fft_threshold_multiplier:.2f}",
                                recommendation="Inspect propellers and motor bearings for damage.",
                                domain="propulsion"
                            ))
                            break # Only one vibe anomaly per tick is enough

        # 2. Motor Current Signature Analysis (MCSA)
        if "motors" in telemetry and not telemetry["motors"].empty:
            motors_df = telemetry["motors"]
            latest = motors_df.iloc[-1]
            
            rpm_1 = latest.get("rpm_1", 0)
            rpm_2 = latest.get("rpm_2", 0)
            rpm_3 = latest.get("rpm_3", 0)
            rpm_4 = latest.get("rpm_4", 0)
            
            # Quadcopter opposing motors: (1,3) and (2,4)
            if rpm_1 > 0 and rpm_3 > 0 and abs(rpm_1 - rpm_3) > self.rpm_imbalance_threshold:
                anomalies.append(AnomalyEvent(
                    event_type="MotorImbalance",
                    timestamp=float(latest['timestamp']),
                    severity="HIGH",
                    detail=f"RPM imbalance between motors 1 and 3: |{rpm_1} - {rpm_3}| > {self.rpm_imbalance_threshold}",
                    recommendation="Check ESCs and motors 1/3 for degradation.",
                    domain="propulsion"
                ))
                
            if rpm_2 > 0 and rpm_4 > 0 and abs(rpm_2 - rpm_4) > self.rpm_imbalance_threshold:
                anomalies.append(AnomalyEvent(
                    event_type="MotorImbalance",
                    timestamp=float(latest['timestamp']),
                    severity="HIGH",
                    detail=f"RPM imbalance between motors 2 and 4: |{rpm_2} - {rpm_4}| > {self.rpm_imbalance_threshold}",
                    recommendation="Check ESCs and motors 2/4 for degradation.",
                    domain="propulsion"
                ))
                
            # Current deviation
            currents = [latest.get(f"cur_{i}", 0) for i in range(1, 5)]
            valid_currents = [c for c in currents if c > 0]
            if valid_currents:
                mean_current = sum(valid_currents) / len(valid_currents)
                for i, c in enumerate(currents):
                    if c > 0 and abs(c - mean_current) > mean_current * self.current_deviation_pct:
                        anomalies.append(AnomalyEvent(
                            event_type="ElectricalDegradation",
                            timestamp=float(latest['timestamp']),
                            severity="MEDIUM",
                            detail=f"Motor {i+1} current ({c}A) deviates >{self.current_deviation_pct*100}% from mean ({mean_current:.2f}A)",
                            recommendation=f"Inspect motor {i+1} wiring and ESC.",
                            domain="propulsion"
                        ))
                        
        return anomalies
