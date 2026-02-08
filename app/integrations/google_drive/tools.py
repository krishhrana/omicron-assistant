from __future__ import annotations

from typing import Any

from agents import FunctionTool, RunContextWrapper, function_tool

from app.integrations.google_drive import services as drive_services
from app.utils.agent_utils import UserContext, get_user_id, get_user_jwt


async def _search_drive_files_tool(
    ctx: RunContextWrapper[UserContext],
    query: str,
    max_results: int = 10,
    page_token: str | None = None,
) -> dict[str, Any]:
    """
    Search Google Drive files using Drive query syntax.

    Example queries:
    - "name contains 'invoice' and mimeType = 'application/pdf'"
    - "modifiedTime > '2024-01-01T00:00:00' and trashed = false"

    Args:
        query: Drive query string (q).
        max_results: Max number of files to return in this page.
        page_token: Token from a previous response to fetch the next page.

    Returns:
        dict: {"files": [...], "nextPageToken": "..."} (raw Drive API response fields).
    """
    result = await drive_services.search_files(
        user_id=get_user_id(ctx),
        user_jwt=get_user_jwt(ctx),
        query=query,
        max_results=max_results,
        page_token=page_token,
    )
    return result.model_dump()


search_drive_files_tool: FunctionTool = function_tool(
    _search_drive_files_tool,
    name_override="search_drive_files",
)


GOOGLE_DRIVE_TOOLS: list[FunctionTool] = [
    search_drive_files_tool,
]
