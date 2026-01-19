from contextlib import asynccontextmanager

from fastapi import FastAPI
from starlette.middleware.sessions import SessionMiddleware

from app.api.v1.router import api_router
from app.core.settings import get_settings
from app.dependencies import close_openai_client, init_openai_client


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_openai_client()
    try:
        yield
    finally:
        await close_openai_client()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_title, lifespan=lifespan)
    app.include_router(api_router, prefix=settings.api_v1_prefix)
    app.add_middleware(SessionMiddleware, secret_key=settings.session_secret_key)
    return app


app = create_app()
