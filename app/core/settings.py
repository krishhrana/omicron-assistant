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
    browser_runner_vault_secret_prefix: str = Field(
        default="browser_secrets_",
        validation_alias="browser_runner_vault_secret_prefix",
    )


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
    model: str = Field(default='gpt-5-mini', validation_alias='google_drive_agent_model')
    reasoning_effort: str = Field(default='high', validation_alias='google_drive_reasoning_effort')
    reasoning_summary: str = Field(default='detailed', validation_alias='google_drive_reasoning_summary')

    model_config = settings_config


class BrowserAgentSettings(BaseSettings):
    model: str = Field(default='gpt-5.2', validation_alias='browser_agent_model')
    reasoning_effort: str = Field(default='medium', validation_alias='browser_agent_reasoning_effort')
    reasoning_summary: str = Field(default='detailed', validation_alias='browser_agent_reasoning_summary')
    playwright_mcp_url: str | None = Field(default=None, validation_alias='playwright_mcp_url')
    playwright_mcp_timeout: int = Field(default=120, validation_alias='playwright_mcp_timeout')
    playwright_mcp_sse_read_timeout: int = Field(
        default=600,
        validation_alias='playwright_mcp_sse_read_timeout',
    )
    playwright_mcp_client_session_timeout_seconds: int = Field(
        default=120,
        validation_alias='playwright_mcp_client_session_timeout_seconds',
    )
    playwright_mcp_max_retry_attempts: int = Field(
        default=2,
        validation_alias='playwright_mcp_max_retry_attempts',
    )
    playwright_mcp_connect_on_startup: bool = Field(
        default=False,
        validation_alias="playwright_mcp_connect_on_startup",
    )
    playwright_mcp_auth_token: str | None = Field(
        default=None,
        validation_alias="playwright_mcp_auth_token",
    )

    model_config = settings_config


class WhatsAppAgentSettings(BaseSettings):
    model: str = Field(default='gpt-5.2', validation_alias='whatsapp_agent_model')
    reasoning_effort: str = Field(default='medium', validation_alias='whatsapp_agent_reasoning_effort')
    reasoning_summary: str = Field(default='detailed', validation_alias='whatsapp_agent_reasoning_summary')
    whatsapp_mcp_url: str | None = Field(
        default='http://127.0.0.1:8000/mcp',
        validation_alias='whatsapp_mcp_url',
    )
    whatsapp_mcp_jwt_audience: str = Field(
        default="whatsapp-mcp",
        validation_alias="whatsapp_mcp_jwt_audience",
    )
    whatsapp_mcp_jwt_subject: str = Field(
        default="omicron-api",
        validation_alias="whatsapp_mcp_jwt_subject",
    )
    whatsapp_mcp_jwt_scopes: str = Field(
        default="whatsapp:mcp whatsapp:send whatsapp:download",
        validation_alias="whatsapp_mcp_jwt_scopes",
    )
    whatsapp_mcp_timeout: int = Field(default=120, validation_alias='whatsapp_mcp_timeout')
    whatsapp_mcp_sse_read_timeout: int = Field(
        default=600,
        validation_alias='whatsapp_mcp_sse_read_timeout',
    )
    whatsapp_mcp_client_session_timeout_seconds: int = Field(
        default=120,
        validation_alias='whatsapp_mcp_client_session_timeout_seconds',
    )
    whatsapp_mcp_max_retry_attempts: int = Field(
        default=2,
        validation_alias='whatsapp_mcp_max_retry_attempts',
    )
    whatsapp_mcp_connect_on_startup: bool = Field(
        default=True,
        validation_alias='whatsapp_mcp_connect_on_startup',
    )

    model_config = settings_config


class WhatsAppSessionSettings(BaseSettings):
    provider: str = Field(default="local", validation_alias="whatsapp_session_provider")
    bridge_base_url: str = Field(
        default="http://127.0.0.1:8080",
        validation_alias="whatsapp_bridge_base_url",
    )
    bridge_jwt_secret: str | None = Field(
        default=None,
        validation_alias="whatsapp_bridge_jwt_secret",
    )
    bridge_jwt_audience: str = Field(
        default="whatsapp-bridge",
        validation_alias="whatsapp_bridge_jwt_audience",
    )
    bridge_jwt_issuer: str = Field(
        default="omicron-api",
        validation_alias="whatsapp_bridge_jwt_issuer",
    )
    bridge_jwt_ttl_seconds: int = Field(
        default=60,
        validation_alias="whatsapp_bridge_jwt_ttl_seconds",
    )
    bridge_timeout_seconds: float = Field(
        default=10.0,
        validation_alias="whatsapp_bridge_timeout_seconds",
    )
    controller_url: str | None = Field(
        default=None,
        validation_alias="whatsapp_session_controller_url",
    )
    controller_jwt_secret: str | None = Field(
        default=None,
        validation_alias="whatsapp_session_controller_jwt_secret",
    )
    controller_jwt_audience: str = Field(
        default="whatsapp-session-controller",
        validation_alias="whatsapp_session_controller_jwt_audience",
    )
    controller_timeout_seconds: float = Field(
        default=10.0,
        validation_alias="whatsapp_session_controller_timeout_seconds",
    )

    model_config = settings_config


class BrowserSessionControllerSettings(BaseSettings):
    # Internal controller that provisions per-session Playwright MCP runners.
    url: str | None = Field(default=None, validation_alias="browser_session_controller_url")
    jwt_secret: str | None = Field(
        default=None,
        validation_alias="browser_session_controller_jwt_secret",
    )
    jwt_audience: str = Field(
        default="browser-session-controller",
        validation_alias="browser_session_controller_jwt_audience",
    )
    timeout_seconds: float = Field(
        default=10.0,
        validation_alias="browser_session_controller_timeout_seconds",
    )

    model_config = settings_config


