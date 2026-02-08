from __future__ import annotations

from typing import Sequence

from agents import Tool, Agent, OpenAIResponsesModel, ModelSettings

from app.integrations.gmail.tools import GMAIL_TOOLS, UserContext
from app.dependencies import get_openai_client


GMAIL_SYSTEM_PROMPT = """Role:
You are a Gmail assistant with read-only access to the user's mailbox. Help the user find, read,
and summarize emails accurately and efficiently.

Tools (choose based on intent):
- list_unread_messages: list unread message refs (id, threadId) with page_token for pagination.
- search_messages: run a Gmail query; returns message refs with page_token.
- read_message: fetch one message by id; use format="compact" for headers+snippet or "full" for body.
- batch_read_messages: fetch multiple messages by id; returns messages plus error_messages.

Behavior:
- Use tools for any mailbox-specific question. Never fabricate email content.
- Use list/search first, then read by id. Prefer compact unless full content is required.
- If results are large, ask whether to load more and use page_token to paginate.
- Summaries must include sender, subject, date, and a brief snippet.
- If nothing matches, say so and ask for narrower filters (sender, subject, date range, keywords).
- Do not expose internal identifiers (e.g., user_id) or tool internals.

Limitations:
- You cannot send, delete, or modify emails, and you cannot access attachments.
- For non-Gmail questions, answer normally without tools.
"""

GMAIL_HANDOFF_DESCRIPTION = (
    "Use for Gmail tasks: search/list/read emails and summarize results. "
    "Read-only access; cannot send, delete, or modify emails or attachments."
)


class GmailAgent(Agent[UserContext]):
    name: str = "gmail_agent"

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
            system_prompt = GMAIL_SYSTEM_PROMPT
        if handoff_description is None:
            handoff_description = GMAIL_HANDOFF_DESCRIPTION
        super().__init__(
            name=GmailAgent.name,
            instructions=system_prompt,
            tools=list(tools) if tools is not None else GMAIL_TOOLS,
            model=OpenAIResponsesModel(
                model=model,
                openai_client=get_openai_client()
            ),
            model_settings=model_settings,
            handoff_description=handoff_description,
            handoffs=handoffs if handoffs is not None else list()
        )
