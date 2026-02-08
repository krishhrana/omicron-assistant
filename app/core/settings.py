from __future__ import annotations
import json
from functools import cached_property, lru_cache
from pathlib import Path
from typing import List

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


settings_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parents[2] / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra='ignore'
    )

class Settings(BaseSettings):
    app_title: str = "Demo"
    api_v1_prefix: str = "/v1"
    session_secret_key: str = Field(...)
    supabase_url: str = Field(validation_alias='supabase_url')
    supabase_api_key: str = Field(validation_alias='supabase_api_key')
    supabase_jwt_secret: str | None = Field(default=None, validation_alias='supabase_jwt_secret')
    google_tokens_encryption_key: str | None = Field(default=None, validation_alias='gmail_tokens_encryption_key')
    supabase_service_role_key: str | None = Field(default=None, validation_alias='supabase_service_role_key')


    model_config = settings_config


class GoogleAuthSettings(BaseSettings): 
    client_secrets_file: str = Field(validation_alias='google_client_secrets_file')

    def _resolve_client_secrets_path(self) -> Path:
        secrets_path = Path(self.client_secrets_file)
        if not secrets_path.is_absolute():
            secrets_path = Path(__file__).resolve().parents[2] / secrets_path
        return secrets_path
    

    @cached_property
    def _client_secrets(self) -> dict[str, str]:
        secrets_path = self._resolve_client_secrets_path()
        data = json.loads(secrets_path.read_text(encoding="utf-8"))
        if "installed" in data:
            return data["installed"]
        if "web" in data:
            return data["web"]
        raise ValueError("Unsupported client secrets file format")

    @property
    def client_id(self) -> str:
        return self._client_secrets["client_id"]

    @property
    def client_secret(self) -> str:
        return self._client_secrets["client_secret"]

    @property
    def auth_uri(self) -> str:
        return self._client_secrets["auth_uri"]

    @property
    def token_uri(self) -> str:
        return self._client_secrets["token_uri"]


class GmailAuthSettings(GoogleAuthSettings): 
    scopes: List[str] = Field(validation_alias='gmail_scopes')
    redirect_uri: str = Field(validation_alias='gmail_redirect_uri')
    post_connect_redirect: str = Field(validation_alias='gmail_post_connect_redirect')

    model_config = settings_config


class GoogleDriveSettings(GoogleAuthSettings): 
    scopes: List[str] = Field(validation_alias='google_drive_scopes')
    redirect_uri: str = Field(validation_alias='google_drive_redirect_uri')
    post_connect_redirect: str = Field(validation_alias='google_drive_post_connect_redirect')

    model_config = settings_config
    


class OpenAISettings(BaseSettings): 
    api_key: str = Field(validation_alias='openai_api_key')
    max_retries: int = 5

    model_config = settings_config


class OrchestratorAgentSettings(BaseSettings): 
    model: str = Field(default='gpt-5.2', validation_alias='orchestrator_agent_model')
    reasoning_effort: str = Field(default='high', validation_alias='orchestrator_agent_reasoning_effort')
    reasoning_summary: str = Field(default='detailed', validation_alias='orchestrator_agent_reasoning_summary')

    model_config = settings_config


class GmailAgentSettings(BaseSettings): 
    model: str = Field(default='gpt-5.2', validation_alias='gmail_agent_model')
    reasoning_effort: str = Field(default='high', validation_alias='gmail_agent_reasoning_effort')
    reasoning_summary: str = Field(default='detailed', validation_alias='gmail_agent_reasoning_summary')

    model_config = settings_config


class GoogleDriveAgentSettings(BaseSettings): 
    model: str = Field(default='gpt-5.2', validation_alias='google_drive_agent_model')
    reasoning_effort: str = Field(default='high', validation_alias='google_drive_reasoning_effort')
    reasoning_summary: str = Field(default='detailed', validation_alias='google_drive_reasoning_summary')

    model_config = settings_config




@lru_cache(1)
def get_settings() -> Settings:
    return Settings()

@lru_cache(1)
def get_gmail_auth_settings() -> GmailAuthSettings:
    return GmailAuthSettings()


@lru_cache(1)
def get_google_drive_settings() -> GoogleDriveSettings:
    return GoogleDriveSettings()


def get_openai_settings() -> OpenAISettings:
    return OpenAISettings()


@lru_cache(1)
def get_orchestrator_agent_settings() -> OrchestratorAgentSettings:
    return OrchestratorAgentSettings()

@lru_cache(1)
def get_gmail_agent_settings() -> GmailAgentSettings:
    return GmailAgentSettings()

@lru_cache(1)
def get_google_drive_agent_settings() -> GoogleDriveAgentSettings:
    return GoogleDriveAgentSettings()

