import os

from fastapi import APIRouter, Depends, Request

from app.auth import AuthContext, get_auth_context
from app.core.settings import get_gmail_auth_settings
from app.db.gmail_sql import (
    disconnect_gmail_connection,
    upsert_gmail_connection_service,
)
from app.schemas.endpoint_schemas.oauth import OAuthStartResponse, OAuthStatusResponse
from app.services.oauth_unified_service import (
    OAuthProviderSpec,
    callback_oauth_flow,
    get_oauth_status,
    start_oauth_flow,
)


os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")

settings = get_gmail_auth_settings()
router = APIRouter()
provider_spec = OAuthProviderSpec(
    provider="gmail",
    client_secrets_file=settings.client_secrets_file,
    scopes=settings.scopes,
    redirect_uri=settings.redirect_uri,
    post_connect_redirect=settings.post_connect_redirect,
)


async def _persist_gmail_connection(user_id: str, creds: object) -> None:
    refresh_token = getattr(creds, "refresh_token", None)
    access_token = getattr(creds, "token", None)
    expiry = getattr(creds, "expiry", None)
    scopes = list(getattr(creds, "scopes", []) or [])

    await upsert_gmail_connection_service(
        user_id=user_id,
        google_email=None,
        refresh_token_encrypted=refresh_token,
        access_token=access_token,
        access_token_expires_at=expiry.isoformat() if expiry else None,
        scopes=scopes or None,
        status="active",
        revoked_at=None,
    )


@router.get("/oauth/gmail/start", response_model=OAuthStartResponse)
async def oauth_gmail_start(
    request: Request,
    force_consent: bool = False,
    return_to: str | None = None,
    auth_ctx: AuthContext = Depends(get_auth_context),
) -> OAuthStartResponse:
    return await start_oauth_flow(
        request=request,
        auth_ctx=auth_ctx,
        provider_spec=provider_spec,
        force_consent=force_consent,
        return_to=return_to,
    )


@router.get("/oauth/gmail/status/{transaction_id}", response_model=OAuthStatusResponse)
async def oauth_gmail_status(
    transaction_id: str,
    auth_ctx: AuthContext = Depends(get_auth_context),
) -> OAuthStatusResponse:
    return await get_oauth_status(
        transaction_id=transaction_id,
        auth_ctx=auth_ctx,
        provider_spec=provider_spec,
    )


@router.get("/oauth/gmail/callback")
async def oauth_gmail_callback(request: Request):
    return await callback_oauth_flow(
        request=request,
        provider_spec=provider_spec,
        persist_connection=_persist_gmail_connection,
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
