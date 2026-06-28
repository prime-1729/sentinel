import json
import logging
from typing import List, Dict, Any
import ollama
from rag import rag
from tools import OLLAMA_TOOLS, TOOL_MAP

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are SENTINEL, an advanced AI analyst for autonomous drone operations.
Your job is to answer the operator's questions by querying the telemetry database using your available tools.

CRITICAL INSTRUCTIONS:
1. You have access to a suite of tools. Use them! Do not guess metrics.
2. If the user asks for a summary, FIRST call get_mission_stats, then get_anomalies to understand what happened.
3. If the user asks about the path, call get_flight_path.
4. If you need specific metrics not covered by the main tools, call query_sql.
5. If a tool returns an error or empty data, try a different approach.
6. When writing your final briefing, use clear, professional, military-style language.
7. Always cite the data you found (e.g. "Duration was 45.2 seconds", "3 IdleDrift anomalies detected").
"""

class ReActAgent:
    def __init__(self, model: str = "qwen3"):
        self.model = model
        
    def ask(self, question: str, mission_id: str = None, session_id: str = None, max_steps: int = 8) -> str:
        """
        Process a natural language query using the ReAct loop pattern.
        """
        # 1. Retrieve background context from RAG
        rag_context = rag.retrieve_context(question)
        
        # 2. Build the initial prompt
        context_msg = f"BACKGROUND KNOWLEDGE (Use this to understand SENTINEL terms):\n{rag_context}"
        if mission_id:
            context_msg += f"\n\nCURRENT MISSION ID: {mission_id}\nUse this ID when calling tools."
            
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "system", "content": context_msg},
            {"role": "user", "content": question}
        ]
        
        print(f"\n[SENTINEL AGENT] Starting analysis for query: '{question}'")
        
        # 3. Enter the ReAct loop
        for step in range(max_steps):
            print(f"  ↳ Step {step+1}: Thinking...")
            
            try:
                response = ollama.chat(
                    model=self.model,
                    messages=messages,
                    tools=OLLAMA_TOOLS
                )
            except Exception as e:
                error_msg = f"Model execution failed: {e}"
                print(f"  ❌ {error_msg}")
                return error_msg
                
            msg = response.message
            
            # If the model didn't call any tools, it believes it has the final answer
            if not msg.tool_calls or len(msg.tool_calls) == 0:
                print(f"  ✓ Analysis complete.")
                return msg.content
                
            # Otherwise, the model wants to call tools. We must execute them and return results.
            messages.append(msg) # Append the assistant's tool call message
            
            for tool_call in msg.tool_calls:
                func_name = tool_call.function.name
                func_args = tool_call.function.arguments
                
                print(f"  ⚙️ Calling tool: {func_name}({json.dumps(func_args)})")
                
                if func_name not in TOOL_MAP:
                    result_json = json.dumps({"error": f"Unknown tool: {func_name}"})
                else:
                    try:
                        # Execute the python function mapped to this tool
                        func = TOOL_MAP[func_name]
                        result = func(**func_args)
                        result_json = json.dumps(result)
                    except Exception as e:
                        result_json = json.dumps({"error": f"Tool execution failed: {str(e)}"})
                        
                print(f"  ← Tool returned {len(result_json)} bytes of data")
                
                # Append the tool's result back into the conversation history
                messages.append({
                    "role": "tool",
                    "content": result_json,
                    "name": func_name
                })
                
        # If we exit the loop, we hit the step limit
        print(f"  ⚠️ Reached max steps ({max_steps}) without final answer.")
        
        # Do one final prompt forcing an answer based on whatever data we gathered
        messages.append({
            "role": "user",
            "content": "You have reached the maximum number of tool calls. Please provide the best answer you can based on the data gathered so far."
        })
        
        final_response = ollama.chat(model=self.model, messages=messages)
        return final_response.message.content

if __name__ == "__main__":
    # Test the agent
    agent = ReActAgent()
    # Replace mission_live with an actual mission ID in your DB to test
    print("\n\nFINAL ANSWER:\n", agent.ask("Give me a summary of the mission and what anomalies occurred.", mission_id="mission_live"))
