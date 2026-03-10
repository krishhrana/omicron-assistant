from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from whatsapp_session_controller.services.runtime_types import RuntimeState


@dataclass(frozen=True)
class OrchestratedRuntime:
    runtime_id: str
    bridge_base_url: str
    mcp_url: str
    task_arn: str | None = None


class RuntimeOrchestrator(Protocol):
    async def get_or_create_runtime(
        self,
        *,
        user_id: str,
        runtime_id: str,
        generation: int,
    ) -> OrchestratedRuntime: ...

    async def disconnect_runtime(
        self,
        *,
        user_id: str,
        runtime_id: str,
        generation: int,
    ) -> None: ...

    async def probe_runtime(
        self,
        *,
        runtime: OrchestratedRuntime,
    ) -> RuntimeState: ...
