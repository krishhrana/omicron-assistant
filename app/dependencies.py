from __future__ import annotations

from agents import set_tracing_export_api_key
from fastapi import FastAPI
from openai import AsyncOpenAI

from supabase import ClientOptions, create_async_client, AsyncClient

from app.core.settings import (
    get_openai_settings,
    get_settings,
    validate_startup_security_configuration,
)

_openai_client: AsyncOpenAI | None = None
_supabase_client: AsyncClient | None = None


async def init_google_tokens_encryption_key() -> None:
    settings = get_settings()
    if settings.google_tokens_encryption_key:
        return
    vault_client = await create_supabase_service_client()
    try:
        response = await (
            vault_client.rpc(
                "get_vault_secret",
                {"secret_name": "gmail_tokens_encryption_key"},
            )
            .execute()
        )
    finally:
        await vault_client.postgrest.aclose()

    secret = response.data if response else None
    if not secret:
        raise RuntimeError("Vault secret gmail_tokens_encryption_key not found via get_vault_secret()")

    settings.google_tokens_encryption_key = secret



def init_openai_client(_: FastAPI | None = None) -> None:
    global _openai_client
    settings = get_openai_settings()
    set_tracing_export_api_key(settings.api_key)
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


async def init_supabase_client(_: FastAPI | None = None) -> None:
    global _supabase_client
    if _supabase_client is None:
        settings = get_settings()
        _supabase_client = await create_async_client(settings.supabase_url, settings.supabase_api_key)


async def close_supabase_client(): 
    global _supabase_client
    client = _supabase_client
    if client is not None:
        await client.postgrest.aclose()
    _supabase_client = None

def get_supabase_client() -> AsyncClient:
    if _supabase_client is None:
        raise RuntimeError("Supabase client not initialized")
    return _supabase_client


async def create_supabase_user_client(user_jwt: str) -> AsyncClient:
    settings = get_settings()
    if not user_jwt:
        raise RuntimeError("User JWT is required for per-request Supabase access")
    token = user_jwt
    if token.lower().startswith("bearer "):
        token = token.split(None, 1)[1]
    options = ClientOptions(
        auto_refresh_token=False,
        persist_session=False,
        headers={"Authorization": f"Bearer {token}"},
    )
    return await create_async_client(
        settings.supabase_url,
        settings.supabase_api_key,
        options=options,
    )


async def create_supabase_service_client() -> AsyncClient:
    settings = get_settings()
    if not settings.supabase_service_role_key:
        raise RuntimeError(
            "SUPABASE_SERVICE_ROLE_KEY is required for service-role Supabase access"
        )
    options = ClientOptions(auto_refresh_token=False, persist_session=False)
    return await create_async_client(
        settings.supabase_url,
        settings.supabase_service_role_key,
        options=options,
    )


async def startup():
    validate_startup_security_configuration()
    init_openai_client()
    await init_supabase_client()
    await init_google_tokens_encryption_key()


async def shutdown(): 
    await close_openai_client()
    await close_supabase_client()
    
