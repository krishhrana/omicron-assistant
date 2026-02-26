from __future__ import annotations

from pydantic import BaseModel


class SupportedApp(BaseModel):
    id: str
    display_name: str
    description: str
    category: str
    requires_user_connection: bool
    runtime_available: bool


class SupportedAppsResponse(BaseModel):
    apps: list[SupportedApp]
    total: int
