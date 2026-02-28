from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


OAuthTransactionStatus = Literal["pending", "connected", "error", "expired"]


class OAuthStartResponse(BaseModel):
    provider: str
    url: str
    transaction_id: str
    status: OAuthTransactionStatus = "pending"
    expires_at: str


class OAuthStatusResponse(BaseModel):
    provider: str
    transaction_id: str
    status: OAuthTransactionStatus
    connected: bool
    detail: str | None = None
    updated_at: str
