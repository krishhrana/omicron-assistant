from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from pydantic import AliasChoices, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


settings_config = SettingsConfigDict(
    env_file=Path(__file__).resolve().parents[2] / ".env",
    env_file_encoding="utf-8",
    case_sensitive=False,
    extra="ignore",
)


def _parse_csv_or_json_list(raw: Any) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, list):
        return [str(item).strip() for item in raw if str(item).strip()]
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return []
        if text.startswith("["):
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                parsed = None
            if isinstance(parsed, list):
                return [str(item).strip() for item in parsed if str(item).strip()]
        return [part.strip() for part in text.split(",") if part.strip()]
    return [str(raw).strip()] if str(raw).strip() else []


class WhatsAppSessionControllerSettings(BaseSettings):
    app_title: str = Field(
        default="Omicron WhatsApp Session Controller",
        validation_alias="WHATSAPP_SESSION_CONTROLLER_APP_TITLE",
    )
    api_v1_prefix: str = Field(
        default="/v1",
        validation_alias="WHATSAPP_SESSION_CONTROLLER_API_V1_PREFIX",
    )
    host: str = Field(default="0.0.0.0", validation_alias="WHATSAPP_SESSION_CONTROLLER_HOST")
    port: int = Field(default=8101, validation_alias="WHATSAPP_SESSION_CONTROLLER_PORT")
    reload: bool = Field(default=False, validation_alias="WHATSAPP_SESSION_CONTROLLER_RELOAD")

    supabase_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices("SUPABASE_URL", "supabase_url"),
    )
    supabase_service_role_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("SUPABASE_SERVICE_ROLE_KEY", "supabase_service_role_key"),
    )
    runtime_lease_table: str = Field(
        default="controller_whatsapp_runtime_leases",
        validation_alias="WHATSAPP_CONTROLLER_RUNTIME_LEASE_TABLE",
    )

    jwt_secret: str | None = Field(
        default=None,
        validation_alias="WHATSAPP_SESSION_CONTROLLER_JWT_SECRET",
    )
    jwt_audience: str = Field(
        default="whatsapp-session-controller",
        validation_alias="WHATSAPP_SESSION_CONTROLLER_JWT_AUDIENCE",
    )
    jwt_issuer: str = Field(
        default="omicron-api",
        validation_alias="WHATSAPP_SESSION_CONTROLLER_JWT_ISSUER",
    )
    jwt_algorithm: str = Field(
        default="HS256",
        validation_alias="WHATSAPP_SESSION_CONTROLLER_JWT_ALGORITHM",
    )
    jwt_ttl_seconds: int = Field(
        default=60,
        validation_alias="WHATSAPP_SESSION_CONTROLLER_JWT_TTL_SECONDS",
    )

    runtime_sliding_ttl_seconds: int = Field(
        default=600,
        validation_alias="WHATSAPP_RUNTIME_SLIDING_TTL_SECONDS",
    )
    runtime_max_lifetime_seconds: int = Field(
        default=5400,
        validation_alias="WHATSAPP_RUNTIME_MAX_LIFETIME_SECONDS",
    )
    runtime_orchestrator: Literal["ecs", "local"] = Field(
        default="ecs",
        validation_alias="WHATSAPP_RUNTIME_ORCHESTRATOR",
    )
    runtime_endpoint_scheme: Literal["http", "https"] = Field(
        default="http",
        validation_alias="WHATSAPP_RUNTIME_ENDPOINT_SCHEME",
    )
    runtime_endpoint_host_template: str | None = Field(
        default=None,
        validation_alias="WHATSAPP_RUNTIME_ENDPOINT_HOST_TEMPLATE",
    )
    runtime_bridge_port: int = Field(
        default=8080,
        validation_alias="WHATSAPP_RUNTIME_BRIDGE_PORT",
    )
    runtime_mcp_port: int = Field(
        default=8000,
        validation_alias="WHATSAPP_RUNTIME_MCP_PORT",
    )
    runtime_mcp_path: str = Field(
        default="/mcp",
        validation_alias="WHATSAPP_RUNTIME_MCP_PATH",
    )
    runtime_bridge_base_url_template: str | None = Field(
        default=None,
        validation_alias="WHATSAPP_RUNTIME_BRIDGE_BASE_URL_TEMPLATE",
    )
    runtime_mcp_url_template: str | None = Field(
        default=None,
        validation_alias="WHATSAPP_RUNTIME_MCP_URL_TEMPLATE",
    )
    runtime_health_probe_enabled: bool = Field(
        default=True,
        validation_alias="WHATSAPP_RUNTIME_HEALTH_PROBE_ENABLED",
    )
    runtime_health_probe_timeout_seconds: float = Field(
        default=2.0,
        validation_alias="WHATSAPP_RUNTIME_HEALTH_PROBE_TIMEOUT_SECONDS",
    )
    runtime_bridge_health_path: str = Field(
        default="/health",
        validation_alias="WHATSAPP_RUNTIME_BRIDGE_HEALTH_PATH",
    )
    runtime_mcp_health_path: str = Field(
        default="/health",
        validation_alias="WHATSAPP_RUNTIME_MCP_HEALTH_PATH",
    )

    aws_region: str | None = Field(
        default=None,
        validation_alias="WHATSAPP_CONTROLLER_AWS_REGION",
    )
    aws_profile: str | None = Field(
        default=None,
        validation_alias="WHATSAPP_CONTROLLER_AWS_PROFILE",
    )
    ecs_cluster: str | None = Field(
        default=None,
        validation_alias="WHATSAPP_CONTROLLER_ECS_CLUSTER",
    )
    ecs_task_definition: str | None = Field(
        default=None,
        validation_alias="WHATSAPP_CONTROLLER_ECS_TASK_DEFINITION",
    )
    ecs_capacity_provider: str | None = Field(
        default=None,
        validation_alias="WHATSAPP_CONTROLLER_ECS_CAPACITY_PROVIDER",
    )
    ecs_subnets: list[str] = Field(
        default_factory=list,
        validation_alias="WHATSAPP_CONTROLLER_ECS_SUBNETS",
    )
    ecs_security_groups: list[str] = Field(
        default_factory=list,
        validation_alias="WHATSAPP_CONTROLLER_ECS_SECURITY_GROUPS",
    )
    ecs_assign_public_ip: bool = Field(
        default=False,
        validation_alias="WHATSAPP_CONTROLLER_ECS_ASSIGN_PUBLIC_IP",
    )
    ecs_launch_type: Literal["EC2", "FARGATE"] = Field(
        default="EC2",
        validation_alias="WHATSAPP_CONTROLLER_ECS_LAUNCH_TYPE",
    )
    ecs_started_by_prefix: str = Field(
        default="wa-runtime-",
        validation_alias="WHATSAPP_CONTROLLER_ECS_STARTED_BY_PREFIX",
    )

    model_config = settings_config

    @model_validator(mode="before")
    @classmethod
    def _normalize_network_lists(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        normalized = dict(data)
        for key in ("ecs_subnets", "ecs_security_groups"):
            if key in normalized:
                normalized[key] = _parse_csv_or_json_list(normalized[key])
        return normalized

    @model_validator(mode="after")
    def _validate_runtime_limits(self):
        if self.jwt_ttl_seconds <= 0:
            raise ValueError("WHATSAPP_SESSION_CONTROLLER_JWT_TTL_SECONDS must be greater than 0.")
        if self.runtime_sliding_ttl_seconds <= 0:
            raise ValueError("WHATSAPP_RUNTIME_SLIDING_TTL_SECONDS must be greater than 0.")
        if self.runtime_max_lifetime_seconds <= 0:
            raise ValueError("WHATSAPP_RUNTIME_MAX_LIFETIME_SECONDS must be greater than 0.")
        if self.runtime_max_lifetime_seconds < self.runtime_sliding_ttl_seconds:
            raise ValueError(
                "WHATSAPP_RUNTIME_MAX_LIFETIME_SECONDS must be >= "
                "WHATSAPP_RUNTIME_SLIDING_TTL_SECONDS."
            )
        if not (self.supabase_url or "").strip():
            raise ValueError("SUPABASE_URL is required for WhatsApp Session Controller.")
        if not (self.supabase_service_role_key or "").strip():
            raise ValueError(
                "SUPABASE_SERVICE_ROLE_KEY is required for WhatsApp Session Controller."
            )
        if not self.runtime_lease_table.strip():
            raise ValueError("WHATSAPP_CONTROLLER_RUNTIME_LEASE_TABLE must be non-empty.")
        if self.runtime_bridge_port <= 0 or self.runtime_bridge_port > 65535:
            raise ValueError("WHATSAPP_RUNTIME_BRIDGE_PORT must be between 1 and 65535.")
        if self.runtime_mcp_port <= 0 or self.runtime_mcp_port > 65535:
            raise ValueError("WHATSAPP_RUNTIME_MCP_PORT must be between 1 and 65535.")
        if self.runtime_health_probe_timeout_seconds <= 0:
            raise ValueError("WHATSAPP_RUNTIME_HEALTH_PROBE_TIMEOUT_SECONDS must be greater than 0.")
        if not self.runtime_mcp_path.startswith("/"):
            raise ValueError("WHATSAPP_RUNTIME_MCP_PATH must start with '/'.")
        if not self.runtime_bridge_health_path.startswith("/"):
            raise ValueError("WHATSAPP_RUNTIME_BRIDGE_HEALTH_PATH must start with '/'.")
        if not self.runtime_mcp_health_path.startswith("/"):
            raise ValueError("WHATSAPP_RUNTIME_MCP_HEALTH_PATH must start with '/'.")
        if not self.ecs_started_by_prefix.strip():
            raise ValueError("WHATSAPP_CONTROLLER_ECS_STARTED_BY_PREFIX must be non-empty.")
        if self.runtime_orchestrator == "ecs":
            if not (self.aws_region or "").strip():
                raise ValueError(
                    "WHATSAPP_CONTROLLER_AWS_REGION is required when WHATSAPP_RUNTIME_ORCHESTRATOR=ecs."
                )
            if not (self.ecs_cluster or "").strip():
                raise ValueError(
                    "WHATSAPP_CONTROLLER_ECS_CLUSTER is required when WHATSAPP_RUNTIME_ORCHESTRATOR=ecs."
                )
            if not (self.ecs_task_definition or "").strip():
                raise ValueError(
                    "WHATSAPP_CONTROLLER_ECS_TASK_DEFINITION is required when WHATSAPP_RUNTIME_ORCHESTRATOR=ecs."
                )
            if self.ecs_assign_public_ip:
                raise ValueError(
                    "WHATSAPP_CONTROLLER_ECS_ASSIGN_PUBLIC_IP must be false. "
                    "Public runtime exposure is not supported."
                )
            if not self.ecs_subnets:
                raise ValueError(
                    "WHATSAPP_CONTROLLER_ECS_SUBNETS is required for ECS runtime networking."
                )
            if not self.ecs_security_groups:
                raise ValueError(
                    "WHATSAPP_CONTROLLER_ECS_SECURITY_GROUPS is required for ECS runtime networking."
                )
            bridge_template = (self.runtime_bridge_base_url_template or "").lower()
            mcp_template = (self.runtime_mcp_url_template or "").lower()
            if "{task_public_ip}" in bridge_template or "{task_public_ip}" in mcp_template:
                raise ValueError(
                    "Runtime URL templates cannot use {task_public_ip}. "
                    "Public runtime endpoint resolution is not supported."
                )
        return self


@lru_cache(1)
def get_controller_settings() -> WhatsAppSessionControllerSettings:
    return WhatsAppSessionControllerSettings()
