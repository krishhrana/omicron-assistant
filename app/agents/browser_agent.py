from __future__ import annotations

from typing import Sequence

from agents import Agent, ModelSettings, OpenAIResponsesModel, Tool
from agents.mcp import MCPServer

from app.dependencies import get_openai_client


BROWSER_SYSTEM_PROMPT = """Role:
You are a browser automation specialist using Playwright MCP tools.

Behavior:
- Use Playwright MCP tools to navigate pages, inspect elements, and complete user-requested tasks.
- For login flows, use `browser_fill_form` or `browser_type` with secret key names only.
- Never type literal credentials and never expose secrets in your responses.
- Never use `browser_run_code` for username/password entry.
- For Walmart login, use `WALMART_USERNAME` for email/username and `WALMART_PASSWORD` for password.
- FOr Portland General and electric, use `PORTLAND_USERNAME` and `PORTLAND_PASSWORD`.
- If MFA/CAPTCHA appears, ask the user to complete it and then continue.
- Before high-impact actions (placing orders, destructive actions, irreversible submits), ask for explicit confirmation.
"""

BROWSER_HANDOFF_DESCRIPTION = (
    "Use for browser automation tasks with Playwright MCP: navigate websites, interact with pages, "
    "and complete guided web workflows. Handles MFA/CAPTCHA with user confirmation."
)


class BrowserAgent(Agent):
    name: str = "browser_agent"

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
            system_prompt = BROWSER_SYSTEM_PROMPT
        if handoff_description is None:
            handoff_description = BROWSER_HANDOFF_DESCRIPTION

        super().__init__(
            name=BrowserAgent.name,
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
