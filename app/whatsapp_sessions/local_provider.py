from __future__ import annotations

from app.core.settings import WhatsAppSessionSettings

from .base import WhatsAppRuntimeLease


class LocalWhatsAppSessionProvider:
    """Single-host local provider used in development environments."""

    def __init__(self, settings: WhatsAppSessionSettings) -> None:
        self._settings = settings

    async def get_or_create(
        self,
        *,
        user_id: str,
        user_jwt: str,
    ) -> WhatsAppRuntimeLease:
        _ = user_jwt
        return WhatsAppRuntimeLease(
            runtime_id=f"local-{user_id}",
            bridge_base_url=self._settings.bridge_base_url.rstrip("/"),
        )

    async def read_current(
        self,
        *,
        user_id: str,
        user_jwt: str,
    ) -> WhatsAppRuntimeLease | None:
        return await self.get_or_create(user_id=user_id, user_jwt=user_jwt)

    async def disconnect(
        self,
        *,
        user_id: str,
        user_jwt: str,
        runtime_id: str | None = None,
    ) -> None:
        _ = user_id
        _ = user_jwt
        _ = runtime_id
        return

    async def touch(
        self,
        *,
        user_id: str,
        user_jwt: str,
        runtime_id: str | None = None,
    ) -> None:
        _ = user_id
        _ = user_jwt
        _ = runtime_id
        return
