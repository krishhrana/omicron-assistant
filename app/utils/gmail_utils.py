from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google.auth.exceptions import RefreshError

from googleapiclient.discovery import build

from app.db.gmail_sql import get_gmail_creds
from app.core.settings import get_gmail_auth_settings

from functools import wraps
import inspect

from fastapi import HTTPException
from fastapi.concurrency import run_in_threadpool


settings = get_gmail_auth_settings()

def gmail_api(fn=None):
    """
    Decorator for Gmail API tool functions.
    Supports usage as @gmail_api or @gmail_api().
    """
    def decorator(func):
        if inspect.iscoroutinefunction(func):
            @wraps(func)
            async def async_wrapper(*args, **kwargs):
                try:
                    return await func(*args, **kwargs)
                except RefreshError as exc:
                    raise HTTPException(status_code=401, detail="Gmail credentials expired") from exc
            return async_wrapper

        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            try:
                return await run_in_threadpool(func, *args, **kwargs)
            except RefreshError as exc:
                raise HTTPException(status_code=401, detail="Gmail credentials expired") from exc
        return async_wrapper

    if fn is None:
        return decorator
    return decorator(fn)


def get_gmail_client_for_user(user_id: str): 
    user_tokens = get_gmail_creds(user_id)
    creds = Credentials(
        token=user_tokens.access_token,
        refresh_token=user_tokens.refresh_token,
        token_uri=settings.auth_uri, 
        client_id=settings.client_id, 
        client_secret=settings.client_secret, 
        scopes = settings.scopes
    )
    # TODO add refresh token refresh logic
    if not creds.valid: 
        creds.refresh(Request())

    return build('gmail', 'v1', credentials=creds)
