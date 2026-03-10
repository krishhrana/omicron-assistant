from __future__ import annotations

from datetime import datetime, timezone
import logging
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException

from app.auth import AuthContext, get_auth_context
from app.core.settings import get_whatsapp_session_settings
from app.db.whatsapp_sql import get_whatsapp_connection, upsert_whatsapp_connection
from app.schemas.endpoint_schemas.whatsapp_connect import (
    WhatsAppConnectStatusResponse,
    WhatsAppDisconnectResponse,
    WhatsAppPrewarmResponse,
)
from app.whatsapp_sessions import WhatsAppRuntimeLease, get_whatsapp_session_provider
from app.whatsapp_sessions.bridge_auth import WhatsAppBridgeAuthError, mint_bridge_bearer_header


router = APIRouter()
logger = logging.getLogger(__name__)

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

_DISCONNECT_REASON_RUNTIME_EXPIRED = "runtime_expired"
_DISCONNECT_REASON_USER_DISCONNECTED = "user_disconnected"
_DISCONNECT_REASON_WHATSAPP_LOGGED_OUT = "whatsapp_logged_out"
_VALID_DISCONNECT_REASONS = {
    _DISCONNECT_REASON_RUNTIME_EXPIRED,
    _DISCONNECT_REASON_USER_DISCONNECTED,
    _DISCONNECT_REASON_WHATSAPP_LOGGED_OUT,
}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_user_label(user_id: str) -> str:
    normalized = user_id.strip()
    if not normalized:
        return "unknown"
    if len(normalized) <= 6:
        return normalized
    return f"{normalized[:3]}...{normalized[-2:]}"


def _coerce_disconnect_reason(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip().lower()
    if normalized in _VALID_DISCONNECT_REASONS:
        return normalized
    return None


def _disconnect_message(reason: str) -> str:
    if reason == _DISCONNECT_REASON_USER_DISCONNECTED:
        return "WhatsApp was disconnected by user action. Tap Connect to relink."
    if reason == _DISCONNECT_REASON_WHATSAPP_LOGGED_OUT:
        return "WhatsApp logged out. Reconnect is required."
    return "WhatsApp runtime expired. Tap Connect to resume."


def _disconnect_status(reason: str) -> str:
    if reason == _DISCONNECT_REASON_WHATSAPP_LOGGED_OUT:
        return "logged_out"
    return "disconnected"


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
    logger.info(
        "whatsapp.bridge.status.request runtime_id=%s url=%s timeout_seconds=%.2f",
        lease.runtime_id,
        url,
        float(settings.bridge_timeout_seconds),
    )
    try:
        async with httpx.AsyncClient(timeout=settings.bridge_timeout_seconds) as client:
            response = await client.get(url, headers=auth_headers)
    except httpx.RequestError as exc:
        logger.warning(
            "whatsapp.bridge.status.request_failed runtime_id=%s url=%s error=%s",
            lease.runtime_id,
            url,
            exc,
        )
        raise HTTPException(status_code=503, detail=f"WhatsApp bridge is unavailable: {exc}") from exc

    logger.info(
        "whatsapp.bridge.status.response runtime_id=%s status_code=%s",
        lease.runtime_id,
        response.status_code,
    )
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
    logger.info(
        "whatsapp.bridge.connect.request runtime_id=%s url=%s timeout_seconds=%.2f",
        lease.runtime_id,
        url,
        float(settings.bridge_timeout_seconds),
    )
    try:
        async with httpx.AsyncClient(timeout=settings.bridge_timeout_seconds) as client:
            response = await client.post(url, headers=auth_headers)
    except httpx.RequestError as exc:
        logger.warning(
            "whatsapp.bridge.connect.request_failed runtime_id=%s url=%s error=%s",
            lease.runtime_id,
            url,
            exc,
        )
        raise HTTPException(status_code=503, detail=f"WhatsApp bridge is unavailable: {exc}") from exc

    logger.info(
        "whatsapp.bridge.connect.response runtime_id=%s status_code=%s",
        lease.runtime_id,
        response.status_code,
    )
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
    logger.info(
        "whatsapp.bridge.revoke_disconnect.request runtime_id=%s url=%s timeout_seconds=%.2f",
        lease.runtime_id,
        url,
        float(settings.bridge_timeout_seconds),
    )
    try:
        async with httpx.AsyncClient(timeout=settings.bridge_timeout_seconds) as client:
            response = await client.post(url, headers=auth_headers)
    except httpx.RequestError as exc:
        logger.warning(
            "whatsapp.bridge.revoke_disconnect.request_failed runtime_id=%s url=%s error=%s",
            lease.runtime_id,
            url,
            exc,
        )
        raise HTTPException(status_code=503, detail=f"WhatsApp bridge is unavailable: {exc}") from exc

    logger.info(
        "whatsapp.bridge.revoke_disconnect.response runtime_id=%s status_code=%s",
        lease.runtime_id,
        response.status_code,
    )
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
    existing_disconnect_reason = (
        _coerce_disconnect_reason(previous.get("last_error_code"))
        if isinstance(previous, dict)
        else None
    )

    if connected:
        connected_at = connected_at or now_iso
        disconnected_at = None
    elif state in {"disconnected", "logged_out", "error"}:
        disconnected_at = now_iso

    disconnect_reason: str | None = None
    if state == "logged_out":
        disconnect_reason = _DISCONNECT_REASON_WHATSAPP_LOGGED_OUT
    elif state == "disconnected":
        disconnect_reason = existing_disconnect_reason

    last_error_code = None
    if disconnect_reason is not None:
        last_error_code = disconnect_reason
    elif state == "error":
        last_error_code = "error"
    logger.info(
        "whatsapp.connection.snapshot user=%s runtime_id=%s state=%s connected=%s reauth_required=%s disconnect_reason=%s",
        _safe_user_label(auth_ctx.user_id),
        lease.runtime_id,
        state,
        connected,
        reauth_required,
        disconnect_reason,
    )
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
        logger.exception(
            "whatsapp.connection.snapshot.persist_failed user=%s runtime_id=%s state=%s",
            _safe_user_label(auth_ctx.user_id),
            lease.runtime_id,
            state,
        )
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
        disconnect_reason=disconnect_reason,
        message=message,
        qr_code=qr_code,
        qr_image_data_url=qr_image_data_url,
        sync_progress=sync_progress,
        sync_current=sync_current,
        sync_total=sync_total,
        updated_at=updated_at,
        poll_after_seconds=_poll_interval_for_state(state),
    )


