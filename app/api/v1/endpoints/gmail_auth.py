import base64
import json
import os
import secrets
from typing import Optional
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.concurrency import run_in_threadpool

from google_auth_oauthlib.flow import Flow

from app.core.settings import get_gmail_auth_settings
from app.db.gmail_sql import disconnect_gmail_connection, upsert_gmail_connection
from app.auth import AuthContext, get_auth_context



os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")

settings = get_gmail_auth_settings()

router = APIRouter()

_DEFAULT_ALLOWED_RETURN_TO_ORIGINS = {
    "http://localhost:3000",
    "http://127.0.0.1:3000",
}
_STATE_PAYLOAD_VERSION = 1


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


def _allowed_return_to_origins() -> set[str]:
    parsed = urlparse(settings.post_connect_redirect)
    allowed = set(_DEFAULT_ALLOWED_RETURN_TO_ORIGINS)
    if parsed.scheme and parsed.netloc:
        allowed.add(f"{parsed.scheme}://{parsed.netloc}")
    return allowed


def _sanitize_return_to(
    candidate: str | None,
    *,
    additional_allowed_origins: set[str] | None = None,
) -> str | None:
    if not candidate:
        return None

    parsed = urlparse(candidate)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None

    origin = f"{parsed.scheme}://{parsed.netloc}"
    allowed_origins = _allowed_return_to_origins()
    if additional_allowed_origins:
        allowed_origins.update(additional_allowed_origins)

    if origin not in allowed_origins:
        return None

    return candidate


def _resolve_return_to(*, request: Request, return_to: str | None) -> str:
    request_origin = request.headers.get("origin")
    additional_allowed_origins = (
        {request_origin} if request_origin else None
    )
    return (
        _sanitize_return_to(
            return_to,
            additional_allowed_origins=additional_allowed_origins,
        )
        or _sanitize_return_to(
            request.headers.get("referer"),
            additional_allowed_origins=additional_allowed_origins,
        )
        or settings.post_connect_redirect
    )


def _encode_oauth_state(*, csrf_state: str, return_to: str) -> str:
    payload = {
        "v": _STATE_PAYLOAD_VERSION,
        "csrf": csrf_state,
        "return_to": return_to,
    }
    serialized = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(serialized).decode("ascii").rstrip("=")


def _decode_oauth_state(state: str | None) -> tuple[str, str | None] | None:
    if not state:
        return None

    try:
        padded_state = state + "=" * (-len(state) % 4)
        decoded = base64.urlsafe_b64decode(padded_state.encode("ascii"))
        payload = json.loads(decoded.decode("utf-8"))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
        return None

    if not isinstance(payload, dict) or payload.get("v") != _STATE_PAYLOAD_VERSION:
        return None

    csrf_state = payload.get("csrf")
    if not isinstance(csrf_state, str) or not csrf_state:
        return None

    return_to = payload.get("return_to")
    return csrf_state, return_to if isinstance(return_to, str) else None


def _build_post_connect_redirect(
    *,
    status: str,
    detail: str | None = None,
    base_redirect: str | None = None,
) -> str:
    parsed = urlparse(base_redirect or settings.post_connect_redirect)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        parsed = urlparse(settings.post_connect_redirect)

    query_params = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query_params["provider"] = "gmail"
    query_params["status"] = status
    if detail:
        query_params["detail"] = detail
    else:
        query_params.pop("detail", None)
    return urlunparse(parsed._replace(query=urlencode(query_params)))


@router.get("/oauth/gmail/start")
async def oauth_gmail_start(
    request: Request,
    force_consent: bool = False,
    return_to: str | None = None,
    auth_ctx: AuthContext = Depends(get_auth_context),
):
    """
    Redirects the user to Google's OAuth consent screen.

    force_consent=true is useful ONLY when you need to guarantee a refresh token
    (e.g., you lost it and must re-consent).
    """
    flow = await make_flow()
    resolved_return_to = _resolve_return_to(
        request=request,
        return_to=return_to,
    )
    csrf_state = secrets.token_urlsafe(32)
    oauth_state = _encode_oauth_state(
        csrf_state=csrf_state,
        return_to=resolved_return_to,
    )

    auth_kwargs = dict(
        access_type="offline",            # critical: enables refresh token
        include_granted_scopes="true",    # recommended for incremental auth
    )
    if force_consent:
        auth_kwargs["prompt"] = "consent"

    authorization_url, state = await run_in_threadpool(
        flow.authorization_url,
        state=oauth_state,
        **auth_kwargs,
    )

    # Save CSRF state + who is connecting (so callback can map it)
    user_id = auth_ctx.user_id
    request.session["google_oauth_state"] = state
    request.session["google_oauth_user_id"] = user_id
    request.session["google_oauth_user_jwt"] = auth_ctx.token
    request.session["google_oauth_return_to"] = resolved_return_to
    request.session["google_oauth_request_origin"] = request.headers.get("origin")
    return {"url": authorization_url}
    # return RedirectResponse(authorization_url)


@router.get("/oauth/gmail/callback")
async def oauth_gmail_callback(request: Request):
    session_state = request.session.pop("google_oauth_state", None)
    session_user_id = request.session.pop("google_oauth_user_id", None)
    session_user_jwt = request.session.pop("google_oauth_user_jwt", None)
    session_return_to = request.session.pop("google_oauth_return_to", None)
    session_request_origin = request.session.pop("google_oauth_request_origin", None)
    state = request.query_params.get("state")
    decoded_state = _decode_oauth_state(state)
    decoded_return_to = decoded_state[1] if decoded_state else None
    callback_allowed_origins = (
        {session_request_origin} if session_request_origin else None
    )
    callback_return_to = (
        _sanitize_return_to(
            session_return_to,
            additional_allowed_origins=callback_allowed_origins,
        )
        or _sanitize_return_to(
            decoded_return_to,
            additional_allowed_origins=callback_allowed_origins,
        )
        or settings.post_connect_redirect
    )

    oauth_error = request.query_params.get("error")
    if oauth_error:
        return RedirectResponse(
            _build_post_connect_redirect(
                status="error",
                detail=oauth_error,
                base_redirect=callback_return_to,
            )
        )

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
    await upsert_gmail_connection(
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
    return RedirectResponse(
        _build_post_connect_redirect(
            status="connected",
            base_redirect=callback_return_to,
        )
    )


@router.post("/oauth/gmail/disconnect")
async def oauth_gmail_disconnect(
    auth_ctx: AuthContext = Depends(get_auth_context),
):
    disconnected = await disconnect_gmail_connection(
        user_id=auth_ctx.user_id,
        user_jwt=auth_ctx.token,
    )
    return {"ok": True, "provider": "gmail", "disconnected": disconnected}
