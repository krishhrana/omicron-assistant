from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from agents import RunContextWrapper
from agents.mcp import MCPServer, MCPServerStreamableHttp
from mcp import Tool as MCPTool
from mcp.types import CallToolResult, GetPromptResult, ListPromptsResult

if TYPE_CHECKING:
    from agents.agent import AgentBase


class LazyBrowserSessionMCPServer(MCPServer):
    """Lazy MCP server that connects to a configured browser MCP endpoint on first tool listing."""

    def __init__(
        self,
        *,
        default_mcp_url: str,
        name: str = "playwright",
        mcp_timeout: float = 120,
        mcp_sse_read_timeout: float = 600,
        client_session_timeout_seconds: float | None = 120,
        max_retry_attempts: int = 2,
    ) -> None:
        super().__init__(use_structured_content=False)
        self._default_mcp_url = default_mcp_url.strip()
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
        # No-op: connect lazily on first list_tools() call.
        return

    async def _ensure_connected(self, run_context: RunContextWrapper[Any]) -> MCPServerStreamableHttp:
        if self._server is not None:
            return self._server

        async with self._connect_lock:
            if self._server is not None:
                return self._server

            _ = run_context
            mcp_url = self._default_mcp_url
            if not mcp_url:
                raise RuntimeError("Missing Browser MCP URL")
            params: dict[str, Any] = {
                "url": mcp_url,
                "timeout": self._mcp_timeout,
                "sse_read_timeout": self._mcp_sse_read_timeout,
            }
            server = MCPServerStreamableHttp(
                name=self._name,
                params=params,
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
            raise RuntimeError("run_context is required for lazy browser MCP provisioning")
        server = await self._ensure_connected(run_context)
        return await server.list_tools(run_context, agent)

    async def call_tool(self, tool_name: str, arguments: dict[str, Any] | None) -> CallToolResult:
        if self._server is None:
            raise RuntimeError(
                "Browser MCP server not connected yet. Tool invocation requires a prior list_tools() call."
            )
        return await self._server.call_tool(tool_name, arguments)

    async def list_prompts(self) -> ListPromptsResult:
        if self._server is None:
            raise RuntimeError("Browser MCP server not connected yet.")
        return await self._server.list_prompts()

    async def get_prompt(self, name: str, arguments: dict[str, Any] | None = None) -> GetPromptResult:
        if self._server is None:
            raise RuntimeError("Browser MCP server not connected yet.")
        return await self._server.get_prompt(name, arguments)
