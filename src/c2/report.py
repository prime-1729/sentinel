import json
from dataclasses import asdict
from typing import List
import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), "..", "intelligence"))
from domains.anomaly import AnomalyEvent
import ollama


def generate_intelligence_report(
    telemetry: dict,
    anomalies: List[AnomalyEvent],
    mission_context: dict = None,
    mission_id: str = None
) -> str:
    """
    Generate a plain-language mission intelligence report
    using the deterministic QueryEngine and Ollama.
    """
    from telemetry_store import TelemetryStore
    from query_engine import QueryEngine, QueryIntent, QueryType
    from nlp import format_response
    import uuid

    # 1. Ensure we have a mission_id and drone_id
    if not mission_id:
        mission_id = f"mission_{uuid.uuid4().hex[:8]}"
    drone_id = "drone_upload"

    # 2. Ingest telemetry and anomalies into SQLite database
    store = TelemetryStore()
    try:
        # Check if the mission exists in the database
        mission_exists = store.get_mission(mission_id)
        if not mission_exists:
            store.create_mission(mission_id, drone_id)
            store.ingest_dataframes(telemetry, drone_id, mission_id)
            
            # Convert AnomalyEvent dataclasses to dictionaries for ingestion
            anomaly_dicts = []
            for a in anomalies:
                if hasattr(a, 'event_type'):
                    anomaly_dicts.append({
                        'timestamp': a.timestamp,
                        'event_type': a.event_type,
                        'severity': a.severity,
                        'detail': a.detail,
                        'recommendation': a.recommendation
                    })
                elif isinstance(a, dict):
                    anomaly_dicts.append(a)
            
            store.ingest_anomalies(anomaly_dicts, drone_id, mission_id)
            store.complete_mission(mission_id)
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"Failed to ingest telemetry in report generation: {e}")
    finally:
        store.close()

    # 3. Query via deterministic QueryEngine
    engine = QueryEngine()
    try:
        intent = QueryIntent(query_type=QueryType.MISSION_SUMMARY, mission_id=mission_id)
        result = engine.execute(intent)
        
        result_dict = {
            "success": result.success,
            "summary": result.summary,
            "evidence": result.evidence[:10],
            "confidence": result.confidence,
            "data_gaps": result.data_gaps,
            "correlations": result.correlations
        }
        
        if mission_context:
            result_dict["summary"]["mission_context"] = mission_context

        # 4. Generate report via LLM formatting
        report_question = (
            "Analyze the mission data and generate a concise After Action Intelligence Report with exactly these sections:\n\n"
            "MISSION STATUS\n"
            "One sentence. Was this mission nominal or did issues occur?\n\n"
            "OPERATIONAL SUMMARY\n"
            "2-3 sentences covering duration, altitude, distance, and flight performance.\n\n"
            "ANOMALIES DETECTED\n"
            "For each anomaly: what happened, why it matters operationally, and the recommended action before next mission. "
            "If no anomalies: state 'No anomalies detected. Mission nominal.'\n\n"
            "READINESS ASSESSMENT\n"
            "One sentence. Is this platform ready for next mission? Yes/No and why.\n\n"
            "Use direct military operations language. Be concise. No filler."
        )
        
        report = format_response(result_dict, report_question)
        return report
    finally:
        engine.close()


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
    from domains.anomaly import run_all_detectors

    conn = connect_to_drone()
    telemetry = extract_telemetry(conn, duration_seconds=20)
    anomalies = run_all_detectors(telemetry)

    print_full_report(telemetry, anomalies)