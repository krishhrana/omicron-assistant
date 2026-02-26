from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class WhatsAppRuntimeLease:
    runtime_id: str
    bridge_base_url: str
    mcp_url: str | None = None


class WhatsAppSessionProvider(Protocol):
    async def get_or_create(
        self,
        *,
        user_id: str,
        user_jwt: str,
    ) -> WhatsAppRuntimeLease: ...

    async def disconnect(
        self,
        *,
        user_id: str,
        runtime_id: str | None = None,
    ) -> None: ...
