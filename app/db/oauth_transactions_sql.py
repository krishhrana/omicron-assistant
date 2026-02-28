from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.dependencies import create_supabase_service_client


OAUTH_PROVIDER_GMAIL = "gmail"
OAUTH_PROVIDER_GOOGLE_DRIVE = "google-drive"

OAUTH_STATUS_PENDING = "pending"
OAUTH_STATUS_CONNECTED = "connected"
OAUTH_STATUS_ERROR = "error"
OAUTH_STATUS_EXPIRED = "expired"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _extract_single_row(response: Any) -> dict[str, Any] | None:
    if response is None:
        return None

    data = getattr(response, "data", None)
    if isinstance(data, dict):
        return data
    if isinstance(data, list):
        if not data:
            return None
        first = data[0]
        return first if isinstance(first, dict) else None
    return None


def _parse_iso_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None

    normalized = value
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"

    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None

    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


async def create_oauth_transaction(
    *,
    provider: str,
    user_id: str,
    return_to: str,
    expires_at: str,
) -> dict[str, Any]:
    client = await create_supabase_service_client()
    try:
        response = await (
            client.table("oauth_transactions")
            .insert(
                {
                    "provider": provider,
                    "user_id": user_id,
                    "status": OAUTH_STATUS_PENDING,
                    "return_to": return_to,
                    "expires_at": expires_at,
                    "error_detail": None,
                    "completed_at": None,
                }
            )
            .execute()
        )
        row = _extract_single_row(response)
        if not row:
            raise RuntimeError("Failed to create oauth transaction")
        return row
    finally:
        await client.postgrest.aclose()


async def get_oauth_transaction(*, transaction_id: str) -> dict[str, Any] | None:
    client = await create_supabase_service_client()
    try:
        response = await (
            client.table("oauth_transactions")
            .select("*")
            .eq("id", transaction_id)
            .maybe_single()
            .execute()
        )
        return _extract_single_row(response)
    finally:
        await client.postgrest.aclose()


async def get_oauth_transaction_for_user(
    *,
    user_id: str,
    provider: str,
    transaction_id: str,
) -> dict[str, Any] | None:
    client = await create_supabase_service_client()
    try:
        response = await (
            client.table("oauth_transactions")
            .select("*")
            .eq("id", transaction_id)
            .eq("provider", provider)
            .eq("user_id", user_id)
            .maybe_single()
            .execute()
        )
        return _extract_single_row(response)
    finally:
        await client.postgrest.aclose()


async def consume_pending_transaction(
    *,
    transaction_id: str,
    provider: str,
    consumed_at: str | None = None,
) -> dict[str, Any] | None:
    lock_time = consumed_at or _utc_now_iso()

    client = await create_supabase_service_client()
    try:
        response = await (
            client.table("oauth_transactions")
            .update({"completed_at": lock_time})
            .eq("id", transaction_id)
            .eq("provider", provider)
            .eq("status", OAUTH_STATUS_PENDING)
            .is_("completed_at", "null")
            .gt("expires_at", lock_time)
            .execute()
        )
        return _extract_single_row(response)
    finally:
        await client.postgrest.aclose()


async def mark_transaction_connected(
    *,
    transaction_id: str,
    provider: str,
    completed_at_lock: str,
) -> dict[str, Any] | None:
    client = await create_supabase_service_client()
    try:
        response = await (
            client.table("oauth_transactions")
            .update(
                {
                    "status": OAUTH_STATUS_CONNECTED,
                    "error_detail": None,
                }
            )
            .eq("id", transaction_id)
            .eq("provider", provider)
            .eq("status", OAUTH_STATUS_PENDING)
            .eq("completed_at", completed_at_lock)
            .execute()
        )
        return _extract_single_row(response)
    finally:
        await client.postgrest.aclose()


async def mark_transaction_error(
    *,
    transaction_id: str,
    provider: str,
    detail: str,
    status: str = OAUTH_STATUS_ERROR,
    completed_at_lock: str | None = None,
) -> dict[str, Any] | None:
    completed_at = _utc_now_iso()
    client = await create_supabase_service_client()
    try:
        query = (
            client.table("oauth_transactions")
            .update(
                {
                    "status": status,
                    "error_detail": detail,
                    "completed_at": completed_at,
                }
            )
            .eq("id", transaction_id)
            .eq("provider", provider)
            .eq("status", OAUTH_STATUS_PENDING)
        )

        if completed_at_lock is not None:
            query = query.eq("completed_at", completed_at_lock)

        response = await query.execute()
        row = _extract_single_row(response)
        if row:
            return row
    finally:
        await client.postgrest.aclose()

    return await get_oauth_transaction(transaction_id=transaction_id)


async def mark_transaction_expired_if_needed(
    *,
    transaction: dict[str, Any],
    detail: str = "OAuth transaction expired.",
) -> dict[str, Any]:
    if transaction.get("status") != OAUTH_STATUS_PENDING:
        return transaction

    expires_at = _parse_iso_datetime(transaction.get("expires_at"))
    now = datetime.now(timezone.utc)

    if not expires_at or expires_at > now:
        return transaction

    updated = await mark_transaction_error(
        transaction_id=str(transaction.get("id")),
        provider=str(transaction.get("provider")),
        detail=detail,
        status=OAUTH_STATUS_EXPIRED,
        completed_at_lock=(
            str(transaction.get("completed_at"))
            if isinstance(transaction.get("completed_at"), str)
            else None
        ),
    )
    return updated if updated else transaction