async def _runtime_disconnected_status(
    *,
    auth_ctx: AuthContext,
) -> WhatsAppConnectStatusResponse:
    previous = await get_whatsapp_connection(user_id=auth_ctx.user_id, user_jwt=auth_ctx.token)
    previous_status = (
        str(previous.get("status") or "").strip().lower()
        if isinstance(previous, dict)
        else ""
    )
    disconnect_reason = (
        _coerce_disconnect_reason(previous.get("last_error_code"))
        if isinstance(previous, dict)
        else None
    )
    if disconnect_reason is None:
        if previous_status == "logged_out":
            disconnect_reason = _DISCONNECT_REASON_WHATSAPP_LOGGED_OUT
        else:
            disconnect_reason = _DISCONNECT_REASON_RUNTIME_EXPIRED

    now_iso = _utc_now_iso()
    connected_at = (
        previous.get("connected_at")
        if isinstance(previous, dict) and isinstance(previous.get("connected_at"), str)
        else None
    )
    status = _disconnect_status(disconnect_reason)
    reauth_required = disconnect_reason in {
        _DISCONNECT_REASON_USER_DISCONNECTED,
        _DISCONNECT_REASON_WHATSAPP_LOGGED_OUT,
    }
    logger.info(
        "whatsapp.connection.runtime_disconnected user=%s inferred_status=%s disconnect_reason=%s",
        _safe_user_label(auth_ctx.user_id),
        status,
        disconnect_reason,
    )
    try:
        await upsert_whatsapp_connection(
            user_id=auth_ctx.user_id,
            user_jwt=auth_ctx.token,
            runtime_id=None,
            status=status,
            reauth_required=reauth_required,
            last_error_code=disconnect_reason,
            connected_at=connected_at,
            disconnected_at=now_iso,
            last_seen_at=now_iso,
        )
    except Exception as exc:
        logger.exception(
            "whatsapp.connection.runtime_disconnected.persist_failed user=%s status=%s",
            _safe_user_label(auth_ctx.user_id),
            status,
        )
        raise HTTPException(
            status_code=500,
            detail=(
                "Failed to persist WhatsApp connection state. "
                "Apply whatsapp_connections schema migration first."
            ),
        ) from exc

    return WhatsAppConnectStatusResponse(
        runtime_id=None,
        status=status,
        connected=False,
        reauth_required=reauth_required,
        disconnect_reason=disconnect_reason,
        message=_disconnect_message(disconnect_reason),
        updated_at=now_iso,
        poll_after_seconds=_poll_interval_for_state(status),
    )


