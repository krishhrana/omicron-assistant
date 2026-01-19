from __future__ import annotations

from typing import Sequence

from agents import ModelSettings, OpenAIResponsesModel, Tool, Agent

from app.dependencies import get_openai_client
 

ORCHESTRATOR_SYSTEM_PROMPT = """Role:
You are the orchestrator for a multi-agent assistant. Your job is to understand the user's intent,
choose the right tools or hand off to a specialist agent, and ensure the user gets a correct,
useful response with minimal back-and-forth.

How to route:
- If a specialist agent clearly fits (e.g., Gmail tasks), hand off to that agent.
- If intent is ambiguous, ask a concise clarifying question before acting.
- If no specialist is needed, respond directly without using tools or handoffs.

Behavior:
- Be transparent about what you can and cannot do; do not invent capabilities.
- Prefer the smallest number of steps to solve the task.
- Avoid exposing internal IDs, tool internals, or system details.
- Summarize results succinctly and confirm next steps when appropriate.

Limitations:
- Do not perform actions outside your available tools/handoffs.
- Do not fabricate data; rely on tool outputs and user-provided info.
"""

ORCHESTRATOR_HANDOFF_DESCRIPTION = (
    "Route and coordinate user requests across available agents and tools. "
    "Use this agent when intent is unclear, when multiple domains are involved, "
    "or when a request needs triage before handing off to a specialist."
)

class OrchestratorAgent(Agent): 
    name: str = "orchestrator_agent"

    def __init__(
        self,
        system_prompt: str | None = None,
        tools: Sequence[Tool] | None = None,
        model: str | None = None,
        handoff_description: str | None = None,
        handoffs: Sequence[str] | None = None,
        model_settings: ModelSettings | None = None,
        
    ) -> None:
        if system_prompt is None:
            system_prompt = ORCHESTRATOR_SYSTEM_PROMPT
        if handoff_description is None:
            handoff_description = ORCHESTRATOR_HANDOFF_DESCRIPTION
        super().__init__(
            name=OrchestratorAgent.name,
            instructions=system_prompt,
            tools=list(tools) if tools is not None else list(),
            model=OpenAIResponsesModel(
                model=model,
                openai_client=get_openai_client()
            ),
            model_settings=model_settings,
            handoff_description=handoff_description,
            handoffs=handoffs if handoffs is not None else list()
        )
