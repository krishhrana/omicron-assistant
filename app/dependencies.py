from __future__ import annotations
import asyncio
import contextlib
import logging

from fastapi import FastAPI
import httpx
from openai import AsyncOpenAI

from agents.mcp import MCPServerStreamableHttp
from supabase import ClientOptions, create_async_client, AsyncClient

from app.core.settings import get_browser_agent_settings, get_openai_settings, get_settings

_openai_client: AsyncOpenAI | None = None
_supabase_client: AsyncClient | None = None
_browser_mcp_server: MCPServerStreamableHttp | None = None

logger = logging.getLogger(__name__)


async def _is_playwright_mcp_endpoint_usable(url: str, timeout_seconds: float = 3.0) -> bool:
    try:
        async with httpx.AsyncClient(timeout=timeout_seconds, follow_redirects=True) as client:
            response = await client.post(
                url,
                json={"jsonrpc": "2.0", "id": "probe", "method": "ping", "params": {}},
                headers={
                    "Accept": "application/json, text/event-stream",
                    "Content-Type": "application/json",
                },
            )
    except Exception:
        return False

    if response.status_code >= 500:
        return False
    if response.status_code in {404, 405, 501}:
        return False
    return True


async def init_google_tokens_encryption_key() -> None:
    settings = get_settings()
    if settings.google_tokens_encryption_key:
        return
    if not settings.supabase_service_role_key:
        raise RuntimeError(
            "SUPABASE_SERVICE_ROLE_KEY is required to fetch gmail_tokens_encryption_key from Vault"
        )

    vault_client = await create_async_client(
        settings.supabase_url, 
        settings.supabase_service_role_key, 
        options=ClientOptions(auto_refresh_token=False, persist_session=False)
        )
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


async def init_browser_mcp_server(_: FastAPI | None = None) -> None:
    global _browser_mcp_server
    if _browser_mcp_server is not None:
        return

    settings = get_browser_agent_settings()
    if not settings.playwright_mcp_url:
        return
    if not settings.playwright_mcp_connect_on_startup:
        # Production uses the Browser Session Controller + lazy per-session MCP servers.
        # Keep this as an explicit local-dev fallback only.
        return
    if not await _is_playwright_mcp_endpoint_usable(settings.playwright_mcp_url):
        logger.warning(
            "Playwright MCP endpoint is unreachable or invalid at %s; browser agent is disabled.",
            settings.playwright_mcp_url,
        )
        return

    server = MCPServerStreamableHttp(
        name="playwright",
        params={
            "url": settings.playwright_mcp_url,
            "timeout": settings.playwright_mcp_timeout,
            "sse_read_timeout": settings.playwright_mcp_sse_read_timeout,
        },
        cache_tools_list=True,
        client_session_timeout_seconds=settings.playwright_mcp_client_session_timeout_seconds,
        max_retry_attempts=settings.playwright_mcp_max_retry_attempts,
    )

    try:
        await server.connect()
    except BaseException as exc:
        if isinstance(exc, (KeyboardInterrupt, SystemExit)):
            raise
        logger.warning(
            "Failed to connect to Playwright MCP server at %s: %s",
            settings.playwright_mcp_url,
            exc,
        )
        if isinstance(exc, asyncio.CancelledError):
            return
        with contextlib.suppress(Exception):
            await server.cleanup()
        return

    _browser_mcp_server = server


async def close_browser_mcp_server() -> None:
    global _browser_mcp_server
    server = _browser_mcp_server
    if server is not None:
        await server.cleanup()
    _browser_mcp_server = None


def get_browser_mcp_server() -> MCPServerStreamableHttp:
    if _browser_mcp_server is None:
        raise RuntimeError(
            "Browser MCP server not initialized. Set PLAYWRIGHT_MCP_URL and "
            "PLAYWRIGHT_MCP_CONNECT_ON_STARTUP=true (local dev) and ensure the MCP server is reachable."
        )
    return _browser_mcp_server


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
    return await create_async_client(settings.supabase_url, settings.supabase_api_key, options=options)



async def startup(): 
    init_openai_client()
    await init_supabase_client()
    await init_google_tokens_encryption_key()
    await init_browser_mcp_server()


async def shutdown(): 
    await close_browser_mcp_server()
    await close_openai_client()
    await close_supabase_client()
    