async def _refresh_runtime_lease_best_effort(
    *,
    provider: Any,
    auth_ctx: AuthContext,
    lease: WhatsAppRuntimeLease,
) -> None:
    touch = getattr(provider, "touch", None)
    if touch is None:
        return
    try:
        await touch(
            user_id=auth_ctx.user_id,
            user_jwt=auth_ctx.token,
            runtime_id=lease.runtime_id,
        )
    except Exception:
        # Lease-refresh failures should not fail user-visible connect/status responses.
        logger.warning(
            "whatsapp.runtime.touch_failed_nonblocking user=%s runtime_id=%s",
            _safe_user_label(auth_ctx.user_id),
            lease.runtime_id,
        )
        return


@router.post("/whatsapp/connect/start", response_model=WhatsAppConnectStatusResponse)
async def whatsapp_connect_start(
    auth_ctx: AuthContext = Depends(get_auth_context),
) -> WhatsAppConnectStatusResponse:
    user_label = _safe_user_label(auth_ctx.user_id)
    logger.info("whatsapp.connect.start.begin user=%s", user_label)
    provider = get_whatsapp_session_provider()
    try:
        lease = await provider.get_or_create(user_id=auth_ctx.user_id, user_jwt=auth_ctx.token)
    except RuntimeError as exc:
        logger.warning(
            "whatsapp.connect.start.lease_failed user=%s error=%s",
            user_label,
            exc,
        )
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    logger.info(
        "whatsapp.connect.start.lease_ok user=%s runtime_id=%s bridge_base_url=%s mcp_url=%s",
        user_label,
        lease.runtime_id,
        lease.bridge_base_url,
        lease.mcp_url,
    )
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
        logger.error(
            "whatsapp.connect.start.jwt_mint_failed user=%s runtime_id=%s error=%s",
            user_label,
            lease.runtime_id,
            exc,
        )
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    await _request_bridge_connect(lease, auth_headers=connect_headers)
    bridge_payload = await _fetch_bridge_status(lease, auth_headers=status_headers)
    response = await _sync_connection_snapshot(auth_ctx=auth_ctx, lease=lease, bridge_payload=bridge_payload)
    await _refresh_runtime_lease_best_effort(provider=provider, auth_ctx=auth_ctx, lease=lease)
    logger.info(
        "whatsapp.connect.start.complete user=%s runtime_id=%s status=%s connected=%s",
        user_label,
        lease.runtime_id,
        response.status,
        response.connected,
    )
    return response


@router.get("/whatsapp/connect/status", response_model=WhatsAppConnectStatusResponse)
async def whatsapp_connect_status(
    auth_ctx: AuthContext = Depends(get_auth_context),
) -> WhatsAppConnectStatusResponse:
    user_label = _safe_user_label(auth_ctx.user_id)
    logger.info("whatsapp.connect.status.begin user=%s", user_label)
    provider = get_whatsapp_session_provider()
    try:
        lease = await provider.read_current(user_id=auth_ctx.user_id, user_jwt=auth_ctx.token)
    except RuntimeError as exc:
        logger.warning(
            "whatsapp.connect.status.read_current_failed user=%s error=%s",
            user_label,
            exc,
        )
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if lease is None:
        logger.info("whatsapp.connect.status.no_runtime user=%s", user_label)
        return await _runtime_disconnected_status(auth_ctx=auth_ctx)
    logger.info(
        "whatsapp.connect.status.runtime user=%s runtime_id=%s bridge_base_url=%s mcp_url=%s",
        user_label,
        lease.runtime_id,
        lease.bridge_base_url,
        lease.mcp_url,
    )
    try:
        status_headers = mint_bridge_bearer_header(
            user_id=auth_ctx.user_id,
            runtime_id=lease.runtime_id,
            scope="whatsapp:status",
        )
    except WhatsAppBridgeAuthError as exc:
        logger.error(
            "whatsapp.connect.status.jwt_mint_failed user=%s runtime_id=%s error=%s",
            user_label,
            lease.runtime_id,
            exc,
        )
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    bridge_payload = await _fetch_bridge_status(lease, auth_headers=status_headers)
    response = await _sync_connection_snapshot(auth_ctx=auth_ctx, lease=lease, bridge_payload=bridge_payload)
    await _refresh_runtime_lease_best_effort(provider=provider, auth_ctx=auth_ctx, lease=lease)
    logger.info(
        "whatsapp.connect.status.complete user=%s runtime_id=%s status=%s connected=%s",
        user_label,
        lease.runtime_id,
        response.status,
        response.connected,
    )
    return response


