from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from whatsapp_session_controller.api.router import api_router
from whatsapp_session_controller.core.settings import get_controller_settings


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Phase 1: no external resources to initialize yet.
    yield


def create_app() -> FastAPI:
    settings = get_controller_settings()
    app = FastAPI(title=settings.app_title, lifespan=lifespan)
    app.include_router(api_router, prefix=settings.api_v1_prefix)

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()

