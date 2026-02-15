from typing import Literal

from fastapi import APIRouter, Depends, HTTPException


from app.auth import AuthContext, get_auth_context
from app.dependencies import get_openai_client
from app.db.chat_sessions_sql import (
    delete_chat_session,
    get_chat_session,
    list_active_sessions,
    upsert_chat_session,
)
from app.schemas.endpoint_schemas.sessions import ChatSessionUpsertPayload


router = APIRouter()


def _normalize_conversation_item(item) -> dict | None:
    item_type = getattr(item, "type", None)
    if item_type == "message":
        role = getattr(item, "role", None)
        content_list = []
        for content in getattr(item, "content", []) or []:
            if hasattr(content, "model_dump"):
                content_list.append(content.model_dump())
            else:
                text = getattr(content, "text", None)
                if text is not None:
                    content_list.append({"type": getattr(content, "type", "text"), "text": text})
        return {"type": "message", "role": role, "content": content_list}
    if item_type == "function_call":
        return {"type": "tool_called", "tool": getattr(item, "name", None)}
    if item_type == "function_call_output":
        return {"type": "tool_output", "output": getattr(item, "output", None)}
    if item_type == "reasoning":
        if hasattr(item, "model_dump_json"):
            return {"type": "reasoning", "reasoning": item.model_dump_json()}
        return {"type": "reasoning", "reasoning": str(item)}
    return None


@router.get("/sessions")
async def list_sessions(
    limit: int = 100,
    auth_ctx: AuthContext = Depends(get_auth_context),
):
    return await list_active_sessions(auth_ctx.token, limit=limit)


@router.post("/sessions")
async def upsert_session(
    payload: ChatSessionUpsertPayload,
    auth_ctx: AuthContext = Depends(get_auth_context),
):
    await upsert_chat_session(
        user_id=auth_ctx.user_id,
        user_jwt=auth_ctx.token,
        conversation_id=payload.conversation_id,
        title=payload.title,
        metadata=payload.metadata,
        last_message_at=payload.last_message_at,
        status=payload.status,
    )
    return {"ok": True}


@router.delete("/sessions/{session_id}")
async def delete_session(
    session_id: str,
    auth_ctx: AuthContext = Depends(get_auth_context),
):
    session_row = await get_chat_session(
        user_id=auth_ctx.user_id,
        user_jwt=auth_ctx.token,
        session_id=session_id,
    )
    if not session_row:
        raise HTTPException(status_code=404, detail="Session not found")

    conversation_deleted = None
    conversation_delete_error = None
    conversation_id = session_row.get("conversation_id")
    if conversation_id:
        client = get_openai_client()
        try:
            result = await client.conversations.delete(conversation_id)
            conversation_deleted = getattr(result, "deleted", True)
        except Exception as exc:
            conversation_deleted = False
            conversation_delete_error = str(exc)

    deleted = await delete_chat_session(
        user_id=auth_ctx.user_id,
        user_jwt=auth_ctx.token,
        session_id=session_id,
    )
    deleted_ids = [row.get("id") for row in deleted] if isinstance(deleted, list) else []
    return {
        "deleted_ids": deleted_ids,
        "conversation_deleted": conversation_deleted,
        "conversation_delete_error": conversation_delete_error,
    }


@router.get("/sessions/{session_id}/history")
async def get_session_history(
    session_id: str,
    limit: int = 100,
    order: Literal["asc", "desc"] = "asc",
    after: str | None = None,
    auth_ctx: AuthContext = Depends(get_auth_context),
):
    session_row = await get_chat_session(
        user_id=auth_ctx.user_id,
        user_jwt=auth_ctx.token,
        session_id=session_id,
    )
    if not session_row:
        raise HTTPException(status_code=404, detail="Session not found")

    conversation_id = session_row.get("conversation_id")
    if not conversation_id:
        raise HTTPException(status_code=400, detail="Session has no conversation_id")

    client = get_openai_client()
    paginator = await client.conversations.items.list(
        conversation_id,
        limit=limit,
        order=order,
        after=after,
    )
    data = []
    raw_count = 0
    last_item_id = None
    async for item in paginator:
        print(item)
        raw_count += 1
        last_item_id = getattr(item, "id", None)
        normalized = _normalize_conversation_item(item)
        if normalized is not None:
            data.append(normalized)
    next_after = last_item_id if raw_count == limit else None
    return {"data": data, "next_after": next_after}
