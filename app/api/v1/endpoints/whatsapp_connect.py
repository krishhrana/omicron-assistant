from __future__ import annotations

from datetime import datetime, timezone
import traceback
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException

from app.auth import AuthContext, get_auth_context
from app.core.settings import get_whatsapp_session_settings
from app.db.whatsapp_sql import get_whatsapp_connection, upsert_whatsapp_connection
from app.schemas.endpoint_schemas.whatsapp_connect import (
    WhatsAppConnectStatusResponse,
    WhatsAppDisconnectResponse,
)
from app.whatsapp_sessions import WhatsAppRuntimeLease, get_whatsapp_session_provider
from app.whatsapp_sessions.bridge_auth import WhatsAppBridgeAuthError, mint_bridge_bearer_header


router = APIRouter()

_VALID_BRIDGE_STATES = {
    "disconnected",
    "connecting",
    "awaiting_qr",
    "logging_in",
    "syncing",
    "connected",
    "logged_out",
    "error",
}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _coerce_bridge_status(
    payload: dict[str, Any],
) -> tuple[str, bool, str | None, str | None, str | None, int | None, int | None, int | None, str | None]:
    state = str(payload.get("state") or "").strip().lower()
    if state not in _VALID_BRIDGE_STATES:
        state = "error"

    connected = bool(payload.get("connected"))
    if state == "connected":
        connected = True

    message = payload.get("message")
    qr_code = payload.get("qr_code")
    qr_image_data_url = payload.get("qr_image_data_url")
    sync_progress = payload.get("sync_progress")
    sync_current = payload.get("sync_current")
    sync_total = payload.get("sync_total")
    updated_at = payload.get("updated_at")
    return (
        state,
        connected,
        message if isinstance(message, str) else None,
        qr_code if isinstance(qr_code, str) else None,
        qr_image_data_url if isinstance(qr_image_data_url, str) else None,
        int(sync_progress) if isinstance(sync_progress, int) else None,
        int(sync_current) if isinstance(sync_current, int) else None,
        int(sync_total) if isinstance(sync_total, int) else None,
        updated_at if isinstance(updated_at, str) else None,
    )


def _poll_interval_for_state(state: str) -> int:
    if state in {"connecting", "awaiting_qr", "logging_in", "syncing"}:
        return 2
    if state == "connected":
        return 10
    return 5


async def _fetch_bridge_status(
    lease: WhatsAppRuntimeLease,
    *,
    auth_headers: dict[str, str],
) -> dict[str, Any]:
    settings = get_whatsapp_session_settings()
    url = f"{lease.bridge_base_url.rstrip('/')}/api/auth/status"
    try:
        async with httpx.AsyncClient(timeout=settings.bridge_timeout_seconds) as client:
            response = await client.get(url, headers=auth_headers)
    except httpx.RequestError as exc:
        raise HTTPException(status_code=503, detail=f"WhatsApp bridge is unavailable: {exc}") from exc

    if response.status_code != 200:
        raise HTTPException(
            status_code=502,
            detail=f"Failed to read WhatsApp bridge status (HTTP {response.status_code})",
        )

    payload = response.json()
    if not isinstance(payload, dict):
        raise HTTPException(status_code=502, detail="Invalid WhatsApp bridge status response")
    return payload


async def _request_bridge_connect(
    lease: WhatsAppRuntimeLease,
    *,
    auth_headers: dict[str, str],
) -> None:
    settings = get_whatsapp_session_settings()
    url = f"{lease.bridge_base_url.rstrip('/')}/api/connect"
    try:
        async with httpx.AsyncClient(timeout=settings.bridge_timeout_seconds) as client:
            response = await client.post(url, headers=auth_headers)
    except httpx.RequestError as exc:
        raise HTTPException(status_code=503, detail=f"WhatsApp bridge is unavailable: {exc}") from exc

    if response.status_code != 200:
        detail = f"Failed to start WhatsApp bridge connect flow (HTTP {response.status_code})"
        try:
            payload = response.json()
            if isinstance(payload, dict):
                message = payload.get("message")
                if isinstance(message, str) and message.strip():
                    detail = message.strip()
        except Exception:
            pass
        raise HTTPException(status_code=502, detail=detail)


async def _request_bridge_revoke_disconnect(
    lease: WhatsAppRuntimeLease,
    *,
    auth_headers: dict[str, str],
) -> None:
    settings = get_whatsapp_session_settings()
    url = f"{lease.bridge_base_url.rstrip('/')}/api/disconnect/revoke"
    try:
        async with httpx.AsyncClient(timeout=settings.bridge_timeout_seconds) as client:
            response = await client.post(url, headers=auth_headers)
    except httpx.RequestError as exc:
        raise HTTPException(status_code=503, detail=f"WhatsApp bridge is unavailable: {exc}") from exc

    if response.status_code != 200:
        detail = f"Failed to revoke WhatsApp device (HTTP {response.status_code})"
        try:
            payload = response.json()
            if isinstance(payload, dict):
                message = payload.get("message")
                if isinstance(message, str) and message.strip():
                    detail = message.strip()
        except Exception:
            pass
        raise HTTPException(status_code=502, detail=detail)


