from __future__ import annotations

import inspect
from functools import wraps
from typing import Callable, Protocol

from fastapi import HTTPException
from fastapi.concurrency import run_in_threadpool
from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from app.core.settings import GoogleAuthSettings


class GoogleCreds(Protocol):
    access_token: str | None
    refresh_token: str | None


def google_api(service_label: str):
    """
    Decorator for Google API tool functions.
    Supports usage as @google_api("Gmail") or google_api("Drive")(fn).
    """
    def decorator(func):
        if inspect.iscoroutinefunction(func):
            @wraps(func)
            async def async_wrapper(*args, **kwargs):
                try:
                    return await func(*args, **kwargs)
                except RefreshError as exc:
                    raise HTTPException(
                        status_code=401,
                        detail=f"{service_label} credentials expired",
                    ) from exc
            return async_wrapper

        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            try:
                return await run_in_threadpool(func, *args, **kwargs)
            except RefreshError as exc:
                raise HTTPException(
                    status_code=401,
                    detail=f"{service_label} credentials expired",
                ) from exc
        return async_wrapper

    return decorator


def get_google_client_for_user(
    *,
    user_id: str,
    user_jwt: str,
    token_loader: Callable[[str, str], GoogleCreds | None],
    settings: GoogleAuthSettings,
    api_service: str,
    api_version: str,
    service_label: str | None = None,
):
    user_tokens = token_loader(user_id, user_jwt)
    if not user_tokens:
        label = service_label or api_service
        raise HTTPException(status_code=401, detail=f"{label} credentials not found")
    creds = Credentials(
        token=user_tokens.access_token,
        refresh_token=user_tokens.refresh_token,
        token_uri=settings.token_uri,
        client_id=settings.client_id,
        client_secret=settings.client_secret,
        scopes=settings.scopes,
    )
    if not creds.valid:
        creds.refresh(Request())

    return build(api_service, api_version, credentials=creds)
