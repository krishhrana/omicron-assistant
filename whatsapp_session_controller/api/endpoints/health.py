from __future__ import annotations

from pydantic import BaseModel
from fastapi import APIRouter


router = APIRouter()


class HealthResponse(BaseModel):
    ok: bool = True
    service: str = "whatsapp-session-controller"
    status: str = "healthy"


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse()

