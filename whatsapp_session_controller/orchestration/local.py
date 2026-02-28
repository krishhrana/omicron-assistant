from __future__ import annotations

import asyncio
from urllib.parse import urlsplit, urlunsplit

import httpx

from whatsapp_session_controller.core.settings import WhatsAppSessionControllerSettings
from whatsapp_session_controller.orchestration.base import OrchestratedRuntime
from whatsapp_session_controller.services.runtime_types import RuntimeState


class LocalRuntimeOrchestrator:
    """Local/dev runtime adapter for deterministic non-ECS workflows."""

    def __init__(self, *, settings: WhatsAppSessionControllerSettings) -> None:
        self._settings = settings

    def _runtime_host(self, runtime_id: str) -> str:
        base = (self._settings.runtime_endpoint_host_template or "").strip()
        if base:
            return base.format(runtime_id=runtime_id)
        return "127.0.0.1"

    def _bridge_base_url(self, runtime_id: str) -> str:
        template = (self._settings.runtime_bridge_base_url_template or "").strip()
        if template:
            return template.format(runtime_id=runtime_id)
        return (
            f"{self._settings.runtime_endpoint_scheme}://{self._runtime_host(runtime_id)}:"
            f"{self._settings.runtime_bridge_port}"
        )

    def _mcp_url(self, runtime_id: str) -> str:
        template = (self._settings.runtime_mcp_url_template or "").strip()
        if template:
            return template.format(runtime_id=runtime_id)
        mcp_path = self._settings.runtime_mcp_path
        return (
            f"{self._settings.runtime_endpoint_scheme}://{self._runtime_host(runtime_id)}:"
            f"{self._settings.runtime_mcp_port}{mcp_path}"
        )

    @staticmethod
    def _join_probe_url(base_url: str, probe_path: str) -> str:
        split = urlsplit(base_url.rstrip("/"))
        path = probe_path if probe_path.startswith("/") else f"/{probe_path}"
        return urlunsplit((split.scheme, split.netloc, path, "", ""))

    async def _probe_url(self, url: str) -> bool:
        timeout = max(0.1, float(self._settings.runtime_health_probe_timeout_seconds))
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.get(url)
            return 200 <= response.status_code < 300
        except Exception:
            return False

    async def get_or_create_runtime(
        self,
        *,
        user_id: str,
        runtime_id: str,
        generation: int,
    ) -> OrchestratedRuntime:
        _ = user_id
        _ = generation
        return OrchestratedRuntime(
            runtime_id=runtime_id,
            bridge_base_url=self._bridge_base_url(runtime_id),
            mcp_url=self._mcp_url(runtime_id),
            task_arn=None,
        )

    async def disconnect_runtime(
        self,
        *,
        user_id: str,
        runtime_id: str,
        generation: int,
    ) -> None:
        _ = user_id
        _ = runtime_id
        _ = generation
        return None

    async def probe_runtime(
        self,
        *,
        runtime: OrchestratedRuntime,
    ) -> RuntimeState:
        if not self._settings.runtime_health_probe_enabled:
            return "ready"

        bridge_health_url = self._join_probe_url(
            runtime.bridge_base_url,
            self._settings.runtime_bridge_health_path,
        )
        mcp_health_url = self._join_probe_url(runtime.mcp_url, self._settings.runtime_mcp_health_path)
        bridge_ok, mcp_ok = await asyncio.gather(
            self._probe_url(bridge_health_url),
            self._probe_url(mcp_health_url),
        )
        return "ready" if bridge_ok and mcp_ok else "degraded"
