from __future__ import annotations

from fastapi import FastAPI
from openai import AsyncOpenAI

from app.core.settings import get_openai_settings

_openai_client: AsyncOpenAI | None = None


def init_openai_client(_: FastAPI | None = None) -> None:
    global _openai_client
    settings = get_openai_settings()
    if _openai_client is None:
        _openai_client = AsyncOpenAI(
            api_key=settings.api_key,
            max_retries=settings.max_retries,
        )


async def close_openai_client(_: FastAPI | None = None) -> None:
    global _openai_client
    client = _openai_client
    if client is not None:
        await client.close()
    _openai_client = None


def get_openai_client() -> AsyncOpenAI:
    global _openai_client
    if _openai_client is None:
        raise RuntimeError("OpenAI client not initialized")
    return _openai_client


def startup(): 
    init_openai_client()


async def shutdown(): 
    await close_openai_client()
