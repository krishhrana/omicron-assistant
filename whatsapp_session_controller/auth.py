from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
import jwt
from jwt import PyJWTError

from whatsapp_session_controller.core.settings import get_controller_settings


_bearer_scheme = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class ControllerAuthContext:
    subject: str
    user_id: str
    token: str
    scopes: tuple[str, ...]
    runtime_id: str | None = None


def _parse_scope_claims(raw_scope: Any, raw_scopes: Any) -> tuple[str, ...]:
    values: list[str] = []
    for candidate in (raw_scope, raw_scopes):
        if isinstance(candidate, str):
            values.extend(part.strip() for part in candidate.replace(",", " ").split() if part.strip())
        elif isinstance(candidate, list):
            values.extend(str(part).strip() for part in candidate if str(part).strip())
    deduped = tuple(dict.fromkeys(values))
    return deduped


def _extract_non_empty_str(claims: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = claims.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _decode_controller_token(token: str) -> ControllerAuthContext:
    settings = get_controller_settings()
    secret = (settings.jwt_secret or "").strip()
    if not secret:
        raise HTTPException(
            status_code=503,
            detail="Controller auth is unavailable: WHATSAPP_SESSION_CONTROLLER_JWT_SECRET is not configured.",
        )

    try:
        claims = jwt.decode(
            token,
            secret,
            algorithms=[settings.jwt_algorithm],
            audience=settings.jwt_audience,
            issuer=settings.jwt_issuer,
            options={"require": ["sub", "iat", "exp", "user_id"]},
        )
    except PyJWTError as exc:
        raise HTTPException(status_code=401, detail="Invalid token") from exc

    subject = _extract_non_empty_str(claims, "sub")
    user_id = _extract_non_empty_str(claims, "user_id")
    runtime_id = _extract_non_empty_str(claims, "runtime_id")
    scopes = _parse_scope_claims(claims.get("scope"), claims.get("scopes"))

    if subject is None or user_id is None:
        raise HTTPException(status_code=401, detail="Invalid token claims")
    if not scopes:
        raise HTTPException(status_code=403, detail="Missing token scopes")

    return ControllerAuthContext(
        subject=subject,
        user_id=user_id,
        token=token,
        scopes=scopes,
        runtime_id=runtime_id,
    )


async def get_auth_context(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> ControllerAuthContext:
    if not credentials or credentials.scheme.lower() != "bearer" or not credentials.credentials:
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")
    token = credentials.credentials.strip()
    if not token:
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")
    return _decode_controller_token(token)


def require_scope(required_scope: str) -> Callable[..., ControllerAuthContext]:
    async def _dependency(
        auth_ctx: ControllerAuthContext = Depends(get_auth_context),
    ) -> ControllerAuthContext:
        if required_scope not in auth_ctx.scopes:
            raise HTTPException(status_code=403, detail=f"Missing required scope: {required_scope}")
        return auth_ctx

    return _dependency

