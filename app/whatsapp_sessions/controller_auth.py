from __future__ import annotations

import time
from collections.abc import Iterable

import jwt

from app.core.settings import get_whatsapp_session_settings


class WhatsAppControllerAuthError(RuntimeError):
    """Raised when WhatsApp session controller JWT auth configuration is invalid."""


def _required_controller_jwt_secret() -> str:
    settings = get_whatsapp_session_settings()
    secret = (settings.controller_jwt_secret or "").strip()
    if not secret:
        raise WhatsAppControllerAuthError(
            "WHATSAPP_SESSION_CONTROLLER_JWT_SECRET is not configured. "
            "Controller JWT auth is required."
        )
    return secret


def _split_claim_values(raw: str) -> list[str]:
    return [part.strip() for part in raw.replace(",", " ").split() if part.strip()]


def _normalize_claim_values(values: str | Iterable[str], *, claim_name: str) -> list[str]:
    if isinstance(values, str):
        normalized = _split_claim_values(values)
    else:
        normalized = []
        for value in values:
            if not isinstance(value, str):
                continue
            normalized.extend(_split_claim_values(value))

    deduped = list(dict.fromkeys(normalized))
    if not deduped:
        raise WhatsAppControllerAuthError(f"{claim_name} must include at least one value.")
    return deduped


def mint_whatsapp_controller_token(
    *,
    subject: str,
    user_id: str,
    scopes: str | Iterable[str],
    runtime_id: str | None = None,
    audiences: str | Iterable[str] | None = None,
    ttl_seconds: int | None = None,
) -> str:
    settings = get_whatsapp_session_settings()

    audience_values = _normalize_claim_values(
        audiences if audiences is not None else settings.controller_jwt_audience,
        claim_name="audiences",
    )
    scope_values = _normalize_claim_values(scopes, claim_name="scopes")

    effective_ttl = int(settings.controller_jwt_ttl_seconds if ttl_seconds is None else ttl_seconds)
    if effective_ttl <= 0:
        raise WhatsAppControllerAuthError(
            "WHATSAPP_SESSION_CONTROLLER_JWT_TTL_SECONDS must be greater than 0."
        )

    normalized_subject = subject.strip()
    if not normalized_subject:
        raise WhatsAppControllerAuthError("JWT subject must be non-empty.")

    normalized_user_id = user_id.strip()
    if not normalized_user_id:
        raise WhatsAppControllerAuthError("user_id must be non-empty.")

    normalized_runtime_id = runtime_id.strip() if isinstance(runtime_id, str) else None

    now = int(time.time())
    payload = {
        "sub": normalized_subject,
        "aud": audience_values if len(audience_values) > 1 else audience_values[0],
        "iss": settings.controller_jwt_issuer,
        "iat": now,
        "exp": now + effective_ttl,
        "user_id": normalized_user_id,
        "scope": " ".join(scope_values),
    }
    if normalized_runtime_id:
        payload["runtime_id"] = normalized_runtime_id

    return jwt.encode(payload, _required_controller_jwt_secret(), algorithm="HS256")


def mint_whatsapp_controller_bearer_header(
    *,
    subject: str,
    user_id: str,
    scopes: str | Iterable[str],
    runtime_id: str | None = None,
    audiences: str | Iterable[str] | None = None,
    ttl_seconds: int | None = None,
) -> dict[str, str]:
    token = mint_whatsapp_controller_token(
        subject=subject,
        user_id=user_id,
        scopes=scopes,
        runtime_id=runtime_id,
        audiences=audiences,
        ttl_seconds=ttl_seconds,
    )
    return {"Authorization": f"Bearer {token}"}


def mint_controller_lease_bearer_header(
    *,
    user_id: str,
    subject: str = "omicron-api",
) -> dict[str, str]:
    settings = get_whatsapp_session_settings()
    return mint_whatsapp_controller_bearer_header(
        subject=subject,
        user_id=user_id,
        scopes=["whatsapp:runtime:lease"],
        audiences=[settings.controller_jwt_audience],
    )


def mint_controller_read_bearer_header(
    *,
    user_id: str,
    runtime_id: str,
    subject: str = "omicron-api",
) -> dict[str, str]:
    settings = get_whatsapp_session_settings()
    return mint_whatsapp_controller_bearer_header(
        subject=subject,
        user_id=user_id,
        runtime_id=runtime_id,
        scopes=["whatsapp:runtime:read"],
        audiences=[settings.controller_jwt_audience],
    )


def mint_controller_touch_bearer_header(
    *,
    user_id: str,
    runtime_id: str,
    subject: str = "omicron-api",
) -> dict[str, str]:
    settings = get_whatsapp_session_settings()
    return mint_whatsapp_controller_bearer_header(
        subject=subject,
        user_id=user_id,
        runtime_id=runtime_id,
        scopes=["whatsapp:runtime:touch"],
        audiences=[settings.controller_jwt_audience],
    )


def mint_controller_disconnect_bearer_header(
    *,
    user_id: str,
    runtime_id: str,
    subject: str = "omicron-api",
) -> dict[str, str]:
    settings = get_whatsapp_session_settings()
    return mint_whatsapp_controller_bearer_header(
        subject=subject,
        user_id=user_id,
        runtime_id=runtime_id,
        scopes=["whatsapp:runtime:disconnect"],
        audiences=[settings.controller_jwt_audience],
    )
