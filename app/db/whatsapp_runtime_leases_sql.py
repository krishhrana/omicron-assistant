from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.dependencies import create_supabase_user_client


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


_LEASE_SELECT_COLUMNS = (
    "user_id, runtime_id, runtime_generation, bridge_base_url, mcp_url, "
    "controller_state, desired_state, lease_expires_at, last_touched_at, "
    "last_error_code, last_error_at, created_at, updated_at"
)


async def get_whatsapp_runtime_lease(
    *,
    user_id: str,
    user_jwt: str,
) -> dict[str, Any] | None:
    client = await create_supabase_user_client(user_jwt)
    try:
        response = await (
            client.table("whatsapp_runtime_leases")
            .select(_LEASE_SELECT_COLUMNS)
            .eq("user_id", user_id)
            .maybe_single()
            .execute()
        )
        return response.data if response else None
    finally:
        await client.postgrest.aclose()


async def upsert_whatsapp_runtime_lease(
    *,
    user_id: str,
    user_jwt: str,
    runtime_id: str,
    runtime_generation: int,
    bridge_base_url: str,
    mcp_url: str,
    controller_state: str,
    lease_expires_at: str,
    desired_state: str = "warm",
    last_touched_at: str | None = None,
    last_error_code: str | None = None,
    last_error_at: str | None = None,
) -> dict[str, Any]:
    client = await create_supabase_user_client(user_jwt)
    try:
        payload: dict[str, Any] = {
            "user_id": user_id,
            "runtime_id": runtime_id,
            "runtime_generation": runtime_generation,
            "bridge_base_url": bridge_base_url,
            "mcp_url": mcp_url,
            "controller_state": controller_state,
            "desired_state": desired_state,
            "lease_expires_at": lease_expires_at,
            "last_touched_at": last_touched_at or _utc_now_iso(),
            "last_error_code": last_error_code,
            "last_error_at": last_error_at,
        }
        await (
            client.table("whatsapp_runtime_leases")
            .upsert(payload, on_conflict="user_id")
            .execute()
        )
        response = await (
            client.table("whatsapp_runtime_leases")
            .select(_LEASE_SELECT_COLUMNS)
            .eq("user_id", user_id)
            .maybe_single()
            .execute()
        )
        row = response.data if response else None
        if not row:
            raise RuntimeError("Failed to load whatsapp_runtime_leases row after upsert")
        return row
    finally:
        await client.postgrest.aclose()


async def touch_whatsapp_runtime_lease(
    *,
    user_id: str,
    user_jwt: str,
    lease_expires_at: str,
    controller_state: str | None = None,
) -> dict[str, Any]:
    client = await create_supabase_user_client(user_jwt)
    try:
        patch: dict[str, Any] = {
            "lease_expires_at": lease_expires_at,
            "last_touched_at": _utc_now_iso(),
        }
        if controller_state is not None:
            patch["controller_state"] = controller_state

        await (
            client.table("whatsapp_runtime_leases")
            .update(patch)
            .eq("user_id", user_id)
            .execute()
        )
        response = await (
            client.table("whatsapp_runtime_leases")
            .select(_LEASE_SELECT_COLUMNS)
            .eq("user_id", user_id)
            .maybe_single()
            .execute()
        )
        row = response.data if response else None
        if not row:
            raise RuntimeError("Failed to load whatsapp_runtime_leases row after touch")
        return row
    finally:
        await client.postgrest.aclose()


async def update_whatsapp_runtime_lease_state(
    *,
    user_id: str,
    user_jwt: str,
    controller_state: str,
    desired_state: str | None = None,
    last_error_code: str | None = None,
    last_error_at: str | None = None,
) -> dict[str, Any] | None:
    client = await create_supabase_user_client(user_jwt)
    try:
        patch: dict[str, Any] = {
            "controller_state": controller_state,
            "last_touched_at": _utc_now_iso(),
            "last_error_code": last_error_code,
            "last_error_at": last_error_at,
        }
        if desired_state is not None:
            patch["desired_state"] = desired_state

        await (
            client.table("whatsapp_runtime_leases")
            .update(patch)
            .eq("user_id", user_id)
            .execute()
        )
        response = await (
            client.table("whatsapp_runtime_leases")
            .select(_LEASE_SELECT_COLUMNS)
            .eq("user_id", user_id)
            .maybe_single()
            .execute()
        )
        return response.data if response else None
    finally:
        await client.postgrest.aclose()


async def delete_whatsapp_runtime_lease(
    *,
    user_id: str,
    user_jwt: str,
) -> list[dict[str, Any]]:
    client = await create_supabase_user_client(user_jwt)
    try:
        response = await (
            client.table("whatsapp_runtime_leases")
            .delete()
            .eq("user_id", user_id)
            .execute()
        )
        return response.data if response else []
    finally:
        await client.postgrest.aclose()
