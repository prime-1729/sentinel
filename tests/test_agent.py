import os
import sys
import unittest
import pytest
import sqlite3
import pandas as pd
from typing import Dict, Any

# Ensure src is in python path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src')))

from telemetry_store import TelemetryStore
from query_engine import QueryEngine, QueryIntent, QueryType, QueryResult
from sentinel_agent import MissionSession, SentinelAgent

def test_mission_session_initialization():
    session = MissionSession(mission_id="test_mission")
    assert session.mission_id == "test_mission"
    assert len(session.history) == 0
    assert len(session.query_history) == 0
    assert len(session.established_facts) == 0
    assert len(session.open_questions) == 0

def test_mission_session_add_exchange():
    session = MissionSession(mission_id="test_mission")
    session.add_exchange("what is the status?", "The status is nominal.")
    assert len(session.history) == 1
    assert session.history[0] == {"question": "what is the status?", "answer": "The status is nominal."}

def test_mission_session_add_result_high_confidence():
    session = MissionSession(mission_id="test_mission")
    intent = QueryIntent(query_type=QueryType.MISSION_SUMMARY, mission_id="test_mission")
    result = QueryResult(
        success=True,
        summary={"duration_seconds": 120.0, "max_altitude_m": 50.0},
        confidence="HIGH"
    )
    session.add_result(intent, result)
    assert len(session.query_history) == 1
    assert session.query_history[0] == (intent, result)
    assert "mission_summary" in session.established_facts
    assert session.established_facts["mission_summary"] == {"duration_seconds": 120.0, "max_altitude_m": 50.0}

def test_mission_session_add_result_low_confidence_no_fact():
    session = MissionSession(mission_id="test_mission")
    intent = QueryIntent(query_type=QueryType.MISSION_SUMMARY, mission_id="test_mission")
    result = QueryResult(
        success=True,
        summary={"duration_seconds": 120.0, "max_altitude_m": 50.0},
        confidence="LOW"
    )
    session.add_result(intent, result)
    assert len(session.query_history) == 1
    assert "mission_summary" not in session.established_facts

def test_sentinel_agent_get_session():
    # Use in-memory DB or temporary file DB for testing
    agent = SentinelAgent(db_path=":memory:")
    
    # Retrieve new session
    session = agent.get_session("test_sess", "test_mission")
    assert session.mission_id == "test_mission"
    
    # Retrieve existing session
    session2 = agent.get_session("test_sess")
    assert session2 is session
    assert session2.mission_id == "test_mission"
    
    # Handle unknown mission update
    session_unk = agent.get_session("unk_sess")
    assert session_unk.mission_id == "unknown"
    
    # Retrieve with mission update
    session_upd = agent.get_session("unk_sess", "known_mission")
    assert session_upd is session_unk
    assert session_upd.mission_id == "known_mission"

@pytest.mark.skipif(not os.path.exists("/usr/bin/ollama") and not os.path.exists("/usr/local/bin/ollama"), reason="Ollama not available")
def test_sentinel_agent_end_to_end_integration():
    # Create a temporary database and ingest some test data so the agent has something to query
    db_path = "data/temp_test_agent.db"
    if os.path.exists(db_path):
        try:
            os.remove(db_path)
        except OSError:
            pass
        
    store = TelemetryStore(db_path=db_path)
    store.create_mission("test_agent_mission", "drone_1")
    
    # Ingest 1 anomaly event
    anomaly_dicts = [{
        'timestamp': 1000.0,
        'event_type': 'BatteryStress',
        'severity': 'CRITICAL',
        'detail': 'Battery voltage dropped suddenly.',
        'recommendation': 'Land immediately.'
    }]
    store.ingest_anomalies(anomaly_dicts, "drone_1", "test_agent_mission")
    store.close()
    
    agent = SentinelAgent(db_path=db_path)
    try:
        # Run a query asking for anomalies
        ans1 = agent.ask("show me all anomalies", mission_id="test_agent_mission", session_id="agent_sess")
        assert "BatteryStress" in ans1 or "battery" in ans1.lower()
        
        # Verify conversational history was stored
        session = agent.get_session("agent_sess")
        assert len(session.history) == 1
        assert "BatteryStress" in session.history[0]["answer"] or "battery" in session.history[0]["answer"].lower()
        
        # Run a follow-up query to verify context is passed (e.g. "what was its severity?")
        ans2 = agent.ask("what was its severity?", mission_id="test_agent_mission", session_id="agent_sess")
        assert "critical" in ans2.lower()
        
    finally:
        agent.close()
        if os.path.exists(db_path):
            try:
                os.remove(db_path)
            except OSError:
                pass
        for ext in ["-wal", "-shm"]:
            path = db_path + ext
            if os.path.exists(path):
                try:
                    os.remove(path)
                except OSError:
                    pass
