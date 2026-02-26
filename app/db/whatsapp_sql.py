from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.dependencies import create_supabase_user_client


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def get_whatsapp_connection(*, user_id: str, user_jwt: str) -> dict[str, Any] | None:
    client = await create_supabase_user_client(user_jwt)
    try:
        response = await (
            client.table("whatsapp_connections")
            .select(
                "user_id, runtime_id, status, reauth_required, last_error_code, "
                "connected_at, disconnected_at, last_seen_at, created_at, updated_at"
            )
            .eq("user_id", user_id)
            .maybe_single()
            .execute()
        )
        return response.data if response else None
    finally:
        await client.postgrest.aclose()


async def upsert_whatsapp_connection(
    *,
    user_id: str,
    user_jwt: str,
    runtime_id: str | None,
    status: str,
    reauth_required: bool,
    last_error_code: str | None,
    connected_at: str | None,
    disconnected_at: str | None,
    last_seen_at: str | None = None,
) -> dict[str, Any]:
    client = await create_supabase_user_client(user_jwt)
    try:
        payload: dict[str, Any] = {
            "user_id": user_id,
            "runtime_id": runtime_id,
            "status": status,
            "reauth_required": reauth_required,
            "last_error_code": last_error_code,
            "connected_at": connected_at,
            "disconnected_at": disconnected_at,
            "last_seen_at": last_seen_at or _utc_now_iso(),
        }
        await client.table("whatsapp_connections").upsert(payload, on_conflict="user_id").execute()
        response = await (
            client.table("whatsapp_connections")
            .select(
                "user_id, runtime_id, status, reauth_required, last_error_code, "
                "connected_at, disconnected_at, last_seen_at, created_at, updated_at"
            )
            .eq("user_id", user_id)
            .maybe_single()
            .execute()
        )
        row = response.data if response else None
        if not row:
            raise RuntimeError("Failed to load WhatsApp connection row after upsert")
        return row
    finally:
        await client.postgrest.aclose()
