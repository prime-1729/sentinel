import json
from dataclasses import asdict
from typing import List
from anomaly import AnomalyEvent
import ollama


def generate_intelligence_report(
    telemetry: dict,
    anomalies: List[AnomalyEvent],
    mission_context: dict = None
) -> str:
    """
    Generate a plain-language mission intelligence report
    using Ollama. This is SENTINEL's core output.
    """

    positions = telemetry['positions']
    battery = telemetry['battery']
    hud = telemetry['hud']

    # Build structured mission summary
    mission_summary = {}

    if len(positions) > 0:
        duration = positions['timestamp'].max() - positions['timestamp'].min()
        mission_summary['duration_seconds'] = round(duration, 1)
        mission_summary['max_altitude_metres'] = round(
            positions['relative_alt'].max(), 1
        )

    if len(hud) > 0:
        mission_summary['max_groundspeed_ms'] = round(
            hud['groundspeed'].max(), 1
        )
        mission_summary['max_climb_rate_ms'] = round(
            hud['climb_rate'].max(), 1
        )
        mission_summary['average_throttle_pct'] = round(
            hud['throttle_pct'].mean(), 1
        )

    if len(battery) > 0:
        mission_summary['battery_start_pct'] = int(
            battery['remaining_pct'].iloc[0]
        )
        mission_summary['battery_end_pct'] = int(
            battery['remaining_pct'].iloc[-1]
        )
        mission_summary['voltage_min'] = round(battery['voltage'].min(), 2)
        mission_summary['voltage_max'] = round(battery['voltage'].max(), 2)

    # Format anomalies for the prompt
    anomaly_list = []
    for a in anomalies:
        anomaly_list.append({
            'type': a.event_type,
            'severity': a.severity,
            'detail': a.detail,
            'recommendation': a.recommendation
        })

    mission_summary['anomalies_detected'] = len(anomalies)
    mission_summary['anomaly_breakdown'] = anomaly_list

    # Add optional mission context
    if mission_context:
        mission_summary['mission_context'] = mission_context

    prompt = f"""You are SENTINEL, a mission intelligence system for autonomous drone operations.

Analyse the following drone mission data and generate a concise After Action Intelligence Report 
for an operations commander.

MISSION DATA:
{json.dumps(mission_summary, indent=2)}

Generate a report with exactly these sections:

MISSION STATUS
One sentence. Was this mission nominal or did issues occur?

OPERATIONAL SUMMARY  
2-3 sentences covering duration, altitude, and flight performance.

ANOMALIES DETECTED
For each anomaly: what happened, why it matters operationally, 
and the recommended action before next mission.
If no anomalies: state "No anomalies detected. Mission nominal."

READINESS ASSESSMENT
One sentence. Is this platform ready for next mission? Yes/No and why.

Use direct military operations language. Be concise. No filler."""

    response = ollama.chat(
        model='llama3.2',
        messages=[{"role": "user", "content": prompt}],
    )
    return response['message']['content']


def print_full_report(telemetry: dict, anomalies: List[AnomalyEvent]):
    """
    Print the complete SENTINEL intelligence report.
    """
    print("\n" + "=" * 60)
    print("SENTINEL AFTER ACTION INTELLIGENCE REPORT")
    print("=" * 60)

    report = generate_intelligence_report(telemetry, anomalies)
    print(report)
    print("=" * 60)


if __name__ == "__main__":
    from connect import connect_to_drone
    from telemetry import extract_telemetry
    from anomaly import run_all_detectors

    conn = connect_to_drone()
    telemetry = extract_telemetry(conn, duration_seconds=20)
    anomalies = run_all_detectors(telemetry)

    print_full_report(telemetry, anomalies)