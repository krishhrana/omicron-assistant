from fastapi import APIRouter
from app.api.v1.endpoints import (
    agent_routes,
    apps_routes,
    gmail_auth,
    google_drive_auth,
    onboarding_routes,
    session_routes,
    whatsapp_connect,
)

api_router = APIRouter()
api_router.include_router(gmail_auth.router, tags=["gmail-auth"])
api_router.include_router(google_drive_auth.router, tags=["google-drive-auth"])
api_router.include_router(agent_routes.router, tags=["agents"])
api_router.include_router(apps_routes.router, tags=["apps"])
api_router.include_router(session_routes.router, tags=["sessions"])
api_router.include_router(onboarding_routes.router, tags=["onboarding"])
api_router.include_router(whatsapp_connect.router, tags=["whatsapp-connect"])
