from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
import jwt
from jwt import PyJWTError

from browser_session_controller.settings import get_settings

_bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class ApiAuthContext:
    sub: str


@dataclass(frozen=True)
class RunnerAuthContext:
    session_id: str
    user_id: str


def require_api_auth(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> ApiAuthContext:
    if not creds or creds.scheme.lower() != "bearer" or not creds.credentials:
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")

    settings = get_settings()
    try:
        payload = jwt.decode(
            creds.credentials,
            settings.api_jwt_secret,
            algorithms=["HS256"],
            audience=settings.api_jwt_audience,
            options={"require": ["exp", "iat", "sub", "aud"]},
        )
    except PyJWTError as exc:
        raise HTTPException(status_code=401, detail="Invalid token") from exc

    sub = payload.get("sub")
    if not sub:
        raise HTTPException(status_code=401, detail="Token missing sub")
    return ApiAuthContext(sub=sub)


def require_runner_auth(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> RunnerAuthContext:
    if not creds or creds.scheme.lower() != "bearer" or not creds.credentials:
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")

    settings = get_settings()
    try:
        payload = jwt.decode(
            creds.credentials,
            settings.runner_broker_jwt_secret,
            algorithms=["HS256"],
            audience=settings.runner_broker_jwt_audience,
            options={"require": ["exp", "iat", "aud"]},
        )
    except PyJWTError as exc:
        raise HTTPException(status_code=401, detail="Invalid token") from exc

    session_id = payload.get("session_id")
    user_id = payload.get("user_id")
    if not session_id or not user_id:
        raise HTTPException(status_code=401, detail="Runner token missing session_id/user_id")
    return RunnerAuthContext(session_id=str(session_id), user_id=str(user_id))

