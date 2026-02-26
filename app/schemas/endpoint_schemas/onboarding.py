from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class OnboardingProfileUpsertPayload(BaseModel):
    name: str
    city: str | None = None
    age: int | None = None
    gender: str | None = None


class BrowserCredentialUpsertPayload(BaseModel):
    site_name: str
    login_url: str | None = None
    username: str
    password: str


class UserProfileResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    user_id: str
    name: str
    city: str | None = None
    age: int | None = None
    gender: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class BrowserCredentialMetadata(BaseModel):
    site_key: str
    site_name: str
    login_url: str | None = None
    username_masked: str
    created_at: str | None = None


class BrowserCredentialsResponse(BaseModel):
    credentials: list[BrowserCredentialMetadata] = Field(default_factory=list)


class OnboardingConnectionsResponse(BaseModel):
    gmail: bool
    google_drive: bool
    whatsapp: bool
    connected_app_ids: list[str] = Field(default_factory=list)
    connected_count: int


class OnboardingRequirementsResponse(BaseModel):
    profile_complete: bool
    app_connected: bool
    browser_credentials_added: bool


class OnboardingStateResponse(BaseModel):
    is_complete: bool
    can_complete: bool
    current_step: int
    profile: UserProfileResponse | None = None
    connections: OnboardingConnectionsResponse
    website_credentials: list[BrowserCredentialMetadata] = Field(default_factory=list)
    requirements: OnboardingRequirementsResponse
    onboarding_completed_at: str | None = None


class OnboardingDeleteCredentialResponse(BaseModel):
    ok: bool
