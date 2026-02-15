import os
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.concurrency import run_in_threadpool
from google_auth_oauthlib.flow import Flow

from app.auth import AuthContext, get_auth_context
from app.core.settings import get_google_drive_settings
from app.db.google_drive_sql import (
    list_google_drive_users,
    upsert_google_drive_connection,
)


os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")

settings = get_google_drive_settings()

router = APIRouter()


def _build_flow(state: Optional[str] = None) -> Flow:
    flow = Flow.from_client_secrets_file(
        settings.client_secrets_file,
        scopes=settings.scopes,
        state=state,
    )
    flow.redirect_uri = settings.redirect_uri
    return flow


async def make_flow(state: Optional[str] = None) -> Flow:
    return await run_in_threadpool(_build_flow, state)


@router.get("/oauth/google-drive/start")
async def oauth_google_drive_start(
    request: Request,
    force_consent: bool = False,
    auth_ctx: AuthContext = Depends(get_auth_context),
):
    """
    Redirects the user to Google's OAuth consent screen.

    force_consent=true is useful ONLY when you need to guarantee a refresh token
    (e.g., you lost it and must re-consent).
    """
    flow = await make_flow()

    auth_kwargs = dict(
        access_type="offline",            # critical: enables refresh token
        include_granted_scopes="true",    # recommended for incremental auth
    )
    if force_consent:
        auth_kwargs["prompt"] = "consent"

    authorization_url, state = await run_in_threadpool(flow.authorization_url, **auth_kwargs)

    # Save CSRF state + who is connecting (so callback can map it)
    user_id = auth_ctx.user_id
    request.session["google_drive_oauth_state"] = state
    request.session["google_drive_oauth_user_id"] = user_id
    request.session["google_drive_oauth_user_jwt"] = auth_ctx.token
    return {"url": authorization_url}
    # return RedirectResponse(authorization_url)


@router.get("/oauth/google-drive/callback")
async def oauth_google_drive_callback(request: Request):
    session_state = request.session.get("google_drive_oauth_state")
    session_user_id = request.session.get("google_drive_oauth_user_id")
    session_user_jwt = request.session.get("google_drive_oauth_user_jwt")

    state = request.query_params.get("state")
    if not state or not session_state or state != session_state:
        raise HTTPException(status_code=400, detail="Invalid OAuth State")

    if not session_user_id:
        raise HTTPException(status_code=400, detail="Missing User ID")
    if not session_user_jwt:
        raise HTTPException(status_code=400, detail="Missing User JWT")

    flow = await make_flow(state=state)
    await run_in_threadpool(flow.fetch_token, authorization_response=str(request.url))

    creds = flow.credentials
    expires_at = creds.expiry.isoformat() if creds.expiry else None
    scopes = list(creds.scopes) if creds.scopes else None
    await upsert_google_drive_connection(
        user_id=session_user_id,
        user_jwt=session_user_jwt,
        google_email=None,
        refresh_token_encrypted=creds.refresh_token,
        access_token=creds.token,
        access_token_expires_at=expires_at,
        scopes=scopes,
        status="active",
        revoked_at=None,
    )
    # return {"url": settings.post_connect_redirect}
    return RedirectResponse(settings.post_connect_redirect)
