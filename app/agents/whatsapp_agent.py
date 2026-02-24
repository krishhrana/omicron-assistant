from __future__ import annotations

from typing import Sequence

from agents import ModelSettings, OpenAIResponsesModel, Tool
from agents.mcp import MCPServer

from app.agents.base_agent import BaseAgent
from app.core.enums import SupportedApps
from app.dependencies import get_openai_client


WHATSAPP_SYSTEM_PROMPT = """Role:
You are a WhatsApp assistant that works through WhatsApp MCP tools.

Capabilities:
- Search contacts and chats.
- List and summarize message history.
- Send text and media messages when explicitly requested.
- Download media when needed.

Operating rules:
- Use MCP tools for all WhatsApp-specific facts and actions. Never fabricate message content.
- For send actions, verify recipient and content before sending.
- Ask for explicit confirmation before any high-impact send (financial, legal, or irreversible consequences).
- Keep outputs concise: show recipient/chat, timestamp, and the relevant message summary.
- If the request is not WhatsApp-related, hand back to the orchestrator.

Displaying results to User: 
- Do not reveal internal IDs to the user
- Use group chats or contant name when referring them
"""

WHATSAPP_HANDOFF_DESCRIPTION = (
    "Use for WhatsApp tasks via MCP: search contacts/chats, read and summarize messages, "
    "send messages/files, and download media."
)


class WhatsAppAgent(BaseAgent):
    name: str = SupportedApps.WHATSAPP.value
    CAN_GATHER_USER_DATA: bool = True

    def __init__(
        self,
        system_prompt: str | None = None,
        tools: Sequence[Tool] | None = None,
        model: str | None = None,
        handoff_description: str | None = None,
        handoffs: Sequence[str] | None = None,
        model_settings: ModelSettings | None = None,
        mcp_servers: Sequence[MCPServer] | None = None,
    ) -> None:
        if system_prompt is None:
            system_prompt = WHATSAPP_SYSTEM_PROMPT
        if handoff_description is None:
            handoff_description = WHATSAPP_HANDOFF_DESCRIPTION

        self.can_gather_user_data = self.CAN_GATHER_USER_DATA

        super().__init__(
            name=WhatsAppAgent.name,
            instructions=system_prompt,
            tools=list(tools) if tools is not None else list(),
            model=OpenAIResponsesModel(
                model=model,
                openai_client=get_openai_client(),
            ),
            model_settings=model_settings,
            handoff_description=handoff_description,
            handoffs=handoffs if handoffs is not None else list(),
            mcp_servers=list(mcp_servers) if mcp_servers is not None else list(),
        )
