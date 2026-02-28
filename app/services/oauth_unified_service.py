from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Sequence
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from fastapi import HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import RedirectResponse
from google_auth_oauthlib.flow import Flow
from starlette.requests import Request

from app.auth import AuthContext
from app.core.settings import get_oauth_state_settings
from app.db.oauth_transactions_sql import (
    OAUTH_STATUS_ERROR,
    OAUTH_STATUS_EXPIRED,
    OAUTH_STATUS_PENDING,
    consume_pending_transaction,
    create_oauth_transaction,
    get_oauth_transaction,
    get_oauth_transaction_for_user,
    mark_transaction_connected,
    mark_transaction_error,
    mark_transaction_expired_if_needed,
)
from app.schemas.endpoint_schemas.oauth import OAuthStartResponse, OAuthStatusResponse
from app.services.oauth_state import (
    decode_oauth_state,
    encode_oauth_state,
    summarize_state_error,
)


_DEFAULT_ALLOWED_RETURN_TO_ORIGINS = {
    "http://localhost:3000",
    "http://127.0.0.1:3000",
}


OAuthPersistConnection = Callable[[str, Any], Awaitable[None]]


@dataclass(frozen=True)
class OAuthProviderSpec:
    provider: str
    client_secrets_file: str
    scopes: Sequence[str]
    redirect_uri: str
    post_connect_redirect: str


def _build_flow(provider_spec: OAuthProviderSpec, state: str | None = None) -> Flow:
    flow = Flow.from_client_secrets_file(
        provider_spec.client_secrets_file,
        scopes=list(provider_spec.scopes),
        state=state,
    )
    flow.redirect_uri = provider_spec.redirect_uri
    return flow


async def make_flow(provider_spec: OAuthProviderSpec, state: str | None = None) -> Flow:
    return await run_in_threadpool(_build_flow, provider_spec, state)


def _allowed_return_to_origins(provider_spec: OAuthProviderSpec) -> set[str]:
    parsed = urlparse(provider_spec.post_connect_redirect)
    allowed = set(_DEFAULT_ALLOWED_RETURN_TO_ORIGINS)
    if parsed.scheme and parsed.netloc:
        allowed.add(f"{parsed.scheme}://{parsed.netloc}")
    return allowed


def _sanitize_return_to(
    candidate: str | None,
    *,
    provider_spec: OAuthProviderSpec,
    additional_allowed_origins: set[str] | None = None,
) -> str | None:
    if not candidate:
        return None

    parsed = urlparse(candidate)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None

    origin = f"{parsed.scheme}://{parsed.netloc}"
    allowed_origins = _allowed_return_to_origins(provider_spec)
    if additional_allowed_origins:
        allowed_origins.update(additional_allowed_origins)

    if origin not in allowed_origins:
        return None

    return candidate


def _resolve_return_to(
    *,
    request: Request,
    return_to: str | None,
    provider_spec: OAuthProviderSpec,
) -> str:
    request_origin = request.headers.get("origin")
    additional_allowed_origins = {request_origin} if request_origin else None
    return (
        _sanitize_return_to(
            return_to,
            provider_spec=provider_spec,
            additional_allowed_origins=additional_allowed_origins,
        )
        or _sanitize_return_to(
            request.headers.get("referer"),
            provider_spec=provider_spec,
            additional_allowed_origins=additional_allowed_origins,
        )
        or provider_spec.post_connect_redirect
    )


def _build_post_connect_redirect(
    *,
    provider_spec: OAuthProviderSpec,
    status: str,
    detail: str | None = None,
    base_redirect: str | None = None,
) -> str:
    parsed = urlparse(base_redirect or provider_spec.post_connect_redirect)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        parsed = urlparse(provider_spec.post_connect_redirect)

    query_params = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query_params["provider"] = provider_spec.provider
    query_params["status"] = status
    if detail:
        query_params["detail"] = detail
    else:
        query_params.pop("detail", None)
    return urlunparse(parsed._replace(query=urlencode(query_params)))


def _safe_detail(detail: Any, default: str) -> str:
    if detail is None:
        return default
    text = str(detail).strip()
    if not text:
        return default
    normalized = " ".join(text.split())
    return normalized[:180]


def _expires_at_iso() -> str:
    settings = get_oauth_state_settings()
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=settings.ttl_seconds)
    return expires_at.isoformat()


async def start_oauth_flow(
    *,
    request: Request,
    auth_ctx: AuthContext,
    provider_spec: OAuthProviderSpec,
    force_consent: bool,
    return_to: str | None,
) -> OAuthStartResponse:
    resolved_return_to = _resolve_return_to(
        request=request,
        return_to=return_to,
        provider_spec=provider_spec,
    )

    transaction = await create_oauth_transaction(
        provider=provider_spec.provider,
        user_id=auth_ctx.user_id,
        return_to=resolved_return_to,
        expires_at=_expires_at_iso(),
    )
    transaction_id = str(transaction.get("id"))

    oauth_state = encode_oauth_state(
        transaction_id=transaction_id,
        provider=provider_spec.provider,
    )

    flow = await make_flow(provider_spec)

    auth_kwargs: dict[str, Any] = {
        "access_type": "offline",
        "include_granted_scopes": "true",
    }
    if force_consent:
        auth_kwargs["prompt"] = "consent"

    authorization_url, _ = await run_in_threadpool(
        flow.authorization_url,
        state=oauth_state,
        **auth_kwargs,
    )

    return OAuthStartResponse(
        provider=provider_spec.provider,
        url=authorization_url,
        transaction_id=transaction_id,
        status=OAUTH_STATUS_PENDING,
        expires_at=str(transaction.get("expires_at") or _expires_at_iso()),
    )


