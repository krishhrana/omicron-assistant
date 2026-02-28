from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


RuntimeState = Literal[
    "provisioning",
    "starting",
    "ready",
    "degraded",
    "stopping",
    "stopped",
    "error",
]


class LeaseRuntimeRequest(BaseModel):
    user_id: str
    ttl_seconds: int = Field(default=600, gt=0)
    wait_for_ready_seconds: int = Field(default=15, ge=0)
    force_new: bool = False
    client_request_id: str | None = None


class LeaseRuntimeResponse(BaseModel):
    runtime_id: str
    generation: int
    state: RuntimeState
    bridge_base_url: str
    mcp_url: str
    runtime_started_at: str
    hard_expires_at: str
    lease_expires_at: str
    poll_after_seconds: int = 2
    action: Literal["created", "reused", "rotated"]


class RuntimeStatusResponse(BaseModel):
    runtime_id: str
    generation: int
    state: RuntimeState
    bridge_base_url: str
    mcp_url: str
    runtime_started_at: str
    hard_expires_at: str
    lease_expires_at: str
    last_error: str | None = None


class TouchRuntimeRequest(BaseModel):
    user_id: str
    ttl_seconds: int = Field(default=600, gt=0)


class TouchRuntimeResponse(BaseModel):
    ok: bool
    runtime_id: str
    hard_expires_at: str
    lease_expires_at: str


class DisconnectRuntimeRequest(BaseModel):
    user_id: str
    stop_reason: str = "user_disconnect"


class DisconnectRuntimeResponse(BaseModel):
    ok: bool
    runtime_id: str
    state: RuntimeState

