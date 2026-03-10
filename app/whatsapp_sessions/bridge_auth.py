from __future__ import annotations

import time
from collections.abc import Iterable

import jwt

from app.core.settings import get_whatsapp_session_settings


class WhatsAppBridgeAuthError(RuntimeError):
    """Raised when WhatsApp bridge JWT auth configuration is invalid."""


def _required_bridge_jwt_secret() -> str:
    settings = get_whatsapp_session_settings()
    secret = (settings.bridge_jwt_secret or "").strip()
    if not secret:
        raise WhatsAppBridgeAuthError(
            "WHATSAPP_BRIDGE_JWT_SECRET is not configured. "
            "Bridge control-plane JWT auth is required."
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
        raise WhatsAppBridgeAuthError(f"{claim_name} must include at least one value.")
    return deduped


def mint_whatsapp_internal_token(
    *,
    subject: str,
    runtime_id: str,
    scopes: str | Iterable[str],
    audiences: str | Iterable[str] | None = None,
    ttl_seconds: int | None = None,
) -> str:
    """Mint a short-lived internal JWT for WhatsApp MCP and bridge control-plane calls."""
    settings = get_whatsapp_session_settings()
    audience_values = _normalize_claim_values(
        audiences if audiences is not None else settings.bridge_jwt_audience,
        claim_name="audiences",
    )
    scope_values = _normalize_claim_values(scopes, claim_name="scopes")
    effective_ttl = settings.bridge_jwt_ttl_seconds if ttl_seconds is None else ttl_seconds
    if effective_ttl <= 0:
        raise WhatsAppBridgeAuthError("WHATSAPP_BRIDGE_JWT_TTL_SECONDS must be greater than 0.")
    normalized_subject = subject.strip()
    if not normalized_subject:
        raise WhatsAppBridgeAuthError("JWT subject must be non-empty.")
    normalized_runtime_id = runtime_id.strip()
    if not normalized_runtime_id:
        raise WhatsAppBridgeAuthError("runtime_id must be non-empty.")

    now = int(time.time())
    payload = {
        "sub": normalized_subject,
        "aud": audience_values if len(audience_values) > 1 else audience_values[0],
        "iss": settings.bridge_jwt_issuer,
        "iat": now,
        "exp": now + effective_ttl,
        "runtime_id": normalized_runtime_id,
        "scope": " ".join(scope_values),
    }
    return jwt.encode(payload, _required_bridge_jwt_secret(), algorithm="HS256")


def mint_whatsapp_internal_bearer_header(
    *,
    subject: str,
    runtime_id: str,
    scopes: str | Iterable[str],
    audiences: str | Iterable[str] | None = None,
    ttl_seconds: int | None = None,
) -> dict[str, str]:
    """Mint Authorization header for internal WhatsApp service-to-service calls."""
    token = mint_whatsapp_internal_token(
        subject=subject,
        runtime_id=runtime_id,
        scopes=scopes,
        audiences=audiences,
        ttl_seconds=ttl_seconds,
    )
    return {"Authorization": f"Bearer {token}"}


def mint_bridge_bearer_header(
    *,
    user_id: str,
    runtime_id: str,
    scope: str,
) -> dict[str, str]:
    """Mint a short-lived JWT bearer header for WhatsApp bridge control-plane calls."""
    settings = get_whatsapp_session_settings()
    normalized_user_id = user_id.strip()
    if not normalized_user_id:
        raise WhatsAppBridgeAuthError("user_id must be non-empty.")
    service_subject = settings.bridge_jwt_issuer.strip() or "omicron-api"
    return mint_whatsapp_internal_bearer_header(
        subject=f"{service_subject}:{normalized_user_id}",
        runtime_id=runtime_id,
        scopes=[scope],
        audiences=[settings.bridge_jwt_audience],
    )
