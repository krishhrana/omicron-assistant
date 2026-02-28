import asyncio
from types import SimpleNamespace

import pytest

from app.whatsapp_sessions import controller_provider as provider_module
from app.whatsapp_sessions.base import WhatsAppRuntimeLease


class _StubResponse:
    def __init__(self, status_code: int, payload: dict | list | str | None) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


class _StubAsyncClient:
    def __init__(self, response: _StubResponse) -> None:
        self._response = response

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        _ = exc_type
        _ = exc
        _ = tb
        return None

    async def post(self, *args, **kwargs):
        _ = args
        _ = kwargs
        return self._response

    async def get(self, *args, **kwargs):
        _ = args
        _ = kwargs
        return self._response


def _async_client_factory(response: _StubResponse):
    class _FactoryClient:
        def __init__(self, *args, **kwargs) -> None:
            _ = args
            _ = kwargs
            self._client = _StubAsyncClient(response)

        async def __aenter__(self):
            return await self._client.__aenter__()

        async def __aexit__(self, exc_type, exc, tb) -> None:
            return await self._client.__aexit__(exc_type, exc, tb)

        async def post(self, *args, **kwargs):
            return await self._client.post(*args, **kwargs)

        async def get(self, *args, **kwargs):
            return await self._client.get(*args, **kwargs)

    return _FactoryClient


def _provider() -> provider_module.ControllerWhatsAppSessionProvider:
    settings = SimpleNamespace(
        controller_url="https://controller.internal",
        controller_timeout_seconds=5.0,
    )
    return provider_module.ControllerWhatsAppSessionProvider(settings=settings)


def test_request_controller_lease_maps_429_to_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _provider()
    monkeypatch.setattr(
        provider_module,
        "mint_controller_lease_bearer_header",
        lambda **_: {"Authorization": "Bearer test"},
    )
    monkeypatch.setattr(
        provider_module.httpx,
        "AsyncClient",
        _async_client_factory(_StubResponse(429, {"detail": "controller busy"})),
    )

    with pytest.raises(provider_module.ControllerLeaseUnavailableError, match="controller busy"):
        asyncio.run(provider._request_controller_lease(user_id="user-1"))


def test_request_controller_lease_maps_401_to_response_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _provider()
    monkeypatch.setattr(
        provider_module,
        "mint_controller_lease_bearer_header",
        lambda **_: {"Authorization": "Bearer test"},
    )
    monkeypatch.setattr(
        provider_module.httpx,
        "AsyncClient",
        _async_client_factory(_StubResponse(401, {"detail": "unauthorized"})),
    )

    with pytest.raises(provider_module.ControllerLeaseResponseError, match="unauthorized"):
        asyncio.run(provider._request_controller_lease(user_id="user-1"))


def test_get_or_create_returns_controller_lease(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _provider()
    lease = WhatsAppRuntimeLease(
        runtime_id="wa_rt_fresh",
        bridge_base_url="https://bridge.fresh",
        mcp_url="https://mcp.fresh",
    )

    async def _fake_request_lease(*, user_id: str):
        assert user_id == "user-1"
        return lease

    monkeypatch.setattr(provider, "_request_controller_lease", _fake_request_lease)

    result = asyncio.run(provider.get_or_create(user_id="user-1", user_jwt="token-1"))
    assert result == lease


def test_get_or_create_propagates_unavailable_as_runtime_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _provider()

    async def _fake_request_lease(*, user_id: str):
        _ = user_id
        raise provider_module.ControllerLeaseUnavailableError("controller unavailable")

    monkeypatch.setattr(provider, "_request_controller_lease", _fake_request_lease)

    with pytest.raises(RuntimeError, match="controller unavailable"):
        asyncio.run(provider.get_or_create(user_id="user-1", user_jwt="token-1"))


def test_get_or_create_propagates_not_ready_as_runtime_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _provider()

    async def _fake_request_lease(*, user_id: str):
        _ = user_id
        raise provider_module.ControllerLeaseNotReadyError("runtime warming")

    monkeypatch.setattr(provider, "_request_controller_lease", _fake_request_lease)

    with pytest.raises(RuntimeError, match="runtime warming"):
        asyncio.run(provider.get_or_create(user_id="user-1", user_jwt="token-1"))


def test_disconnect_404_is_noop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _provider()
    monkeypatch.setattr(
        provider_module,
        "mint_controller_disconnect_bearer_header",
        lambda **_: {"Authorization": "Bearer test"},
    )
    monkeypatch.setattr(
        provider_module.httpx,
        "AsyncClient",
        _async_client_factory(_StubResponse(404, {"detail": "not found"})),
    )

    asyncio.run(provider.disconnect(user_id="user-1", user_jwt="token-1", runtime_id="wa_rt_1"))


def test_disconnect_500_raises_runtime_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _provider()
    monkeypatch.setattr(
        provider_module,
        "mint_controller_disconnect_bearer_header",
        lambda **_: {"Authorization": "Bearer test"},
    )
    monkeypatch.setattr(
        provider_module.httpx,
        "AsyncClient",
        _async_client_factory(_StubResponse(500, {"detail": "controller error"})),
    )

    with pytest.raises(RuntimeError, match="controller error"):
        asyncio.run(provider.disconnect(user_id="user-1", user_jwt="token-1", runtime_id="wa_rt_1"))


def test_touch_404_is_noop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _provider()
    monkeypatch.setattr(
        provider_module,
        "mint_controller_touch_bearer_header",
        lambda **_: {"Authorization": "Bearer test"},
    )
    monkeypatch.setattr(
        provider_module.httpx,
        "AsyncClient",
        _async_client_factory(_StubResponse(404, {"detail": "not found"})),
    )

    asyncio.run(provider.touch(user_id="user-1", user_jwt="token-1", runtime_id="wa_rt_1"))


def test_touch_500_raises_runtime_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _provider()
    monkeypatch.setattr(
        provider_module,
        "mint_controller_touch_bearer_header",
        lambda **_: {"Authorization": "Bearer test"},
    )
    monkeypatch.setattr(
        provider_module.httpx,
        "AsyncClient",
        _async_client_factory(_StubResponse(500, {"detail": "controller error"})),
    )

    with pytest.raises(RuntimeError, match="controller error"):
        asyncio.run(provider.touch(user_id="user-1", user_jwt="token-1", runtime_id="wa_rt_1"))


def test_read_current_404_returns_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _provider()
    monkeypatch.setattr(
        provider_module,
        "mint_controller_read_current_bearer_header",
        lambda **_: {"Authorization": "Bearer test"},
    )
    monkeypatch.setattr(
        provider_module.httpx,
        "AsyncClient",
        _async_client_factory(_StubResponse(404, {"detail": "not found"})),
    )

    result = asyncio.run(provider.read_current(user_id="user-1", user_jwt="token-1"))
    assert result is None


def test_read_current_200_returns_lease(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _provider()
    monkeypatch.setattr(
        provider_module,
        "mint_controller_read_current_bearer_header",
        lambda **_: {"Authorization": "Bearer test"},
    )
    monkeypatch.setattr(
        provider_module.httpx,
        "AsyncClient",
        _async_client_factory(
            _StubResponse(
                200,
                {
                    "runtime_id": "wa_rt_1",
                    "bridge_base_url": "https://bridge.rt",
                    "mcp_url": "https://mcp.rt/mcp",
                    "state": "ready",
                },
            )
        ),
    )

    result = asyncio.run(provider.read_current(user_id="user-1", user_jwt="token-1"))
    assert isinstance(result, WhatsAppRuntimeLease)
    assert result.runtime_id == "wa_rt_1"
