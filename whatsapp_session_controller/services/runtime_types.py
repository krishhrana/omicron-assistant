from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal


RuntimeState = Literal[
    "provisioning",
    "starting",
    "ready",
    "degraded",
    "stopping",
    "stopped",
    "error",
]


@dataclass
class RuntimeRecord:
    user_id: str
    runtime_id: str
    generation: int
    state: RuntimeState
    bridge_base_url: str
    mcp_url: str
    runtime_started_at: datetime
    hard_expires_at: datetime
    lease_expires_at: datetime
    last_error: str | None = None
