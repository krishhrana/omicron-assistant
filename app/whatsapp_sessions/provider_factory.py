from __future__ import annotations

from functools import lru_cache

from app.core.settings import get_whatsapp_session_settings

from .base import WhatsAppSessionProvider
from .controller_provider import ControllerWhatsAppSessionProvider
from .local_provider import LocalWhatsAppSessionProvider


@lru_cache(1)
def get_whatsapp_session_provider() -> WhatsAppSessionProvider:
    settings = get_whatsapp_session_settings()
    provider = settings.provider.strip().lower()

    if provider == "local":
        return LocalWhatsAppSessionProvider(settings)
    if provider == "controller":
        return ControllerWhatsAppSessionProvider(settings)

    raise RuntimeError(f"Unsupported WhatsApp session provider: {settings.provider}")
