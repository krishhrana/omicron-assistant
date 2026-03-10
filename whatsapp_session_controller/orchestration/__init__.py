from __future__ import annotations

from whatsapp_session_controller.core.settings import get_controller_settings
from whatsapp_session_controller.orchestration.base import RuntimeOrchestrator
from whatsapp_session_controller.orchestration.ecs import ECSRuntimeOrchestrator
from whatsapp_session_controller.orchestration.local import LocalRuntimeOrchestrator


_runtime_orchestrator: RuntimeOrchestrator | None = None


def get_runtime_orchestrator() -> RuntimeOrchestrator:
    global _runtime_orchestrator
    if _runtime_orchestrator is not None:
        return _runtime_orchestrator

    settings = get_controller_settings()
    provider = settings.runtime_orchestrator.strip().lower()
    if provider == "ecs":
        _runtime_orchestrator = ECSRuntimeOrchestrator(settings=settings)
        return _runtime_orchestrator
    if provider == "local":
        _runtime_orchestrator = LocalRuntimeOrchestrator(settings=settings)
        return _runtime_orchestrator

    raise RuntimeError(
        "Unsupported runtime orchestrator provider. "
        "Expected one of: ecs, local."
    )