async def get_oauth_status(
    *,
    transaction_id: str,
    auth_ctx: AuthContext,
    provider_spec: OAuthProviderSpec,
) -> OAuthStatusResponse:
    transaction = await get_oauth_transaction_for_user(
        user_id=auth_ctx.user_id,
        provider=provider_spec.provider,
        transaction_id=transaction_id,
    )
    if not transaction:
        raise HTTPException(status_code=404, detail="OAuth transaction not found")

    transaction = await mark_transaction_expired_if_needed(transaction=transaction)

    status = str(transaction.get("status") or OAUTH_STATUS_EXPIRED)
    detail = (
        str(transaction.get("error_detail"))
        if status in {OAUTH_STATUS_ERROR, OAUTH_STATUS_EXPIRED}
        and isinstance(transaction.get("error_detail"), str)
        else None
    )
    updated_at = str(
        transaction.get("updated_at")
        or transaction.get("created_at")
        or datetime.now(timezone.utc).isoformat()
    )

    return OAuthStatusResponse(
        provider=provider_spec.provider,
        transaction_id=transaction_id,
        status=status,  # type: ignore[arg-type]
        connected=status == "connected",
        detail=detail,
        updated_at=updated_at,
    )


async def callback_oauth_flow(
    *,
    request: Request,
    provider_spec: OAuthProviderSpec,
    persist_connection: OAuthPersistConnection,
) -> RedirectResponse:
    state_token = request.query_params.get("state")
    callback_return_to = provider_spec.post_connect_redirect

    try:
        claims = decode_oauth_state(
            state_token,
            expected_provider=provider_spec.provider,
        )
    except Exception as exc:
        return RedirectResponse(
            _build_post_connect_redirect(
                provider_spec=provider_spec,
                status="error",
                detail=summarize_state_error(exc),
                base_redirect=callback_return_to,
            )
        )

    transaction = await get_oauth_transaction(transaction_id=claims.transaction_id)
    if not transaction or transaction.get("provider") != provider_spec.provider:
        return RedirectResponse(
            _build_post_connect_redirect(
                provider_spec=provider_spec,
                status="error",
                detail="oauth_transaction_not_found",
                base_redirect=callback_return_to,
            )
        )

    callback_return_to = (
        _sanitize_return_to(
            transaction.get("return_to") if isinstance(transaction.get("return_to"), str) else None,
            provider_spec=provider_spec,
        )
        or provider_spec.post_connect_redirect
    )

    transaction = await mark_transaction_expired_if_needed(transaction=transaction)
    if transaction.get("status") == OAUTH_STATUS_EXPIRED:
        return RedirectResponse(
            _build_post_connect_redirect(
                provider_spec=provider_spec,
                status="expired",
                detail=_safe_detail(transaction.get("error_detail"), "oauth_transaction_expired"),
                base_redirect=callback_return_to,
            )
        )

    locked = await consume_pending_transaction(
        transaction_id=str(transaction.get("id")),
        provider=provider_spec.provider,
    )
    if not locked:
        return RedirectResponse(
            _build_post_connect_redirect(
                provider_spec=provider_spec,
                status="expired",
                detail="oauth_transaction_consumed",
                base_redirect=callback_return_to,
            )
        )

    lock_time_raw = locked.get("completed_at")
    lock_time = lock_time_raw if isinstance(lock_time_raw, str) else None

    oauth_error = request.query_params.get("error")
    if oauth_error:
        await mark_transaction_error(
            transaction_id=str(locked.get("id")),
            provider=provider_spec.provider,
            detail=_safe_detail(oauth_error, "oauth_provider_error"),
            status=OAUTH_STATUS_ERROR,
            completed_at_lock=lock_time,
        )
        return RedirectResponse(
            _build_post_connect_redirect(
                provider_spec=provider_spec,
                status="error",
                detail=_safe_detail(oauth_error, "oauth_provider_error"),
                base_redirect=callback_return_to,
            )
        )

    try:
        flow = await make_flow(provider_spec, state=state_token)
        await run_in_threadpool(flow.fetch_token, authorization_response=str(request.url))
        creds = flow.credentials
        await persist_connection(str(locked.get("user_id")), creds)

        updated = await mark_transaction_connected(
            transaction_id=str(locked.get("id")),
            provider=provider_spec.provider,
            completed_at_lock=lock_time or "",
        )
        if not updated:
            return RedirectResponse(
                _build_post_connect_redirect(
                    provider_spec=provider_spec,
                    status="expired",
                    detail="oauth_transaction_consumed",
                    base_redirect=callback_return_to,
                )
            )
    except Exception as exc:
        detail = _safe_detail(exc, "oauth_callback_failed")
        await mark_transaction_error(
            transaction_id=str(locked.get("id")),
            provider=provider_spec.provider,
            detail=detail,
            status=OAUTH_STATUS_ERROR,
            completed_at_lock=lock_time,
        )
        return RedirectResponse(
            _build_post_connect_redirect(
                provider_spec=provider_spec,
                status="error",
                detail=detail,
                base_redirect=callback_return_to,
            )
        )

    return RedirectResponse(
        _build_post_connect_redirect(
            provider_spec=provider_spec,
            status="connected",
            base_redirect=callback_return_to,
        )
    )
