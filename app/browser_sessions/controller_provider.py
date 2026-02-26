from __future__ import annotations

from app.core.settings import BrowserSessionSettings

from .base import BrowserRuntimeLease


class ControllerBrowserSessionProvider:
    """Placeholder for a future browser session controller provider."""

    def __init__(self, settings: BrowserSessionSettings) -> None:
        self._settings = settings

    async def get_or_create(
        self,
        *,
        user_id: str,
        user_jwt: str,
        session_id: str,
    ) -> BrowserRuntimeLease:
        _ = user_id
        _ = user_jwt
        _ = session_id
        raise RuntimeError(
            "browser_session_provider=controller is not implemented yet. "
            "Use BROWSER_SESSION_PROVIDER=local for now."
        )

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
        raise RuntimeError(
            "browser_session_provider=controller is not implemented yet."
        )
