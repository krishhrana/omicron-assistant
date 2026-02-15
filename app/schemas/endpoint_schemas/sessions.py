from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class ChatSessionUpsertPayload(BaseModel):
    conversation_id: str
    title: str | None = None
    metadata: dict | None = None
    last_message_at: str | None = None
    status: Literal["active", "archived", "deleted"] | None = None
