from __future__ import annotations

from functools import lru_cache

from app.core.settings import get_browser_session_settings

from .base import BrowserSessionProvider
from .controller_provider import ControllerBrowserSessionProvider
from .local_provider import LocalBrowserSessionProvider


@lru_cache(1)
def get_browser_session_provider() -> BrowserSessionProvider:
    settings = get_browser_session_settings()
    provider = settings.provider.strip().lower()

    if provider == "local":
        return LocalBrowserSessionProvider(settings)
    if provider == "controller":
        return ControllerBrowserSessionProvider(settings)

    raise RuntimeError(f"Unsupported browser session provider: {settings.provider}")
