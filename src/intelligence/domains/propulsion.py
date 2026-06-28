import numpy as np
from typing import List
from .anomaly import AnomalyEvent

def detect(telemetry: dict) -> List[AnomalyEvent]:
    anomalies = []
    if "motors" not in telemetry or telemetry["motors"].empty:
        return anomalies
    if "vibration" not in telemetry or len(telemetry["vibration"]) < 10:
        return anomalies
        
    motors_df = telemetry["motors"]
    vib_df = telemetry["vibration"]
    timestamp = motors_df.iloc[-1].get("timestamp", 0)

    # 1. Motor Z-Score Imbalance
    rpms = [motors_df.iloc[-1].get(f"rpm_{i}", 0) for i in range(1, 5)]
    if any(rpms):
        mean_rpm = np.mean(rpms)
        std_rpm = np.std(rpms)
        if mean_rpm > 1000 and std_rpm > 0:
            z_scores = [(rpm - mean_rpm) / std_rpm for rpm in rpms]
            max_z = max(abs(z) for z in z_scores)
            
            if max_z > 1.5 and std_rpm > (0.10 * mean_rpm):
                anomalies.append(AnomalyEvent(
                    event_type="PropulsionZScoreAnomaly",
                    timestamp=timestamp,
                    severity="HIGH",
                    detail=f"Motor RPM imbalance detected. Max Z-score: {max_z:.2f} (Std: {std_rpm:.1f}, Mean: {mean_rpm:.1f}).",
                    recommendation="Possible damaged propeller or failing ESC. Land and inspect propulsion system."
                ))

    # 2. FFT Vibration Peak Extraction
    vib_z = vib_df["vibration_z"].values
    if len(vib_z) >= 10:
        fft_result = np.fft.rfft(vib_z)
        magnitudes = np.abs(fft_result)
        
        if len(magnitudes) > 1:
            peak_freq_idx = np.argmax(magnitudes[1:]) + 1
            peak_magnitude = magnitudes[peak_freq_idx]
            
            if peak_magnitude > 250.0:
                anomalies.append(AnomalyEvent(
                    event_type="ResonanceFrequencySpike",
                    timestamp=timestamp,
                    severity="CRITICAL",
                    detail=f"Harmonic resonance detected in airframe (FFT peak magnitude: {peak_magnitude:.1f}).",
                    recommendation="Airframe structural resonance or severe motor bearing wear. Abort mission."
                ))

    return anomalies
