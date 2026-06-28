import logging
from typing import List, Dict, Any, Optional

from query_engine import QueryEngine, QueryIntent, QueryType
from nlp import parse_intent, format_response

logger = logging.getLogger(__name__)


class MissionSession:
    """Tracks conversation history and context for a session."""
    def __init__(self, mission_id: str):
        self.mission_id = mission_id
        self.history: List[Dict[str, str]] = []
        self.query_history: List[tuple] = []
        self.established_facts: Dict[str, Any] = {}
        self.open_questions: List[str] = []
        
    def add_exchange(self, question: str, answer: str):
        self.history.append({"question": question, "answer": answer})

    def add_result(self, intent, result):
        self.query_history.append((intent, result))
        if result.success and result.confidence == "HIGH":
            # Keyed by query type / context to avoid flat merge conflicts
            q_type_str = intent.query_type.value
            self.established_facts[q_type_str] = result.summary


class SentinelAgent:
    """Orchestrator tying NLP to the deterministic engineering core."""
    
    def __init__(self, db_path: str = "data/sentinel.db"):
        self.engine = QueryEngine(db_path=db_path)
        self.sessions: Dict[str, MissionSession] = {}
        
    def get_session(self, session_id: str, mission_id: Optional[str] = None) -> MissionSession:
        if session_id not in self.sessions:
            self.sessions[session_id] = MissionSession(mission_id or "unknown")
        if mission_id and self.sessions[session_id].mission_id == "unknown":
            self.sessions[session_id].mission_id = mission_id
        return self.sessions[session_id]
        
    def ask(self, question: str, mission_id: str = None, session_id: str = None) -> str:
        """Process a natural language question end-to-end."""
        sess_key = session_id or mission_id or "default"
        session = self.get_session(sess_key, mission_id)
        schema = self.engine.get_schema()
        
        # 1. NLP Parse
        logger.info(f"Parsing intent for question: {question}")
        session_ctx = {
            "history": session.history,
            "established_facts": session.established_facts,
            "open_questions": session.open_questions
        }
        intent_dict = parse_intent(question, schema, mission_id=session.mission_id, session_context=session_ctx)
        
        if intent_dict.get("query_type") == "error":
            return f"System Error: Unable to understand the query. Detail: {intent_dict.get('error')}"
            
        try:
            q_type = QueryType(intent_dict["query_type"])
        except ValueError:
            # Fallback to attribute query if the LLM hallucinated a query type
            logger.warning(f"Unknown query_type {intent_dict.get('query_type')}. Falling back to ATTRIBUTE_QUERY.")
            q_type = QueryType.ATTRIBUTE_QUERY
            
        # If the LLM flattened the parameters (e.g. put 'table' at the root instead of in 'parameters'), fix it.
        params = intent_dict.get("parameters", {})
        if "table" in intent_dict and "table" not in params:
            params = {
                "table": intent_dict.get("table"),
                "columns": intent_dict.get("columns", []),
                "filters": intent_dict.get("filters", []),
                "aggregations": intent_dict.get("aggregations", []),
                "group_by": intent_dict.get("group_by"),
                "order_by": intent_dict.get("order_by"),
                "order_desc": intent_dict.get("order_desc", False),
                "limit": intent_dict.get("limit", 50)
            }
            
        intent = QueryIntent(
            query_type=q_type,
            mission_id=intent_dict.get("mission_id", session.mission_id),
            time_start=intent_dict.get("time_start"),
            time_end=intent_dict.get("time_end"),
            waypoint_id=intent_dict.get("waypoint_id"),
            anomaly_type=intent_dict.get("anomaly_type"),
            parameters=params
        )
        
        # 2. Execute Query
        logger.info(f"Executing QueryIntent: {intent}")
        result = self.engine.execute(intent)
        
        # Store result in session
        session.add_result(intent, result)
        
        # Convert dataclass to dict for LLM
        result_dict = {
            "success": result.success,
            "summary": result.summary,
            "evidence": result.evidence[:10], # Truncate evidence so we don't blow up context window
            "confidence": result.confidence,
            "data_gaps": result.data_gaps,
            "correlations": result.correlations
        }
        
        # 3. NLP Format
        logger.info("Formatting response...")
        answer = format_response(result_dict, question, session_context=session_ctx)
        
        session.add_exchange(question, answer)
        return answer
        
    def close(self):
        """Close the underlying query engine and database connection."""
        self.engine.close()
