from __future__ import annotations

import asyncio
from collections.abc import Iterable
from typing import TYPE_CHECKING, Any

import httpx
from agents import RunContextWrapper
from agents.mcp import MCPServer, MCPServerStreamableHttp
from mcp import Tool as MCPTool
from mcp.types import CallToolResult, GetPromptResult, ListPromptsResult

from app.whatsapp_sessions.base import WhatsAppSessionProvider
from app.whatsapp_sessions.bridge_auth import mint_whatsapp_internal_token

if TYPE_CHECKING:
    from agents.agent import AgentBase


def _split_claim_values(raw: str) -> list[str]:
    return [part.strip() for part in raw.replace(",", " ").split() if part.strip()]


def _normalize_claim_values(values: str | Iterable[str], *, claim_name: str) -> tuple[str, ...]:
    if isinstance(values, str):
        normalized = _split_claim_values(values)
    else:
        normalized = []
        for value in values:
            if isinstance(value, str):
                normalized.extend(_split_claim_values(value))
    deduped = tuple(dict.fromkeys(normalized))
    if not deduped:
        raise RuntimeError(f"{claim_name} must include at least one value.")
    return deduped


class _WhatsAppInternalJWTAuth(httpx.Auth):
    """Inject a short-lived internal JWT on each outgoing MCP HTTP request."""

    def __init__(
        self,
        *,
        subject: str,
        runtime_id: str,
        audiences: tuple[str, ...],
        scopes: tuple[str, ...],
    ) -> None:
        self._subject = subject
        self._runtime_id = runtime_id
        self._audiences = audiences
        self._scopes = scopes

    def auth_flow(self, request: httpx.Request):
        token = mint_whatsapp_internal_token(
            subject=self._subject,
            runtime_id=self._runtime_id,
            audiences=self._audiences,
            scopes=self._scopes,
        )
        request.headers["Authorization"] = f"Bearer {token}"
        yield request


class LazyWhatsAppMCPServer(MCPServer):
    """Lazy MCP server that creates a per-run WhatsApp MCP client."""

    def __init__(
        self,
        *,
        session_provider: WhatsAppSessionProvider,
        default_mcp_url: str,
        mcp_audience: str,
        bridge_audience: str,
        jwt_subject: str,
        jwt_scopes: str,
        name: str = "whatsapp",
        mcp_timeout: float = 120,
        mcp_sse_read_timeout: float = 600,
        client_session_timeout_seconds: float | None = 120,
        max_retry_attempts: int = 2,
    ) -> None:
        super().__init__(use_structured_content=False)
        self._session_provider = session_provider
        self._default_mcp_url = default_mcp_url.strip()
        self._mcp_audience = mcp_audience.strip()
        self._bridge_audience = bridge_audience.strip()
        self._jwt_subject = jwt_subject.strip()
        self._jwt_scopes = jwt_scopes

        self._name = name
        self._mcp_timeout = mcp_timeout
        self._mcp_sse_read_timeout = mcp_sse_read_timeout
        self._client_session_timeout_seconds = client_session_timeout_seconds
        self._max_retry_attempts = max_retry_attempts

        self._server: MCPServerStreamableHttp | None = None
        self._connect_lock = asyncio.Lock()

    @property
    def name(self) -> str:
        return self._name

    async def connect(self):
        # No-op: connect lazily on first list_tools() with run_context.
        return

    def _subject_for_user(self, user_id: str) -> str:
        if not self._jwt_subject:
            return user_id
        return f"{self._jwt_subject}:{user_id}"

    def _build_httpx_client_factory(
        self,
        *,
        token_subject: str,
        runtime_id: str,
    ):
        audiences = _normalize_claim_values(
            [self._mcp_audience, self._bridge_audience],
            claim_name="whatsapp MCP audiences",
        )
        scopes = _normalize_claim_values(self._jwt_scopes, claim_name="whatsapp MCP scopes")

        jwt_auth = _WhatsAppInternalJWTAuth(
            subject=token_subject,
            runtime_id=runtime_id,
            audiences=audiences,
            scopes=scopes,
        )

        def _factory(
            headers: dict[str, str] | None = None,
            timeout: httpx.Timeout | None = None,
            auth: httpx.Auth | None = None,
        ) -> httpx.AsyncClient:
            _ = auth
            return httpx.AsyncClient(
                follow_redirects=True,
                headers=headers,
                timeout=timeout if timeout is not None else httpx.Timeout(30.0, read=300.0),
                auth=jwt_auth,
            )

        return _factory

    async def _ensure_connected(self, run_context: RunContextWrapper[Any]) -> MCPServerStreamableHttp:
        if self._server is not None:
            return self._server

        async with self._connect_lock:
            if self._server is not None:
                return self._server

            ctx = run_context.context
            user_id = getattr(ctx, "user_id", None)
            user_jwt = getattr(ctx, "user_jwt", None)
            if not user_id:
                raise RuntimeError("Missing user_id in run_context for WhatsApp MCP provisioning")
            if not user_jwt:
                raise RuntimeError("Missing user_jwt in run_context for WhatsApp MCP provisioning")

            lease = await self._session_provider.get_or_create(user_id=user_id, user_jwt=user_jwt)
            mcp_url = (lease.mcp_url or self._default_mcp_url).strip()
            if not mcp_url:
                raise RuntimeError("Missing WhatsApp MCP URL for runtime lease")
            runtime_id = (lease.runtime_id or "").strip()
            if not runtime_id:
                raise RuntimeError("Missing runtime_id for WhatsApp runtime lease")

            httpx_client_factory = self._build_httpx_client_factory(
                token_subject=self._subject_for_user(user_id=user_id),
                runtime_id=runtime_id,
            )
            server = MCPServerStreamableHttp(
                name=self._name,
                params={
                    "url": mcp_url,
                    "timeout": self._mcp_timeout,
                    "sse_read_timeout": self._mcp_sse_read_timeout,
                    "httpx_client_factory": httpx_client_factory,
                },
                cache_tools_list=True,
                client_session_timeout_seconds=self._client_session_timeout_seconds,
                max_retry_attempts=self._max_retry_attempts,
            )
            await server.connect()
            self._server = server
            return server

    async def cleanup(self):
        server = self._server
        self._server = None
        if server is not None:
            await server.cleanup()

    async def list_tools(
        self,
        run_context: RunContextWrapper[Any] | None = None,
        agent: AgentBase | None = None,
    ) -> list[MCPTool]:
        if run_context is None:
            raise RuntimeError("run_context is required for lazy WhatsApp MCP provisioning")
        server = await self._ensure_connected(run_context)
        return await server.list_tools(run_context, agent)

    async def call_tool(self, tool_name: str, arguments: dict[str, Any] | None) -> CallToolResult:
        if self._server is None:
            raise RuntimeError(
                "WhatsApp MCP server not connected yet. Tool invocation requires a prior list_tools() call."
            )
        return await self._server.call_tool(tool_name, arguments)

    async def list_prompts(self) -> ListPromptsResult:
        if self._server is None:
            raise RuntimeError("WhatsApp MCP server not connected yet.")
        return await self._server.list_prompts()

    async def get_prompt(self, name: str, arguments: dict[str, Any] | None = None) -> GetPromptResult:
        if self._server is None:
            raise RuntimeError("WhatsApp MCP server not connected yet.")
        return await self._server.get_prompt(name, arguments)
