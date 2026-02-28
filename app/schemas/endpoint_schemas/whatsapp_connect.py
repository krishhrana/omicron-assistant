from __future__ import annotations

from pydantic import BaseModel


class WhatsAppConnectStatusResponse(BaseModel):
    provider: str = "whatsapp"
    runtime_id: str | None = None
    status: str
    connected: bool
    reauth_required: bool
    disconnect_reason: str | None = None
    message: str | None = None
    qr_code: str | None = None
    qr_image_data_url: str | None = None
    sync_progress: int | None = None
    sync_current: int | None = None
    sync_total: int | None = None
    updated_at: str | None = None
    poll_after_seconds: int = 2


class WhatsAppDisconnectResponse(BaseModel):
    ok: bool
    provider: str = "whatsapp"
    status: str


class WhatsAppPrewarmResponse(BaseModel):
    ok: bool
    provider: str = "whatsapp"
    prewarmed: bool
    reason: str | None = None
    runtime_id: str | None = None
