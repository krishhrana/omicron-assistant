from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from agents import FunctionTool, RunContextWrapper, function_tool

from app.integrations.gmail import services as gmail_services
from app.schemas.integration_schemas.gmail import GmailMessage
from app.core.enums import SupportedApps



@dataclass
class UserContext:
    user_id: str
    connected_apps: list[SupportedApps] | None = None


def _get_user_id(ctx: RunContextWrapper[UserContext]) -> str:
    user_id = ctx.context.user_id
    if not user_id:
        raise RuntimeError("Missing user_id in Gmail tool context")
    return user_id


async def _list_unread_messages_tool(
    ctx: RunContextWrapper[UserContext],
    max_results: int = 10,
    page_token: str | None = None,
) -> dict[str, Any]:
    """
    List unread Gmail messages for the current user.

    Returns lightweight message references (id, threadId) plus a page_token for pagination.
    Use this when you need to find unread emails before fetching full content.

    Args:
        max_results: Max number of message refs to return in this page.
        page_token: Token from a previous response to fetch the next page.

    Returns:
        dict: {"messages": [{"id": "...", "threadId": "..."}], "page_token": "..."}.
        page_token is None when there are no more pages.
    """
    result = await gmail_services.list_unread_messages(
        user_id=_get_user_id(ctx),
        max_results=max_results,
        page_token=page_token,
    )
    return result.model_dump()


async def _search_messages_tool(
    ctx: RunContextWrapper[UserContext],
    query: str,
    max_results: int = 10,
    page_token: str | None = None,
) -> dict[str, Any]:
    """
    Search Gmail using the standard Gmail query syntax.

    Example queries: "from:alice is:unread", "subject:\"invoice\" newer_than:7d",
    "has:attachment filename:pdf".

    Args:
        query: Gmail search query string.
        max_results: Max number of message refs to return in this page.
        page_token: Token from a previous response to fetch the next page.

    Returns:
        dict: {"messages": [{"id": "...", "threadId": "..."}], "page_token": "..."}.
        page_token is None when there are no more pages.
    """
    result = await gmail_services.search_messages(
        user_id=_get_user_id(ctx),
        query=query,
        max_results=max_results,
        page_token=page_token,
    )
    return result.model_dump()


async def _read_message_tool(
    ctx: RunContextWrapper[UserContext],
    message_id: str,
    format: Literal['compact', 'full'] = 'compact'
) -> GmailMessage:
    """
    Fetch a single Gmail message by ID.

    Use format="compact" for a fast metadata+snippet view; use format="full" for full body HTML
    (or escaped plain text wrapped in <pre> if no HTML part exists).

    Args:
        message_id: Gmail message ID.
        format: "compact" for headers+snippet, "full" for full content.

    Returns:
        dict with keys: id, thread_id, label_ids, from, to, subject, date, msg_body.
        msg_body is a snippet for compact, or full message body for full.
    """
    fn = gmail_services.read_message_compact if format == 'compact' else gmail_services.read_message_full
    result = await fn(_get_user_id(ctx), message_id)
    return result.model_dump()


async def _batch_read_messages_tool(
    ctx: RunContextWrapper[UserContext],
    messages_ids: list[str],
    format: Literal['compact', 'full'] = 'compact',
) -> dict[str, Any]:
    """
    Fetch multiple Gmail messages by ID in parallel.

    Useful after list/search when you need content for several messages at once.

    Args:
        messages_ids: List of Gmail message IDs.
        format: "compact" for headers+snippet, "full" for full content.

    Returns:
        dict with keys:
        - messages: list of GmailMessage dicts (see read_message).
        - error_messages: list of message IDs that failed to fetch.
    """
    result = await gmail_services.batch_read_messages(_get_user_id(ctx), messages_ids, format)
    return result.model_dump()


list_unread_messages_tool: FunctionTool = function_tool(
    _list_unread_messages_tool,
    name_override="list_unread_messages",
)
search_messages_tool: FunctionTool = function_tool(
    _search_messages_tool,
    name_override="search_messages",
)
read_message_tool: FunctionTool = function_tool(
    _read_message_tool,
    name_override="read_message",
)
batch_read_messages_tool: FunctionTool = function_tool(
    _batch_read_messages_tool,
    name_override="batch_read_messages",
)


GMAIL_TOOLS: list[FunctionTool] = [
    list_unread_messages_tool,
    search_messages_tool,
    read_message_tool,
    batch_read_messages_tool,
]
