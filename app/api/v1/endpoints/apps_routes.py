from __future__ import annotations

from fastapi import APIRouter, Depends

from app.agents.registry import is_browser_connected, is_whatsapp_connected
from app.auth import AuthContext, get_auth_context
from app.core.enums import SupportedApps
from app.schemas.endpoint_schemas.apps import SupportedApp, SupportedAppsResponse


router = APIRouter()


_APP_METADATA: dict[SupportedApps, dict[str, str | bool]] = {
    SupportedApps.GMAIL: {
        "display_name": "Gmail",
        "description": "AI assistant support for Gmail mailbox workflows.",
        "category": "integration",
        "requires_user_connection": True,
    },
    SupportedApps.GOOGLE_DRIVE: {
        "display_name": "Google Drive",
        "description": "AI assistant support for Google Drive file workflows.",
        "category": "integration",
        "requires_user_connection": True,
    },
    SupportedApps.BROWSER: {
        "display_name": "Browser",
        "description": "Playwright-powered browser automation agent.",
        "category": "browser",
        "requires_user_connection": False,
    },
    SupportedApps.WHATSAPP: {
        "display_name": "WhatsApp",
        "description": "WhatsApp MCP-powered messaging and chat retrieval agent.",
        "category": "messaging",
        "requires_user_connection": True,
    },
}


@router.get("/apps/supported", response_model=SupportedAppsResponse)
async def list_supported_apps(
    _: AuthContext = Depends(get_auth_context),
) -> SupportedAppsResponse:
    browser_available = is_browser_connected()
    whatsapp_available = is_whatsapp_connected()
    apps: list[SupportedApp] = []

    for app in SupportedApps:
        metadata = _APP_METADATA[app]
        runtime_available = True
        if app == SupportedApps.BROWSER:
            runtime_available = browser_available
        elif app == SupportedApps.WHATSAPP:
            runtime_available = whatsapp_available
        apps.append(
            SupportedApp(
                id=app.value,
                display_name=str(metadata["display_name"]),
                description=str(metadata["description"]),
                category=str(metadata["category"]),
                requires_user_connection=bool(metadata["requires_user_connection"]),
                runtime_available=runtime_available,
            )
        )

    return SupportedAppsResponse(apps=apps, total=len(apps))
