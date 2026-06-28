import json
import logging
import ollama
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

# The prompt for intent parsing
PARSE_SYSTEM_PROMPT = """You are the NLP routing layer for the SENTINEL drone intelligence system.
Your job is to convert a user's natural language question into a strict JSON intent.

Available Query Types:
1. "mission_summary": General overview of the flight, total distance, max altitude, anomalies.
2. "anomaly_summary": Listing or counting anomalies (can filter by anomaly_type).
3. "time_window": What happened between specific timestamps.
4. "battery_profile": Deep analysis of battery health, discharge rate, voltage curve.
5. "waypoint_analysis": What happened at a specific waypoint (requires waypoint_id).
6. "route_deviation": General path following performance and deviations.
7. "attribute_query": A custom data query against specific tables and columns.

Database Schema for attribute queries:
{schema_str}

OUTPUT FORMAT:
You must return ONLY valid JSON. Do not include markdown formatting or explanations.
Format:
{{
    "query_type": "one_of_the_7_types_above",
    "mission_id": "optional_string",
    "time_start": 0.0,
    "time_end": 0.0,
    "waypoint_id": 0,
    "anomaly_type": "optional_string",
    "parameters": {{
        "table": "table_name",
        "columns": ["col1", "col2"],
        "filters": [{{"column": "col_name", "op": "=|!=|>|<|>=|<=", "value": "val"}}],
        "aggregations": [{{"func": "AVG|MIN|MAX|COUNT|SUM", "column": "col_name"}}],
        "group_by": "col_name",
        "order_by": "col_name",
        "order_desc": true,
        "limit": 50
    }}
}}
"""

FORMAT_SYSTEM_PROMPT = """You are the tactical briefing officer for the SENTINEL drone intelligence system.
You will receive a user's question and the raw structured data from the deterministic engineering core.
Your job is to write a concise, military-style operational briefing answering the question using ONLY the provided data.

RULES:
1. Do not invent facts, numbers, or events.
2. If the data shows an error or data gap, explain that to the user clearly.
3. Be concise and professional.
4. Highlight any 'correlations' found by the reasoning engine as critical findings.
5. Treat the words 'drone', 'robot', 'UAV', and 'asset' as completely synonymous. Do not correct the user on terminology.
"""

def parse_intent(
    question: str,
    schema_registry: dict,
    mission_id: str = None,
    session_context: Optional[dict] = None
) -> dict:
    """Uses LLM to parse natural language into a structured intent."""
    schema_str = json.dumps(schema_registry, indent=2)
    sys_prompt = PARSE_SYSTEM_PROMPT.format(schema_str=schema_str)
    
    # Format and append session context if present
    context_str = ""
    if session_context:
        history = session_context.get("history", [])
        facts = session_context.get("established_facts", {})
        if history:
            context_str += "\nCONVERSATIONAL HISTORY (last 5 exchanges):\n"
            for h in history[-5:]:
                context_str += f"Operator: {h['question']}\nSystem: {h['answer']}\n"
        if facts:
            context_str += f"\nESTABLISHED FACTS FROM PREVIOUS QUERIES:\n{json.dumps(facts, indent=2)}\n"
            
    if context_str:
        sys_prompt += f"\nUse the following conversational context to resolve pronouns, references, and missing details in the user's current question:\n{context_str}"
    
    # We pass mission_id as context so the LLM doesn't have to guess it if it's implied
    user_prompt = f"Question: {question}\nCurrent Mission Context: {mission_id}"
    
    try:
        resp = ollama.chat(
            model='llama3.2',
            messages=[
                {'role': 'system', 'content': sys_prompt},
                {'role': 'user', 'content': user_prompt}
            ],
            options={'temperature': 0.0} # We want deterministic JSON
        )
        content = resp['message']['content'].strip()
        
        # Strip markdown code blocks if the LLM adds them despite instructions
        if content.startswith("```json"):
            content = content[7:]
        if content.startswith("```"):
            content = content[3:]
        if content.endswith("```"):
            content = content[:-3]
            
        intent_dict = json.loads(content.strip())
        
        # Ensure mission_id is carried over if the LLM didn't extract one
        if not intent_dict.get("mission_id") and mission_id:
            intent_dict["mission_id"] = mission_id
            
        return intent_dict
        
    except json.JSONDecodeError as e:
        logger.error(f"LLM failed to output valid JSON: {e}\nRaw output: {content}")
        return {"query_type": "error", "error": "Failed to parse intent"}
    except Exception as e:
        logger.error(f"Ollama API error: {e}")
        return {"query_type": "error", "error": str(e)}


def format_response(
    result_dict: dict,
    question: str,
    session_context: Optional[dict] = None
) -> str:
    """Uses LLM to format raw QueryResult into a natural language briefing."""
    sys_prompt = FORMAT_SYSTEM_PROMPT
    
    # Format and append session context if present
    context_str = ""
    if session_context:
        history = session_context.get("history", [])
        facts = session_context.get("established_facts", {})
        if history:
            context_str += "\nCONVERSATIONAL HISTORY:\n"
            for h in history[-3:]:
                context_str += f"Operator: {h['question']}\nSystem: {h['answer']}\n"
        if facts:
            context_str += f"\nESTABLISHED FACTS:\n{json.dumps(facts, indent=2)}\n"
            
    if context_str:
        sys_prompt += f"\nUse this conversational context to shape the briefing narrative and reference previous answers if relevant:\n{context_str}"
        
    user_prompt = f"Original Question: {question}\nRaw Data:\n{json.dumps(result_dict, indent=2)}"
    
    try:
        resp = ollama.chat(
            model='llama3.2',
            messages=[
                {'role': 'system', 'content': sys_prompt},
                {'role': 'user', 'content': user_prompt}
            ],
            options={'temperature': 0.3}
        )
        return resp['message']['content'].strip()
    except Exception as e:
        logger.error(f"Ollama API error during formatting: {e}")
        return f"Error formatting response: {str(e)}\nRaw data: {result_dict}"
