from __future__ import annotations

import pytest

from whatsapp_session_controller.core.settings import WhatsAppSessionControllerSettings


def _base_settings_kwargs() -> dict[str, object]:
    return {
        "_env_file": None,
        "WHATSAPP_SESSION_CONTROLLER_JWT_SECRET": "controller-secret",
        "SUPABASE_URL": "https://example.supabase.co",
        "SUPABASE_SERVICE_ROLE_KEY": "service-role-key",
        "WHATSAPP_RUNTIME_ORCHESTRATOR": "ecs",
        "WHATSAPP_CONTROLLER_AWS_REGION": "us-west-2",
        "WHATSAPP_CONTROLLER_ECS_CLUSTER": "cluster-a",
        "WHATSAPP_CONTROLLER_ECS_TASK_DEFINITION": "wa-runtime:1",
        "WHATSAPP_CONTROLLER_ECS_SUBNETS": ["subnet-1"],
        "WHATSAPP_CONTROLLER_ECS_SECURITY_GROUPS": ["sg-1"],
    }


def test_rejects_public_ip_assignment() -> None:
    with pytest.raises(ValueError, match="WHATSAPP_CONTROLLER_ECS_ASSIGN_PUBLIC_IP"):
        WhatsAppSessionControllerSettings(
            **_base_settings_kwargs(),
            WHATSAPP_CONTROLLER_ECS_ASSIGN_PUBLIC_IP=True,
        )


def test_requires_security_groups_and_subnets() -> None:
    with pytest.raises(ValueError, match="WHATSAPP_CONTROLLER_ECS_SUBNETS"):
        WhatsAppSessionControllerSettings(
            **_base_settings_kwargs(),
            WHATSAPP_CONTROLLER_ECS_SUBNETS=[],
        )

    with pytest.raises(ValueError, match="WHATSAPP_CONTROLLER_ECS_SECURITY_GROUPS"):
        WhatsAppSessionControllerSettings(
            **_base_settings_kwargs(),
            WHATSAPP_CONTROLLER_ECS_SECURITY_GROUPS=[],
        )


def test_rejects_task_public_ip_placeholder() -> None:
    with pytest.raises(ValueError, match="task_public_ip"):
        WhatsAppSessionControllerSettings(
            **_base_settings_kwargs(),
            WHATSAPP_RUNTIME_BRIDGE_BASE_URL_TEMPLATE="http://{task_public_ip}:8080",
        )


def test_accepts_private_endpoint_template() -> None:
    settings = WhatsAppSessionControllerSettings(
        **_base_settings_kwargs(),
        WHATSAPP_RUNTIME_BRIDGE_BASE_URL_TEMPLATE="http://{task_private_ip}:8080",
        WHATSAPP_RUNTIME_MCP_URL_TEMPLATE="http://{task_private_ip}:8000/mcp",
    )
    assert settings.runtime_bridge_base_url_template is not None
