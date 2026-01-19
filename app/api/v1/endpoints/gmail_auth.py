from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse

from google_auth_oauthlib.flow import Flow

from app.core.settings import get_gmail_auth_settings
from app.db.gmail_sql import upsert_gmail_connection, list_gmail_users


settings = get_gmail_auth_settings()

router = APIRouter()

# TODO Add logic to extract user from auth token
def get_current_user_id(request: Request) -> str:
    return "dummy_user_id"


def make_flow(state: Optional[str] = None) -> Flow:
    flow = Flow.from_client_secrets_file(
        settings.client_secrets_file,
        scopes=settings.scopes,
        state=state,
    )
    flow.redirect_uri = settings.redirect_uri
    return flow


@router.get("/oauth/gmail/start")
def oauth_gmail_start(request: Request, force_consent: bool = False):
    """
    Redirects the user to Google's OAuth consent screen.

    force_consent=true is useful ONLY when you need to guarantee a refresh token
    (e.g., you lost it and must re-consent).
    """
    user_id = get_current_user_id(request)

    flow = make_flow()

    auth_kwargs = dict(
        access_type="offline",            # critical: enables refresh token
        include_granted_scopes="true",    # recommended for incremental auth
    )
    if force_consent:
        auth_kwargs["prompt"] = "consent"

    authorization_url, state = flow.authorization_url(**auth_kwargs)

    # Save CSRF state + who is connecting (so callback can map it)
    request.session["google_oauth_state"] = state
    request.session["google_oauth_user_id"] = user_id

    return RedirectResponse(authorization_url)


@router.get("/oauth/gmail/callback")
def oauth_gmail_callback(request: Request):
    session_state = request.session.get("google_oauth_state")
    session_user_id = request.session.get("google_oauth_user_id")

    state = request.query_params.get("state")
    if not state or not session_state or state != session_state: 
        raise HTTPException(status_code=400, detail="Invalid OAuth State")
    
    if not session_user_id:
        raise HTTPException(status_code=400, detail="Missing User ID")
    
    flow = make_flow(state=state)
    flow.fetch_token(authorization_response=str(request.url))

    creds = flow.credentials
    expires_at = creds.expiry.isoformat() if creds.expiry else None
    scopes = list(creds.scopes) if creds.scopes else None
    upsert_gmail_connection(
        user_id=session_user_id,
        google_email=None,
        refresh_token_encrypted=creds.refresh_token,
        access_token=creds.token,
        access_token_expires_at=expires_at,
        scopes=scopes,
        status="active",
        revoked_at=None,
    )
    return RedirectResponse(settings.post_connect_redirect)
