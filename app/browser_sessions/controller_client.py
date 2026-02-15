from __future__ import annotations

import time
from dataclasses import dataclass

import httpx
import jwt

from app.core.settings import get_browser_session_controller_settings


@dataclass(frozen=True)
class BrowserSessionLease:
    session_id: str
    mcp_url: str
    expires_at: str | None = None
    status: str | None = None


class BrowserSessionControllerClient:
    def __init__(
        self,
        *,
        base_url: str,
        jwt_secret: str,
        jwt_audience: str = "browser-session-controller",
        timeout_seconds: float = 10.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._jwt_secret = jwt_secret
        self._jwt_audience = jwt_audience
        self._timeout_seconds = timeout_seconds

    def _make_auth_header(self) -> dict[str, str]:
        now = int(time.time())
        token = jwt.encode(
            {
                "sub": "omicron-api",
                "aud": self._jwt_audience,
                "iat": now,
                "exp": now + 60,
            },
            self._jwt_secret,
            algorithm="HS256",
        )
        return {"Authorization": f"Bearer {token}"}

    async def get_or_create(
        self,
        *,
        user_id: str,
        session_id: str,
        ttl_seconds: int | None = None,
    ) -> BrowserSessionLease:
        url = f"{self._base_url}/internal/browser-sessions/get-or-create"
        payload: dict = {"user_id": user_id, "session_id": session_id}
        if ttl_seconds is not None:
            payload["ttl_seconds"] = ttl_seconds
        async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
            resp = await client.post(url, json=payload, headers=self._make_auth_header())
            resp.raise_for_status()
            data = resp.json()
        return BrowserSessionLease(
            session_id=str(data.get("session_id") or session_id),
            mcp_url=str(data["mcp_url"]),
            expires_at=data.get("expires_at"),
            status=data.get("status"),
        )

    async def heartbeat(self, *, session_id: str, ttl_seconds: int | None = None) -> None:
        url = f"{self._base_url}/internal/browser-sessions/{session_id}/heartbeat"
        payload: dict = {}
        if ttl_seconds is not None:
            payload["ttl_seconds"] = ttl_seconds
        async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
            resp = await client.post(url, json=payload, headers=self._make_auth_header())
            if resp.status_code == 404:
                # Heartbeat is best-effort; the runner may not exist yet (lazy provisioning).
                return
            resp.raise_for_status()

    async def delete(self, *, session_id: str) -> None:
        url = f"{self._base_url}/internal/browser-sessions/{session_id}"
        async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
            resp = await client.delete(url, headers=self._make_auth_header())
            resp.raise_for_status()


def get_controller_client() -> BrowserSessionControllerClient | None:
    settings = get_browser_session_controller_settings()
    if not settings.url or not settings.jwt_secret:
        return None
    return BrowserSessionControllerClient(
        base_url=settings.url,
        jwt_secret=settings.jwt_secret,
        jwt_audience=settings.jwt_audience,
        timeout_seconds=settings.timeout_seconds,
    )

