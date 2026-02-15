from fastapi import APIRouter
from app.api.v1.endpoints import gmail_auth, google_drive_auth, agent_routes, session_routes

api_router = APIRouter()
api_router.include_router(gmail_auth.router, tags=["gmail-auth"])
api_router.include_router(google_drive_auth.router, tags=["google-drive-auth"])
api_router.include_router(agent_routes.router, tags=["agents"])
api_router.include_router(session_routes.router, tags=["sessions"])
