from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query

from whatsapp_session_controller.api.schemas.runtimes import (
    DisconnectRuntimeRequest,
    DisconnectRuntimeResponse,
    LeaseRuntimeRequest,
    LeaseRuntimeResponse,
    RuntimeStatusResponse,
    TouchRuntimeRequest,
    TouchRuntimeResponse,
)
from whatsapp_session_controller.auth import ControllerAuthContext, require_scope
from whatsapp_session_controller.services.runtime_manager import (
    RuntimeManager,
    RuntimeRecord,
    get_runtime_manager,
)


router = APIRouter(prefix="/whatsapp/runtimes")
logger = logging.getLogger(__name__)


def _normalize_identifier(*, value: str, field_name: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise HTTPException(status_code=422, detail=f"{field_name} must be non-empty")
    return normalized


def _safe_user_label(user_id: str) -> str:
    normalized = user_id.strip()
    if not normalized:
        return "unknown"
    if len(normalized) <= 6:
        return normalized
    return f"{normalized[:3]}...{normalized[-2:]}"


def _enforce_user_ownership(*, auth_ctx: ControllerAuthContext, user_id: str) -> None:
    if auth_ctx.user_id != user_id:
        raise HTTPException(status_code=403, detail="Token user_id does not match request user_id")


def _enforce_runtime_binding(*, auth_ctx: ControllerAuthContext, runtime_id: str) -> None:
    # Runtime-specific tokens are optional for lease and may be omitted by callers.
    if auth_ctx.runtime_id and auth_ctx.runtime_id != runtime_id:
        raise HTTPException(
            status_code=403,
            detail="Token runtime_id does not match requested runtime_id",
        )


def _to_lease_response(
    *,
    record: RuntimeRecord,
    action: str,
) -> LeaseRuntimeResponse:
    return LeaseRuntimeResponse(
        runtime_id=record.runtime_id,
        generation=record.generation,
        state=record.state,
        bridge_base_url=record.bridge_base_url,
        mcp_url=record.mcp_url,
        runtime_started_at=record.runtime_started_at.isoformat(),
        hard_expires_at=record.hard_expires_at.isoformat(),
        lease_expires_at=record.lease_expires_at.isoformat(),
        poll_after_seconds=2,
        action=action,
    )


def _to_status_response(record: RuntimeRecord) -> RuntimeStatusResponse:
    return RuntimeStatusResponse(
        runtime_id=record.runtime_id,
        generation=record.generation,
        state=record.state,
        bridge_base_url=record.bridge_base_url,
        mcp_url=record.mcp_url,
        runtime_started_at=record.runtime_started_at.isoformat(),
        hard_expires_at=record.hard_expires_at.isoformat(),
        lease_expires_at=record.lease_expires_at.isoformat(),
        last_error=record.last_error,
    )


@router.post("/lease", response_model=LeaseRuntimeResponse)
async def lease_runtime(
    payload: LeaseRuntimeRequest,
    auth_ctx: ControllerAuthContext = Depends(require_scope("whatsapp:runtime:lease")),
    runtime_manager: RuntimeManager = Depends(get_runtime_manager),
) -> LeaseRuntimeResponse:
    user_id = _normalize_identifier(value=payload.user_id, field_name="user_id")
    _enforce_user_ownership(auth_ctx=auth_ctx, user_id=user_id)
    logger.info(
        "whatsapp.controller.api.lease.begin user=%s force_new=%s ttl_seconds=%s wait_for_ready_seconds=%s",
        _safe_user_label(user_id),
        payload.force_new,
        payload.ttl_seconds,
        payload.wait_for_ready_seconds,
    )
    record, action = await runtime_manager.lease(
        user_id=user_id,
        ttl_seconds=payload.ttl_seconds,
        force_new=payload.force_new,
        wait_for_ready_seconds=payload.wait_for_ready_seconds,
    )
    logger.info(
        "whatsapp.controller.api.lease.complete user=%s runtime_id=%s generation=%s state=%s action=%s bridge_base_url=%s mcp_url=%s",
        _safe_user_label(user_id),
        record.runtime_id,
        record.generation,
        record.state,
        action,
        record.bridge_base_url,
        record.mcp_url,
    )
    return _to_lease_response(record=record, action=action)


@router.get("/current", response_model=RuntimeStatusResponse)
async def get_current_runtime(
    user_id: str = Query(..., min_length=1),
    auth_ctx: ControllerAuthContext = Depends(require_scope("whatsapp:runtime:read")),
    runtime_manager: RuntimeManager = Depends(get_runtime_manager),
) -> RuntimeStatusResponse:
    resolved_user_id = _normalize_identifier(value=user_id, field_name="user_id")
    _enforce_user_ownership(auth_ctx=auth_ctx, user_id=resolved_user_id)
    logger.info(
        "whatsapp.controller.api.current.begin user=%s",
        _safe_user_label(resolved_user_id),
    )

    record = await runtime_manager.get_current(user_id=resolved_user_id)
    if record is None:
        logger.info(
            "whatsapp.controller.api.current.not_found user=%s",
            _safe_user_label(resolved_user_id),
        )
        raise HTTPException(status_code=404, detail="Runtime not found")
    logger.info(
        "whatsapp.controller.api.current.complete user=%s runtime_id=%s generation=%s state=%s bridge_base_url=%s mcp_url=%s",
        _safe_user_label(resolved_user_id),
        record.runtime_id,
        record.generation,
        record.state,
        record.bridge_base_url,
        record.mcp_url,
    )
    return _to_status_response(record)


@router.get("/{runtime_id}", response_model=RuntimeStatusResponse)
async def get_runtime(
    runtime_id: str,
    user_id: str = Query(..., min_length=1),
    auth_ctx: ControllerAuthContext = Depends(require_scope("whatsapp:runtime:read")),
    runtime_manager: RuntimeManager = Depends(get_runtime_manager),
) -> RuntimeStatusResponse:
    resolved_user_id = _normalize_identifier(value=user_id, field_name="user_id")
    resolved_runtime_id = _normalize_identifier(value=runtime_id, field_name="runtime_id")
    _enforce_user_ownership(auth_ctx=auth_ctx, user_id=resolved_user_id)
    _enforce_runtime_binding(auth_ctx=auth_ctx, runtime_id=resolved_runtime_id)
    logger.info(
        "whatsapp.controller.api.get.begin user=%s runtime_id=%s",
        _safe_user_label(resolved_user_id),
        resolved_runtime_id,
    )

    record = await runtime_manager.get(user_id=resolved_user_id, runtime_id=resolved_runtime_id)
    if record is None:
        logger.info(
            "whatsapp.controller.api.get.not_found user=%s runtime_id=%s",
            _safe_user_label(resolved_user_id),
            resolved_runtime_id,
        )
        raise HTTPException(status_code=404, detail="Runtime not found")
    logger.info(
        "whatsapp.controller.api.get.complete user=%s runtime_id=%s generation=%s state=%s",
        _safe_user_label(resolved_user_id),
        record.runtime_id,
        record.generation,
        record.state,
    )
    return _to_status_response(record)


@router.post("/{runtime_id}/touch", response_model=TouchRuntimeResponse)
async def touch_runtime(
    runtime_id: str,
    payload: TouchRuntimeRequest,
    auth_ctx: ControllerAuthContext = Depends(require_scope("whatsapp:runtime:touch")),
    runtime_manager: RuntimeManager = Depends(get_runtime_manager),
) -> TouchRuntimeResponse:
    user_id = _normalize_identifier(value=payload.user_id, field_name="user_id")
    resolved_runtime_id = _normalize_identifier(value=runtime_id, field_name="runtime_id")
    _enforce_user_ownership(auth_ctx=auth_ctx, user_id=user_id)
    _enforce_runtime_binding(auth_ctx=auth_ctx, runtime_id=resolved_runtime_id)
    logger.info(
        "whatsapp.controller.api.touch.begin user=%s runtime_id=%s ttl_seconds=%s",
        _safe_user_label(user_id),
        resolved_runtime_id,
        payload.ttl_seconds,
    )

    record = await runtime_manager.touch(
        user_id=user_id,
        runtime_id=resolved_runtime_id,
        ttl_seconds=payload.ttl_seconds,
    )
    if record is None:
        logger.info(
            "whatsapp.controller.api.touch.not_found user=%s runtime_id=%s",
            _safe_user_label(user_id),
            resolved_runtime_id,
        )
        raise HTTPException(status_code=404, detail="Runtime not found")
    logger.info(
        "whatsapp.controller.api.touch.complete user=%s runtime_id=%s lease_expires_at=%s",
        _safe_user_label(user_id),
        record.runtime_id,
        record.lease_expires_at.isoformat(),
    )

    return TouchRuntimeResponse(
        ok=True,
        runtime_id=record.runtime_id,
        hard_expires_at=record.hard_expires_at.isoformat(),
        lease_expires_at=record.lease_expires_at.isoformat(),
    )


@router.post("/{runtime_id}/disconnect", response_model=DisconnectRuntimeResponse)
async def disconnect_runtime(
    runtime_id: str,
    payload: DisconnectRuntimeRequest,
    auth_ctx: ControllerAuthContext = Depends(require_scope("whatsapp:runtime:disconnect")),
    runtime_manager: RuntimeManager = Depends(get_runtime_manager),
) -> DisconnectRuntimeResponse:
    user_id = _normalize_identifier(value=payload.user_id, field_name="user_id")
    resolved_runtime_id = _normalize_identifier(value=runtime_id, field_name="runtime_id")
    _enforce_user_ownership(auth_ctx=auth_ctx, user_id=user_id)
    _enforce_runtime_binding(auth_ctx=auth_ctx, runtime_id=resolved_runtime_id)
    logger.info(
        "whatsapp.controller.api.disconnect.begin user=%s runtime_id=%s stop_reason=%s",
        _safe_user_label(user_id),
        resolved_runtime_id,
        payload.stop_reason,
    )

    record = await runtime_manager.disconnect(user_id=user_id, runtime_id=resolved_runtime_id)
    if record is None:
        logger.info(
            "whatsapp.controller.api.disconnect.not_found user=%s runtime_id=%s",
            _safe_user_label(user_id),
            resolved_runtime_id,
        )
        raise HTTPException(status_code=404, detail="Runtime not found")
    logger.info(
        "whatsapp.controller.api.disconnect.complete user=%s runtime_id=%s state=%s",
        _safe_user_label(user_id),
        record.runtime_id,
        record.state,
    )
    return DisconnectRuntimeResponse(ok=True, runtime_id=record.runtime_id, state=record.state)
