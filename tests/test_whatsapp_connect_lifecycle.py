import asyncio
from collections.abc import Iterator

from app.api.v1.endpoints import whatsapp_connect as routes
from app.auth import AuthContext
from app.whatsapp_sessions.base import WhatsAppRuntimeLease


class _FakeSessionProvider:
    def __init__(self) -> None:
        self._lease = WhatsAppRuntimeLease(
            runtime_id="wa_rt_test",
            bridge_base_url="https://bridge.test",
            mcp_url="https://mcp.test",
        )
        self.get_or_create_calls: list[tuple[str, str]] = []
        self.read_current_calls: list[tuple[str, str]] = []
        self.touch_calls: list[tuple[str, str, str | None]] = []
        self.disconnect_calls: list[tuple[str, str, str | None]] = []

    async def get_or_create(self, *, user_id: str, user_jwt: str) -> WhatsAppRuntimeLease:
        self.get_or_create_calls.append((user_id, user_jwt))
        return self._lease

    async def read_current(
        self,
        *,
        user_id: str,
        user_jwt: str,
    ) -> WhatsAppRuntimeLease | None:
        self.read_current_calls.append((user_id, user_jwt))
        return self._lease

    async def touch(
        self,
        *,
        user_id: str,
        user_jwt: str,
        runtime_id: str | None = None,
    ) -> None:
        self.touch_calls.append((user_id, user_jwt, runtime_id))

    async def disconnect(
        self,
        *,
        user_id: str,
        user_jwt: str,
        runtime_id: str | None = None,
    ) -> None:
        self.disconnect_calls.append((user_id, user_jwt, runtime_id))


def _status_payloads() -> Iterator[dict]:
    yield {
        "state": "awaiting_qr",
        "connected": False,
        "message": "Scan QR",
        "qr_code": "qr-123",
        "qr_image_data_url": "data:image/png;base64,AAA",
        "updated_at": "2026-02-28T00:00:00Z",
    }
    yield {
        "state": "connected",
        "connected": True,
        "message": "Connected",
        "updated_at": "2026-02-28T00:00:10Z",
    }


def test_whatsapp_connect_start_status_disconnect_lifecycle(
    monkeypatch,
) -> None:
    provider = _FakeSessionProvider()
    status_payload_iter = _status_payloads()

    async def _fake_request_bridge_connect(
        lease: WhatsAppRuntimeLease,
        *,
        auth_headers: dict[str, str],
    ) -> None:
        assert lease.runtime_id == "wa_rt_test"
        assert auth_headers["Authorization"].startswith("Bearer ")

    async def _fake_fetch_bridge_status(
        lease: WhatsAppRuntimeLease,
        *,
        auth_headers: dict[str, str],
    ) -> dict:
        assert lease.runtime_id == "wa_rt_test"
        assert auth_headers["Authorization"].startswith("Bearer ")
        return next(status_payload_iter)

    async def _fake_request_bridge_revoke_disconnect(
        lease: WhatsAppRuntimeLease,
        *,
        auth_headers: dict[str, str],
    ) -> None:
        assert lease.runtime_id == "wa_rt_test"
        assert auth_headers["Authorization"].startswith("Bearer ")

    async def _fake_get_whatsapp_connection(*, user_id: str, user_jwt: str):
        assert user_id == "user-1"
        assert user_jwt == "token-1"
        return {
            "connected_at": "2026-02-27T23:59:00Z",
            "disconnected_at": None,
        }

    upsert_calls: list[dict] = []

    async def _fake_upsert_whatsapp_connection(**kwargs):
        upsert_calls.append(kwargs)
        return kwargs

    monkeypatch.setattr(routes, "get_whatsapp_session_provider", lambda: provider)
    monkeypatch.setattr(
        routes,
        "mint_bridge_bearer_header",
        lambda **_: {"Authorization": "Bearer test"},
    )
    monkeypatch.setattr(routes, "_request_bridge_connect", _fake_request_bridge_connect)
    monkeypatch.setattr(routes, "_fetch_bridge_status", _fake_fetch_bridge_status)
    monkeypatch.setattr(
        routes,
        "_request_bridge_revoke_disconnect",
        _fake_request_bridge_revoke_disconnect,
    )
    monkeypatch.setattr(routes, "get_whatsapp_connection", _fake_get_whatsapp_connection)
    monkeypatch.setattr(routes, "upsert_whatsapp_connection", _fake_upsert_whatsapp_connection)

    auth_ctx = AuthContext(user_id="user-1", token="token-1")

    start_response = asyncio.run(routes.whatsapp_connect_start(auth_ctx=auth_ctx))
    assert start_response.status == "awaiting_qr"
    assert start_response.connected is False
    assert start_response.runtime_id == "wa_rt_test"

    status_response = asyncio.run(routes.whatsapp_connect_status(auth_ctx=auth_ctx))
    assert status_response.status == "connected"
    assert status_response.connected is True
    assert status_response.runtime_id == "wa_rt_test"

    disconnect_response = asyncio.run(routes.whatsapp_connect_disconnect(auth_ctx=auth_ctx))
    assert disconnect_response.ok is True
    assert disconnect_response.status == "disconnected"

    assert provider.get_or_create_calls == [
        ("user-1", "token-1"),
        ("user-1", "token-1"),
    ]
    assert provider.read_current_calls == [("user-1", "token-1")]
    assert provider.touch_calls == [
        ("user-1", "token-1", "wa_rt_test"),
        ("user-1", "token-1", "wa_rt_test"),
    ]
    assert provider.disconnect_calls == [("user-1", "token-1", "wa_rt_test")]

    assert [call["status"] for call in upsert_calls] == [
        "awaiting_qr",
        "connected",
        "disconnected",
    ]


def test_whatsapp_connect_status_without_runtime_reports_runtime_expired(
    monkeypatch,
) -> None:
    provider = _FakeSessionProvider()

    async def _fake_read_current(
        *,
        user_id: str,
        user_jwt: str,
    ) -> WhatsAppRuntimeLease | None:
        provider.read_current_calls.append((user_id, user_jwt))
        return None

    async def _fake_get_whatsapp_connection(*, user_id: str, user_jwt: str):
        assert user_id == "user-1"
        assert user_jwt == "token-1"
        return {
            "status": "connected",
            "connected_at": "2026-02-27T23:59:00Z",
            "last_error_code": None,
        }

    upsert_calls: list[dict] = []

    async def _fake_upsert_whatsapp_connection(**kwargs):
        upsert_calls.append(kwargs)
        return kwargs

    monkeypatch.setattr(routes, "get_whatsapp_session_provider", lambda: provider)
    monkeypatch.setattr(routes, "get_whatsapp_connection", _fake_get_whatsapp_connection)
    monkeypatch.setattr(routes, "upsert_whatsapp_connection", _fake_upsert_whatsapp_connection)
    monkeypatch.setattr(provider, "read_current", _fake_read_current)

    auth_ctx = AuthContext(user_id="user-1", token="token-1")
    status_response = asyncio.run(routes.whatsapp_connect_status(auth_ctx=auth_ctx))
    assert status_response.status == "disconnected"
    assert status_response.connected is False
    assert status_response.disconnect_reason == "runtime_expired"
    assert status_response.runtime_id is None
    assert provider.get_or_create_calls == []
    assert provider.read_current_calls == [("user-1", "token-1")]
    assert len(upsert_calls) == 1
    assert upsert_calls[0]["runtime_id"] is None
    assert upsert_calls[0]["last_error_code"] == "runtime_expired"
