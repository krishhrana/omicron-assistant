from __future__ import annotations

from app.core.settings import BrowserSessionSettings

from .base import BrowserRuntimeLease


class LocalBrowserSessionProvider:
    """Single-host local provider used in development environments."""

    def __init__(self, settings: BrowserSessionSettings) -> None:
        self._settings = settings

    async def get_or_create(
        self,
        *,
        user_id: str,
        user_jwt: str,
        session_id: str,
    ) -> BrowserRuntimeLease:
        _ = user_jwt
        return BrowserRuntimeLease(runtime_id=f"local-{user_id}-{session_id}")

    async def disconnect(
        self,
        *,
        user_id: str,
        session_id: str,
        runtime_id: str | None = None,
    ) -> None:
        _ = user_id
        _ = session_id
        _ = runtime_id
        return
