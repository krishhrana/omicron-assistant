from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import jwt
from jwt import PyJWTError

from app.core.settings import get_oauth_state_settings


_OAUTH_STATE_TYPE = "oauth_txn_v1"


class OAuthStateError(ValueError):
    """Raised when OAuth state token is invalid."""


@dataclass(frozen=True)
class OAuthStateClaims:
    transaction_id: str
    provider: str
    issued_at: int
    expires_at: int
    issuer: str


def encode_oauth_state(*, transaction_id: str, provider: str) -> str:
    settings = get_oauth_state_settings()
    now = int(time.time())
    exp = now + settings.ttl_seconds

    payload = {
        "typ": _OAUTH_STATE_TYPE,
        "tx": transaction_id,
        "prv": provider,
        "iat": now,
        "exp": exp,
        "iss": settings.issuer,
    }
    return jwt.encode(payload, settings.signing_secret, algorithm="HS256")


def decode_oauth_state(
    state_token: str | None,
    *,
    expected_provider: str | None = None,
) -> OAuthStateClaims:
    if not state_token:
        raise OAuthStateError("Missing OAuth state token.")

    settings = get_oauth_state_settings()
    try:
        payload = jwt.decode(
            state_token,
            settings.signing_secret,
            algorithms=["HS256"],
            issuer=settings.issuer,
        )
    except PyJWTError as exc:
        raise OAuthStateError("Invalid OAuth state token.") from exc

    if not isinstance(payload, dict):
        raise OAuthStateError("Invalid OAuth state payload.")

    token_type = payload.get("typ")
    if token_type != _OAUTH_STATE_TYPE:
        raise OAuthStateError("Unexpected OAuth state token type.")

    transaction_id = payload.get("tx")
    provider = payload.get("prv")
    issued_at = payload.get("iat")
    expires_at = payload.get("exp")
    issuer = payload.get("iss")

    if not isinstance(transaction_id, str) or not transaction_id.strip():
        raise OAuthStateError("OAuth state missing transaction id.")
    if not isinstance(provider, str) or not provider.strip():
        raise OAuthStateError("OAuth state missing provider.")

    if expected_provider and provider != expected_provider:
        raise OAuthStateError("OAuth state provider mismatch.")

    if not isinstance(issued_at, int) or not isinstance(expires_at, int):
        raise OAuthStateError("OAuth state timestamps are invalid.")
    if not isinstance(issuer, str) or not issuer.strip():
        raise OAuthStateError("OAuth state issuer is invalid.")

    return OAuthStateClaims(
        transaction_id=transaction_id,
        provider=provider,
        issued_at=issued_at,
        expires_at=expires_at,
        issuer=issuer,
    )


def summarize_state_error(err: Exception) -> str:
    message = str(err).strip()
    if not message:
        return "invalid_oauth_state"
    safe = " ".join(message.split())
    return safe[:120]
