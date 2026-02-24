from __future__ import annotations

from app.core.settings import WhatsAppSessionSettings

from .base import WhatsAppRuntimeLease


class ControllerWhatsAppSessionProvider:
    """Placeholder for a future ECS/Kubernetes-backed WhatsApp session controller."""

    def __init__(self, settings: WhatsAppSessionSettings) -> None:
        self._settings = settings

    async def get_or_create(
        self,
        *,
        user_id: str,
        user_jwt: str,
    ) -> WhatsAppRuntimeLease:
        _ = user_id
        _ = user_jwt
        raise RuntimeError(
            "whatsapp_session_provider=controller is not implemented yet. "
            "Use WHATSAPP_SESSION_PROVIDER=local for now."
        )

    async def disconnect(
        self,
        *,
        user_id: str,
        runtime_id: str | None = None,
    ) -> None:
        _ = user_id
        _ = runtime_id
        raise RuntimeError(
            "whatsapp_session_provider=controller is not implemented yet."
        )
