from __future__ import annotations

from dataclasses import dataclass

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


def get_auth_context(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> AuthContext:
    if not credentials or credentials.scheme.lower() != "bearer" or not credentials.credentials:
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")

    token = credentials.credentials
    jwt_secret = get_settings().supabase_jwt_secret
    try:
        if jwt_secret:
            payload = jwt.decode(
                token,
                jwt_secret,
                algorithms=["HS256"],
                options={"verify_aud": False},
            )
        else:
            payload = jwt.decode(
                token,
                options={"verify_signature": False, "verify_aud": False},
            )
    except PyJWTError as exc:
        raise HTTPException(status_code=401, detail="Invalid token") from exc

    user_id = payload.get("sub") or payload.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Token missing user id")
    return AuthContext(user_id=user_id, token=token)
