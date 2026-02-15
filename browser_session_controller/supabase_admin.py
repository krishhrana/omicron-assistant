from __future__ import annotations

from supabase import AsyncClient, ClientOptions, create_async_client

from browser_session_controller.settings import get_settings


async def create_supabase_admin_client() -> AsyncClient:
    settings = get_settings()
    return await create_async_client(
        settings.supabase_url,
        settings.supabase_service_role_key,
        options=ClientOptions(auto_refresh_token=False, persist_session=False),
    )

