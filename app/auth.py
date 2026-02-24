from __future__ import annotations

import contextlib
from dataclasses import dataclass
import inspect
from typing import Any, Callable

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
import jwt
from jwt import PyJWTError

from app.core.settings import get_settings

_bearer_scheme = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class AuthContext:
    user_id: str
    token: str


class _TokenInvalidError(RuntimeError):
    """Raised when a token is structurally invalid or rejected by the validator."""


class _TokenValidationUnavailableError(RuntimeError):
    """Raised when no trusted token validator is available at runtime."""


def _extract_user_id(payload: Any) -> str | None:
    if payload is None:
        return None

    if isinstance(payload, dict):
        raw_user_id = payload.get("id") or payload.get("sub") or payload.get("user_id")
        if isinstance(raw_user_id, str) and raw_user_id.strip():
            return raw_user_id.strip()

    for attr_name in ("user", "data", "payload", "session"):
        nested = getattr(payload, attr_name, None)
        nested_user_id = _extract_user_id(nested)
        if nested_user_id:
            return nested_user_id

    raw_user_id = getattr(payload, "id", None) or getattr(payload, "sub", None) or getattr(payload, "user_id", None)
    if isinstance(raw_user_id, str) and raw_user_id.strip():
        return raw_user_id.strip()

    return None


async def _call_supabase_get_user(get_user: Callable[..., Any], token: str) -> Any:
    call_signatures: tuple[tuple[tuple[Any, ...], dict[str, Any]], ...] = (
        ((token,), {}),
        ((), {"jwt": token}),
        ((), {}),
    )

    for args, kwargs in call_signatures:
        try:
            response = get_user(*args, **kwargs)
        except TypeError:
            continue
        if inspect.isawaitable(response):
            return await response
        return response

    raise _TokenValidationUnavailableError("Supabase auth.get_user signature is unsupported")


async def _validate_token_with_supabase_native(token: str) -> str:
    # Local import avoids eager coupling of app.auth to full dependency graph at module import time.
    from app.dependencies import create_supabase_user_client

    client = None
    try:
        client = await create_supabase_user_client(token)
        auth_client = getattr(client, "auth", None)
        get_user = getattr(auth_client, "get_user", None)
        if not callable(get_user):
            raise _TokenValidationUnavailableError("Supabase auth.get_user is unavailable")

        response = await _call_supabase_get_user(get_user, token)
        user_id = _extract_user_id(response)
        if not user_id:
            raise _TokenInvalidError("Supabase token validation did not return a user id")
        return user_id
    except (_TokenInvalidError, _TokenValidationUnavailableError):
        raise
    except Exception as exc:
        msg = str(exc).lower()
        invalid_markers = ("invalid", "jwt", "expired", "unauthorized", "forbidden", "401")
        if any(marker in msg for marker in invalid_markers):
            raise _TokenInvalidError("Supabase reported an invalid token") from exc
        raise _TokenValidationUnavailableError("Supabase token validation is unavailable") from exc
    finally:
        if client is not None:
            with contextlib.suppress(Exception):
                await client.postgrest.aclose()


def _validate_token_with_signed_jwt(token: str, jwt_secret: str) -> str:
    try:
        payload = jwt.decode(
            token,
            jwt_secret,
            algorithms=["HS256"],
            options={"verify_aud": False},
        )
    except PyJWTError as exc:
        raise _TokenInvalidError("Invalid token") from exc

    user_id = payload.get("sub") or payload.get("user_id")
    if not user_id:
        raise _TokenInvalidError("Token missing user id")
    return str(user_id)


async def get_auth_context(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> AuthContext:
    if not credentials or credentials.scheme.lower() != "bearer" or not credentials.credentials:
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")

    token = credentials.credentials.strip()
    if not token:
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")

    settings = get_settings()

    try:
        user_id = await _validate_token_with_supabase_native(token)
        return AuthContext(user_id=user_id, token=token)
    except _TokenInvalidError as exc:
        raise HTTPException(status_code=401, detail="Invalid token") from exc
    except _TokenValidationUnavailableError as native_exc:
        jwt_secret = settings.supabase_jwt_secret
        if jwt_secret and jwt_secret.strip():
            try:
                user_id = _validate_token_with_signed_jwt(token, jwt_secret.strip())
                return AuthContext(user_id=user_id, token=token)
            except _TokenInvalidError as jwt_exc:
                raise HTTPException(status_code=401, detail="Invalid token") from jwt_exc
        raise HTTPException(status_code=503, detail="Authentication validation unavailable") from native_exc
