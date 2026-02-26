from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class BrowserRuntimeLease:
    runtime_id: str
    mcp_url: str | None = None


class BrowserSessionProvider(Protocol):
    async def get_or_create(
        self,
        *,
        user_id: str,
        user_jwt: str,
        session_id: str,
    ) -> BrowserRuntimeLease: ...

    async def disconnect(
        self,
        *,
        user_id: str,
        session_id: str,
        runtime_id: str | None = None,
    ) -> None: ...
