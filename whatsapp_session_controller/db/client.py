from __future__ import annotations

from supabase import AsyncClient, ClientOptions, create_async_client

from whatsapp_session_controller.core.settings import get_controller_settings


async def create_service_supabase_client() -> AsyncClient:
    settings = get_controller_settings()
    url = (settings.supabase_url or "").strip()
    service_key = (settings.supabase_service_role_key or "").strip()
    if not url or not service_key:
        raise RuntimeError(
            "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required for controller DB access."
        )

    options = ClientOptions(auto_refresh_token=False, persist_session=False)
    return await create_async_client(url, service_key, options=options)
