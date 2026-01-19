from fastapi import APIRouter
from app.api.v1.endpoints import gmail_auth, agent_routes

api_router = APIRouter()
api_router.include_router(gmail_auth.router, tags=["gmail-auth"])
api_router.include_router(agent_routes.router, tags=["agents"])
