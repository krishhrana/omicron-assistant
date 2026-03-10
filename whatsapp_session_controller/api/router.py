from __future__ import annotations

from fastapi import APIRouter

from whatsapp_session_controller.api.endpoints import health, runtimes


api_router = APIRouter()
api_router.include_router(health.router, tags=["health"])
api_router.include_router(runtimes.router, tags=["runtimes"])
