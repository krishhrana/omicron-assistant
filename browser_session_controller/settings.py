from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


_config = SettingsConfigDict(case_sensitive=False, extra="ignore")


class ControllerSettings(BaseSettings):
    # Supabase (service role)
    supabase_url: str = Field(validation_alias="supabase_url")
    supabase_service_role_key: str = Field(validation_alias="supabase_service_role_key")

    # API -> controller auth (HS256)
    api_jwt_secret: str = Field(validation_alias="browser_session_controller_jwt_secret")
    api_jwt_audience: str = Field(
        default="browser-session-controller",
        validation_alias="browser_session_controller_jwt_audience",
    )

    # Controller -> runner (broker) auth (HS256)
    runner_broker_jwt_secret: str = Field(validation_alias="browser_runner_broker_jwt_secret")
    runner_broker_jwt_audience: str = Field(
        default="runner",
        validation_alias="browser_runner_broker_jwt_audience",
    )

    # Runner provisioning
    runner_namespace: str = Field(default="omicron-browser", validation_alias="browser_runner_namespace")
    runner_image: str = Field(validation_alias="browser_runner_image")
    runner_port: int = Field(default=8080, validation_alias="browser_runner_port")
    runner_service_account_name: str = Field(
        default="pw-runner",
        validation_alias="browser_runner_service_account_name",
    )
    controller_internal_url: str = Field(
        validation_alias="browser_session_controller_internal_url",
        description="Cluster URL runner Pods use to call the controller broker endpoint.",
    )

    # Artifacts (optional). If configured, an uploader sidecar copies /output to S3 on pod termination.
    artifacts_s3_bucket: str | None = Field(default=None, validation_alias="browser_runner_artifacts_s3_bucket")
    artifacts_s3_prefix_base: str = Field(
        default="pw-videos",
        validation_alias="browser_runner_artifacts_s3_prefix_base",
    )

    # Session lifecycle
    ttl_seconds_default: int = Field(default=600, validation_alias="browser_session_ttl_seconds_default")
    starting_stale_seconds: int = Field(default=120, validation_alias="browser_session_starting_stale_seconds")
    startup_timeout_seconds: int = Field(default=120, validation_alias="browser_runner_startup_timeout_seconds")
    reaper_interval_seconds: int = Field(default=30, validation_alias="browser_session_reaper_interval_seconds")

    # Secrets in Vault
    vault_secret_prefix: str = Field(
        default="playwright_secrets_",
        validation_alias="browser_runner_vault_secret_prefix",
        description="Vault secret name prefix. Full name is <prefix><user_id>.",
    )

    model_config = _config


def get_settings() -> ControllerSettings:
    return ControllerSettings()