@router.post("/whatsapp/connect/disconnect", response_model=WhatsAppDisconnectResponse)
async def whatsapp_connect_disconnect(
    auth_ctx: AuthContext = Depends(get_auth_context),
) -> WhatsAppDisconnectResponse:
    user_label = _safe_user_label(auth_ctx.user_id)
    logger.info("whatsapp.connect.disconnect.begin user=%s", user_label)
    provider = get_whatsapp_session_provider()
    try:
        lease = await provider.get_or_create(user_id=auth_ctx.user_id, user_jwt=auth_ctx.token)
    except RuntimeError as exc:
        logger.warning(
            "whatsapp.connect.disconnect.lease_failed user=%s error=%s",
            user_label,
            exc,
        )
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    logger.info(
        "whatsapp.connect.disconnect.lease_ok user=%s runtime_id=%s bridge_base_url=%s",
        user_label,
        lease.runtime_id,
        lease.bridge_base_url,
    )

    try:
        disconnect_headers = mint_bridge_bearer_header(
            user_id=auth_ctx.user_id,
            runtime_id=lease.runtime_id,
            scope="whatsapp:disconnect",
        )
    except WhatsAppBridgeAuthError as exc:
        logger.error(
            "whatsapp.connect.disconnect.jwt_mint_failed user=%s runtime_id=%s error=%s",
            user_label,
            lease.runtime_id,
            exc,
        )
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    await _request_bridge_revoke_disconnect(lease, auth_headers=disconnect_headers)

    await provider.disconnect(
        user_id=auth_ctx.user_id,
        user_jwt=auth_ctx.token,
        runtime_id=lease.runtime_id,
    )

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
            status="disconnected",
            reauth_required=True,
            last_error_code=_DISCONNECT_REASON_USER_DISCONNECTED,
            connected_at=connected_at,
            disconnected_at=now_iso,
            last_seen_at=now_iso,
        )
    except Exception as exc:
        logger.exception(
            "whatsapp.connect.disconnect.persist_failed user=%s runtime_id=%s",
            user_label,
            lease.runtime_id,
        )
        raise HTTPException(
            status_code=500,
            detail=(
                "Failed to persist WhatsApp disconnect state. "
                "Apply whatsapp_connections schema migration first."
            ),
        ) from exc
    logger.info(
        "whatsapp.connect.disconnect.complete user=%s runtime_id=%s status=disconnected",
        user_label,
        lease.runtime_id,
    )
    return WhatsAppDisconnectResponse(ok=True, status="disconnected")


@router.post("/whatsapp/runtime/prewarm", response_model=WhatsAppPrewarmResponse)
async def whatsapp_runtime_prewarm(
    auth_ctx: AuthContext = Depends(get_auth_context),
) -> WhatsAppPrewarmResponse:
    user_label = _safe_user_label(auth_ctx.user_id)
    existing = await get_whatsapp_connection(user_id=auth_ctx.user_id, user_jwt=auth_ctx.token)
    connection_status = (
        str(existing.get("status") or "").strip().lower()
        if isinstance(existing, dict)
        else ""
    )
    if connection_status != "connected":
        logger.info(
            "whatsapp.runtime.prewarm.skipped user=%s reason=not_connected connection_status=%s",
            user_label,
            connection_status,
        )
        return WhatsAppPrewarmResponse(
            ok=True,
            prewarmed=False,
            reason="not_connected",
        )

    provider = get_whatsapp_session_provider()
    try:
        lease = await provider.get_or_create(user_id=auth_ctx.user_id, user_jwt=auth_ctx.token)
    except RuntimeError as exc:
        logger.warning(
            "whatsapp.runtime.prewarm.lease_failed user=%s error=%s",
            user_label,
            exc,
        )
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    await _refresh_runtime_lease_best_effort(provider=provider, auth_ctx=auth_ctx, lease=lease)
    logger.info(
        "whatsapp.runtime.prewarm.complete user=%s runtime_id=%s bridge_base_url=%s",
        user_label,
        lease.runtime_id,
        lease.bridge_base_url,
    )
    return WhatsAppPrewarmResponse(
        ok=True,
        prewarmed=True,
        reason="connected_user",
        runtime_id=lease.runtime_id,
    )
