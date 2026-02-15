from __future__ import annotations

from dataclasses import dataclass

from app.dependencies import create_supabase_user_client


@dataclass(frozen=True)
class ChatSession:
    id: str
    user_id: str
    title: str | None
    conversation_id: str | None
    metadata: dict
    last_message_at: str | None
    created_at: str | None
    updated_at: str | None
    status: str | None


async def upsert_chat_session(
    *,
    user_id: str,
    user_jwt: str,
    conversation_id: str,
    title: str | None = None,
    metadata: dict | None = None,
    last_message_at: str | None = None,
    status: str | None = None,
) -> str | None:
    if not conversation_id:
        raise ValueError("conversation_id is required")
    client = await create_supabase_user_client(user_jwt)
    try:
        existing_resp = await (
            client.table("chat_sessions")
            .select("id, title, metadata, last_message_at, status")
            .eq("conversation_id", conversation_id)
            .eq("user_id", user_id)
            .maybe_single()
            .execute()
        )
        existing = existing_resp.data if existing_resp else None
        existing_id = existing.get("id") if existing else None

        existing_title = existing.get("title") if existing else None
        resolved_title = existing_title if existing_title else title

        resolved_status = status if status is not None else (existing.get("status") if existing else "active")

        payload = {
            "user_id": user_id,
            "conversation_id": conversation_id,
            "title": resolved_title,
            "metadata": metadata if metadata is not None else (existing.get("metadata") if existing else {}),
            "last_message_at": (
                last_message_at
                if last_message_at is not None
                else (existing.get("last_message_at") if existing else None)
            ),
            "status": resolved_status,
        }
        await client.table("chat_sessions").upsert(payload, on_conflict="conversation_id").execute()
        if existing_id:
            return existing_id
        id_resp = await (
            client.table("chat_sessions")
            .select("id")
            .eq("conversation_id", conversation_id)
            .eq("user_id", user_id)
            .maybe_single()
            .execute()
        )
        return id_resp.data.get("id") if id_resp and id_resp.data else None
    finally:
        await client.postgrest.aclose()


async def create_chat_session_stub(
    *,
    user_id: str,
    user_jwt: str,
    title: str | None = None,
    metadata: dict | None = None,
    last_message_at: str | None = None,
    status: str | None = None,
) -> str:
    """Create a chat_sessions row before an OpenAI conversation exists.

    `conversation_id` is nullable in the DB schema, so we can create a stub and later attach
    `conversation_id` when the run creates/uses a conversation.
    """
    client = await create_supabase_user_client(user_jwt)
    try:
        payload = {
            "user_id": user_id,
            "title": title,
            "metadata": metadata if metadata is not None else {},
            "last_message_at": last_message_at,
            "status": status if status is not None else "active",
        }
        response = await (
            client.table("chat_sessions")
            .insert(payload)
            .execute()
        )
        data = response.data if response else None
        if isinstance(data, dict):
            session_id = data.get("id")
        elif isinstance(data, list) and data:
            session_id = data[0].get("id")
        else:
            session_id = None
        if not session_id:
            raise RuntimeError("Failed to create chat session stub")
        return str(session_id)
    finally:
        await client.postgrest.aclose()


async def update_chat_session_by_id(
    *,
    session_id: str,
    user_id: str,
    user_jwt: str,
    conversation_id: str | None = None,
    title: str | None = None,
    metadata: dict | None = None,
    last_message_at: str | None = None,
    status: str | None = None,
) -> None:
    client = await create_supabase_user_client(user_jwt)
    try:
        payload: dict = {}
        if conversation_id is not None:
            payload["conversation_id"] = conversation_id
        if title is not None:
            payload["title"] = title
        if metadata is not None:
            payload["metadata"] = metadata
        if last_message_at is not None:
            payload["last_message_at"] = last_message_at
        if status is not None:
            payload["status"] = status
        if not payload:
            return

        await (
            client.table("chat_sessions")
            .update(payload)
            .eq("id", session_id)
            .eq("user_id", user_id)
            .execute()
        )
    finally:
        await client.postgrest.aclose()


async def get_chat_session_by_conversation_id(
    *,
    user_id: str,
    user_jwt: str,
    conversation_id: str,
):
    client = await create_supabase_user_client(user_jwt)
    try:
        response = await (
            client.table("chat_sessions")
            .select("*")
            .eq("conversation_id", conversation_id)
            .eq("user_id", user_id)
            .maybe_single()
            .execute()
        )
        return response.data if response else None
    finally:
        await client.postgrest.aclose()


async def list_active_sessions(user_jwt: str, limit: int = 100):
    client = await create_supabase_user_client(user_jwt)
    try:
        response = await (
            client.table("chat_sessions")
            .select("id, title, metadata, last_message_at, created_at, updated_at, status")
            .eq("status", "active")
            .order("updated_at", desc=True)
            .limit(limit)
            .execute()
        )
        return response.data if response else []
    finally:
        await client.postgrest.aclose()


async def get_chat_session(
    *,
    user_id: str,
    user_jwt: str,
    session_id: str,
):
    client = await create_supabase_user_client(user_jwt)
    try:
        response = await (
            client.table("chat_sessions")
            .select("*")
            .eq("id", session_id)
            .eq("user_id", user_id)
            .maybe_single()
            .execute()
        )
        return response.data if response else None
    finally:
        await client.postgrest.aclose()


async def delete_chat_session(
    *,
    user_id: str,
    user_jwt: str,
    session_id: str,
):
    client = await create_supabase_user_client(user_jwt)
    try:
        response = await (
            client.table("chat_sessions")
            .delete()
            .eq("id", session_id)
            .eq("user_id", user_id)
            .execute()
        )
        return response.data if response else []
    finally:
        await client.postgrest.aclose()