class StartupConfigError(RuntimeError):
    """Raised when required runtime security configuration is missing."""


def _is_non_empty(value: str | None) -> bool:
    return bool(value and value.strip())


def validate_startup_security_configuration() -> None:
    """Fail fast on missing auth/security config for API, bridge, and MCP control planes."""
    settings = get_settings()
    browser_agent = get_browser_agent_settings()
    whatsapp_agent = get_whatsapp_agent_settings()
    whatsapp_session = get_whatsapp_session_settings()
    browser_controller = get_browser_session_controller_settings()

    errors: list[str] = []

    has_supabase_jwt_secret = _is_non_empty(settings.supabase_jwt_secret)
    has_supabase_native_config = _is_non_empty(settings.supabase_url) and _is_non_empty(settings.supabase_api_key)
    if not has_supabase_jwt_secret and not has_supabase_native_config:
        errors.append(
            "Configure SUPABASE_JWT_SECRET or both SUPABASE_URL and SUPABASE_API_KEY for token validation."
        )

    has_bridge_jwt_secret = _is_non_empty(whatsapp_session.bridge_jwt_secret)
    whatsapp_provider = whatsapp_session.provider.strip().lower()
    if whatsapp_provider == "local":
        if not has_bridge_jwt_secret:
            errors.append(
                "WHATSAPP_BRIDGE_JWT_SECRET is required when WHATSAPP_SESSION_PROVIDER=local."
            )
    elif whatsapp_provider == "controller":
        if not _is_non_empty(whatsapp_session.controller_url):
            errors.append(
                "WHATSAPP_SESSION_CONTROLLER_URL is required when WHATSAPP_SESSION_PROVIDER=controller."
            )
        if not _is_non_empty(whatsapp_session.controller_jwt_secret):
            errors.append(
                "WHATSAPP_SESSION_CONTROLLER_JWT_SECRET is required when WHATSAPP_SESSION_PROVIDER=controller."
            )

    if _is_non_empty(whatsapp_session.controller_jwt_secret) and not _is_non_empty(whatsapp_session.controller_url):
        errors.append(
            "WHATSAPP_SESSION_CONTROLLER_URL is required when WHATSAPP_SESSION_CONTROLLER_JWT_SECRET is configured."
        )

    if _is_non_empty(browser_controller.url) and not _is_non_empty(browser_controller.jwt_secret):
        errors.append(
            "BROWSER_SESSION_CONTROLLER_JWT_SECRET is required when BROWSER_SESSION_CONTROLLER_URL is configured."
        )
    if _is_non_empty(browser_controller.jwt_secret) and not _is_non_empty(browser_controller.url):
        errors.append(
            "BROWSER_SESSION_CONTROLLER_URL is required when BROWSER_SESSION_CONTROLLER_JWT_SECRET is configured."
        )

    if browser_agent.playwright_mcp_connect_on_startup:
        if not _is_non_empty(browser_agent.playwright_mcp_url):
            errors.append(
                "PLAYWRIGHT_MCP_URL is required when PLAYWRIGHT_MCP_CONNECT_ON_STARTUP=true."
            )
        if not _is_non_empty(browser_agent.playwright_mcp_auth_token):
            errors.append(
                "PLAYWRIGHT_MCP_AUTH_TOKEN is required when PLAYWRIGHT_MCP_CONNECT_ON_STARTUP=true."
            )

    if whatsapp_agent.whatsapp_mcp_connect_on_startup:
        if not _is_non_empty(whatsapp_agent.whatsapp_mcp_url):
            errors.append(
                "WHATSAPP_MCP_URL is required when WHATSAPP_MCP_CONNECT_ON_STARTUP=true."
            )
        if not has_bridge_jwt_secret:
            errors.append(
                "WHATSAPP_BRIDGE_JWT_SECRET is required when WHATSAPP_MCP_CONNECT_ON_STARTUP=true."
            )
        if not _is_non_empty(whatsapp_agent.whatsapp_mcp_jwt_audience):
            errors.append(
                "WHATSAPP_MCP_JWT_AUDIENCE is required when WHATSAPP_MCP_CONNECT_ON_STARTUP=true."
            )
        if not _is_non_empty(whatsapp_agent.whatsapp_mcp_jwt_subject):
            errors.append(
                "WHATSAPP_MCP_JWT_SUBJECT is required when WHATSAPP_MCP_CONNECT_ON_STARTUP=true."
            )
        if not _is_non_empty(whatsapp_agent.whatsapp_mcp_jwt_scopes):
            errors.append(
                "WHATSAPP_MCP_JWT_SCOPES is required when WHATSAPP_MCP_CONNECT_ON_STARTUP=true."
            )

    if errors:
        detail = "\n".join(f"- {entry}" for entry in errors)
        raise StartupConfigError(f"Invalid startup security configuration:\n{detail}")


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


@lru_cache(1)
def get_browser_agent_settings() -> BrowserAgentSettings:
    return BrowserAgentSettings()


@lru_cache(1)
def get_whatsapp_agent_settings() -> WhatsAppAgentSettings:
    return WhatsAppAgentSettings()


@lru_cache(1)
def get_whatsapp_session_settings() -> WhatsAppSessionSettings:
    return WhatsAppSessionSettings()


@lru_cache(1)
def get_browser_session_controller_settings() -> BrowserSessionControllerSettings:
    return BrowserSessionControllerSettings()
