from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.auth import AuthContext, get_auth_context
from app.schemas.endpoint_schemas.onboarding import (
    BrowserCredentialsResponse,
    BrowserCredentialMetadata,
    BrowserCredentialUpsertPayload,
    OnboardingDeleteCredentialResponse,
    OnboardingProfileUpsertPayload,
    OnboardingStateResponse,
    UserProfileResponse,
)
from app.services.onboarding_service import (
    delete_browser_credential,
    get_onboarding_state,
    list_browser_credentials_metadata,
    mark_onboarding_complete,
    save_user_profile,
    upsert_browser_credential,
)


router = APIRouter()


@router.get("/onboarding/state", response_model=OnboardingStateResponse)
async def get_onboarding_state_route(
    auth_ctx: AuthContext = Depends(get_auth_context),
):
    return await get_onboarding_state(
        user_id=auth_ctx.user_id,
        user_jwt=auth_ctx.token,
    )


@router.put("/onboarding/profile", response_model=UserProfileResponse)
async def upsert_onboarding_profile(
    payload: OnboardingProfileUpsertPayload,
    auth_ctx: AuthContext = Depends(get_auth_context),
):
    try:
        return await save_user_profile(
            user_id=auth_ctx.user_id,
            user_jwt=auth_ctx.token,
            name=payload.name,
            city=payload.city,
            age=payload.age,
            gender=payload.gender,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/onboarding/browser-credentials", response_model=BrowserCredentialsResponse)
async def list_onboarding_browser_credentials(
    auth_ctx: AuthContext = Depends(get_auth_context),
):
    credentials = await list_browser_credentials_metadata(user_id=auth_ctx.user_id)
    return BrowserCredentialsResponse(credentials=credentials)


@router.post(
    "/onboarding/browser-credentials",
    response_model=BrowserCredentialMetadata,
)
async def upsert_onboarding_browser_credential(
    payload: BrowserCredentialUpsertPayload,
    auth_ctx: AuthContext = Depends(get_auth_context),
):
    try:
        return await upsert_browser_credential(
            user_id=auth_ctx.user_id,
            site_name=payload.site_name,
            login_url=payload.login_url,
            username=payload.username,
            password=payload.password,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete(
    "/onboarding/browser-credentials/{site_key}",
    response_model=OnboardingDeleteCredentialResponse,
)
async def delete_onboarding_browser_credential(
    site_key: str,
    auth_ctx: AuthContext = Depends(get_auth_context),
):
    deleted = await delete_browser_credential(
        user_id=auth_ctx.user_id,
        site_key=site_key,
    )
    if not deleted:
        raise HTTPException(status_code=404, detail="Browser credential not found")
    return OnboardingDeleteCredentialResponse(ok=True)


@router.post("/onboarding/complete", response_model=OnboardingStateResponse)
async def complete_onboarding(
    auth_ctx: AuthContext = Depends(get_auth_context),
):
    try:
        return await mark_onboarding_complete(
            user_id=auth_ctx.user_id,
            user_jwt=auth_ctx.token,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