async def _sync_connection_snapshot(
    *,
    auth_ctx: AuthContext,
    lease: WhatsAppRuntimeLease,
    bridge_payload: dict[str, Any],
) -> WhatsAppConnectStatusResponse:
    (
        state,
        connected,
        message,
        qr_code,
        qr_image_data_url,
        sync_progress,
        sync_current,
        sync_total,
        updated_at,
    ) = _coerce_bridge_status(bridge_payload)
    reauth_required = state in {"awaiting_qr", "logged_out"}

    previous = await get_whatsapp_connection(user_id=auth_ctx.user_id, user_jwt=auth_ctx.token)
    now_iso = _utc_now_iso()

    connected_at = (
        previous.get("connected_at")
        if previous and isinstance(previous.get("connected_at"), str)
        else None
    )
    disconnected_at = (
        previous.get("disconnected_at")
        if previous and isinstance(previous.get("disconnected_at"), str)
        else None
    )

    if connected:
        connected_at = connected_at or now_iso
        disconnected_at = None
    elif state in {"disconnected", "logged_out", "error"}:
        disconnected_at = now_iso

    last_error_code = state if state == "error" else None
    try:
        await upsert_whatsapp_connection(
            user_id=auth_ctx.user_id,
            user_jwt=auth_ctx.token,
            runtime_id=lease.runtime_id,
            status=state,
            reauth_required=reauth_required,
            last_error_code=last_error_code,
            connected_at=connected_at,
            disconnected_at=disconnected_at,
            last_seen_at=now_iso,
        )
    except Exception as exc:
        print(traceback.format_exc())
        raise HTTPException(
            status_code=500,
            detail=(
                "Failed to persist WhatsApp connection state. "
                "Apply whatsapp_connections schema migration first."
            ),
        ) from exc

    return WhatsAppConnectStatusResponse(
        runtime_id=lease.runtime_id,
        status=state,
        connected=connected,
        reauth_required=reauth_required,
        message=message,
        qr_code=qr_code,
        qr_image_data_url=qr_image_data_url,
        sync_progress=sync_progress,
        sync_current=sync_current,
        sync_total=sync_total,
        updated_at=updated_at,
        poll_after_seconds=_poll_interval_for_state(state),
    )


@router.post("/whatsapp/connect/start", response_model=WhatsAppConnectStatusResponse)
async def whatsapp_connect_start(
    auth_ctx: AuthContext = Depends(get_auth_context),
) -> WhatsAppConnectStatusResponse:
    provider = get_whatsapp_session_provider()
    try:
        lease = await provider.get_or_create(user_id=auth_ctx.user_id, user_jwt=auth_ctx.token)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    try:
        connect_headers = mint_bridge_bearer_header(
            user_id=auth_ctx.user_id,
            runtime_id=lease.runtime_id,
            scope="whatsapp:connect",
        )
        status_headers = mint_bridge_bearer_header(
            user_id=auth_ctx.user_id,
            runtime_id=lease.runtime_id,
            scope="whatsapp:status",
        )
    except WhatsAppBridgeAuthError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    await _request_bridge_connect(lease, auth_headers=connect_headers)
    bridge_payload = await _fetch_bridge_status(lease, auth_headers=status_headers)
    return await _sync_connection_snapshot(auth_ctx=auth_ctx, lease=lease, bridge_payload=bridge_payload)


@router.get("/whatsapp/connect/status", response_model=WhatsAppConnectStatusResponse)
async def whatsapp_connect_status(
    auth_ctx: AuthContext = Depends(get_auth_context),
) -> WhatsAppConnectStatusResponse:
    provider = get_whatsapp_session_provider()
    try:
        lease = await provider.get_or_create(user_id=auth_ctx.user_id, user_jwt=auth_ctx.token)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    try:
        status_headers = mint_bridge_bearer_header(
            user_id=auth_ctx.user_id,
            runtime_id=lease.runtime_id,
            scope="whatsapp:status",
        )
    except WhatsAppBridgeAuthError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    bridge_payload = await _fetch_bridge_status(lease, auth_headers=status_headers)
    return await _sync_connection_snapshot(auth_ctx=auth_ctx, lease=lease, bridge_payload=bridge_payload)


@router.post("/whatsapp/connect/disconnect", response_model=WhatsAppDisconnectResponse)
async def whatsapp_connect_disconnect(
    auth_ctx: AuthContext = Depends(get_auth_context),
) -> WhatsAppDisconnectResponse:
    provider = get_whatsapp_session_provider()
    try:
        lease = await provider.get_or_create(user_id=auth_ctx.user_id, user_jwt=auth_ctx.token)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    try:
        disconnect_headers = mint_bridge_bearer_header(
            user_id=auth_ctx.user_id,
            runtime_id=lease.runtime_id,
            scope="whatsapp:disconnect",
        )
    except WhatsAppBridgeAuthError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    await _request_bridge_revoke_disconnect(lease, auth_headers=disconnect_headers)

    await provider.disconnect(user_id=auth_ctx.user_id, runtime_id=lease.runtime_id)

    previous = await get_whatsapp_connection(user_id=auth_ctx.user_id, user_jwt=auth_ctx.token)
    connected_at = (
        previous.get("connected_at")
        if previous and isinstance(previous.get("connected_at"), str)
        else None
    )
    now_iso = _utc_now_iso()
    try:
        await upsert_whatsapp_connection(
            user_id=auth_ctx.user_id,
            user_jwt=auth_ctx.token,
            runtime_id=lease.runtime_id,
            status="logged_out",
            reauth_required=True,
            last_error_code=None,
            connected_at=connected_at,
            disconnected_at=now_iso,
            last_seen_at=now_iso,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=(
                "Failed to persist WhatsApp disconnect state. "
                "Apply whatsapp_connections schema migration first."
            ),
        ) from exc
    return WhatsAppDisconnectResponse(ok=True, status="logged_out")
