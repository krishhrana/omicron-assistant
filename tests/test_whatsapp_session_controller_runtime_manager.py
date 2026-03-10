from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from whatsapp_session_controller.core.settings import WhatsAppSessionControllerSettings
from whatsapp_session_controller.orchestration.base import OrchestratedRuntime
from whatsapp_session_controller.services.runtime_manager import RuntimeManager
from whatsapp_session_controller.services.runtime_types import RuntimeRecord


class _FakeRuntimeLeaseRepository:
    def __init__(self, initial: RuntimeRecord | None = None) -> None:
        self._by_user: dict[str, RuntimeRecord] = {}
        if initial is not None:
            self._by_user[initial.user_id] = initial
        self.touch_calls: list[dict[str, object]] = []
        self.replace_calls: list[dict[str, object]] = []
        self.transition_calls: list[dict[str, object]] = []

    async def get_by_user(self, *, user_id: str) -> RuntimeRecord | None:
        return self._by_user.get(user_id)

    async def get_by_user_runtime(self, *, user_id: str, runtime_id: str) -> RuntimeRecord | None:
        record = self._by_user.get(user_id)
        if record is None or record.runtime_id != runtime_id:
            return None
        return record

    async def replace_runtime(
        self,
        *,
        current: RuntimeRecord | None,
        next_record: RuntimeRecord,
        desired_state: str = "warm",
    ) -> RuntimeRecord | None:
        self.replace_calls.append(
            {"current": current, "next_record": next_record, "desired_state": desired_state}
        )
        stored = self._by_user.get(next_record.user_id)
        if current is None:
            if stored is not None:
                return None
        else:
            if stored is None:
                return None
            if stored.runtime_id != current.runtime_id or stored.generation != current.generation:
                return None
        self._by_user[next_record.user_id] = next_record
        return next_record

    async def touch_runtime(
        self,
        *,
        user_id: str,
        runtime_id: str,
        expected_generation: int,
        lease_expires_at: datetime,
        state: str,
        bridge_base_url: str | None = None,
        mcp_url: str | None = None,
        desired_state: str = "warm",
        last_error_code: str | None = None,
        last_error_at: datetime | None = None,
    ) -> RuntimeRecord | None:
        self.touch_calls.append(
            {
                "user_id": user_id,
                "runtime_id": runtime_id,
                "expected_generation": expected_generation,
                "lease_expires_at": lease_expires_at,
                "state": state,
                "bridge_base_url": bridge_base_url,
                "mcp_url": mcp_url,
                "desired_state": desired_state,
                "last_error_code": last_error_code,
                "last_error_at": last_error_at,
            }
        )
        stored = self._by_user.get(user_id)
        if stored is None:
            return None
        if stored.runtime_id != runtime_id or stored.generation != expected_generation:
            return None
        updated = replace(
            stored,
            lease_expires_at=lease_expires_at,
            state=state,
            bridge_base_url=bridge_base_url or stored.bridge_base_url,
            mcp_url=mcp_url or stored.mcp_url,
            last_error=last_error_code,
        )
        self._by_user[user_id] = updated
        return updated

    async def transition_state(
        self,
        *,
        user_id: str,
        runtime_id: str,
        expected_generation: int,
        state: str,
        desired_state: str | None = None,
        lease_expires_at: datetime | None = None,
        last_error_code: str | None = None,
        last_error_at: datetime | None = None,
    ) -> RuntimeRecord | None:
        self.transition_calls.append(
            {
                "user_id": user_id,
                "runtime_id": runtime_id,
                "expected_generation": expected_generation,
                "state": state,
                "desired_state": desired_state,
                "lease_expires_at": lease_expires_at,
                "last_error_code": last_error_code,
                "last_error_at": last_error_at,
            }
        )
        stored = self._by_user.get(user_id)
        if stored is None:
            return None
        if stored.runtime_id != runtime_id or stored.generation != expected_generation:
            return None
        updated = replace(
            stored,
            state=state,
            lease_expires_at=lease_expires_at or stored.lease_expires_at,
            last_error=last_error_code,
        )
        self._by_user[user_id] = updated
        return updated


class _FakeRuntimeOrchestrator:
    def __init__(self, *, health_state: str = "ready") -> None:
        self.health_state = health_state
        self.get_or_create_calls: list[dict[str, object]] = []
        self.disconnect_calls: list[dict[str, object]] = []
        self.probe_calls: list[dict[str, object]] = []

    async def get_or_create_runtime(
        self,
        *,
        user_id: str,
        runtime_id: str,
        generation: int,
    ) -> OrchestratedRuntime:
        self.get_or_create_calls.append(
            {"user_id": user_id, "runtime_id": runtime_id, "generation": generation}
        )
        return OrchestratedRuntime(
            runtime_id=runtime_id,
            bridge_base_url=f"https://bridge.example/{runtime_id}",
            mcp_url=f"https://mcp.example/{runtime_id}",
            task_arn=f"arn:aws:ecs:region:acct:task/{runtime_id}",
        )

    async def disconnect_runtime(
        self,
        *,
        user_id: str,
        runtime_id: str,
        generation: int,
    ) -> None:
        self.disconnect_calls.append(
            {"user_id": user_id, "runtime_id": runtime_id, "generation": generation}
        )

    async def probe_runtime(
        self,
        *,
        runtime: OrchestratedRuntime,
    ) -> str:
        self.probe_calls.append({"runtime_id": runtime.runtime_id})
        return self.health_state


def _settings() -> WhatsAppSessionControllerSettings:
    return WhatsAppSessionControllerSettings(
        _env_file=None,
        WHATSAPP_SESSION_CONTROLLER_JWT_SECRET="controller-secret",
        SUPABASE_URL="https://example.supabase.co",
        SUPABASE_SERVICE_ROLE_KEY="service-role-key",
        WHATSAPP_RUNTIME_ORCHESTRATOR="local",
        WHATSAPP_RUNTIME_SLIDING_TTL_SECONDS=600,
        WHATSAPP_RUNTIME_MAX_LIFETIME_SECONDS=5400,
    )


def test_lease_reuses_existing_runtime_and_clamps_ttl(monkeypatch) -> None:
    now = datetime(2026, 2, 28, 6, 0, 0, tzinfo=timezone.utc)
    initial = RuntimeRecord(
        user_id="user-1",
        runtime_id="wa_rt_existing",
        generation=3,
        state="ready",
        bridge_base_url="https://bridge.example/wa_rt_existing",
        mcp_url="https://mcp.example/wa_rt_existing",
        runtime_started_at=now - timedelta(minutes=5),
        hard_expires_at=now + timedelta(minutes=1),
        lease_expires_at=now + timedelta(seconds=30),
        last_error=None,
    )
    repository = _FakeRuntimeLeaseRepository(initial=initial)
    orchestrator = _FakeRuntimeOrchestrator(health_state="ready")
    manager = RuntimeManager(settings=_settings(), repository=repository, orchestrator=orchestrator)
    monkeypatch.setattr(manager, "_utc_now", lambda: now)

    lease, action = asyncio.run(
        manager.lease(user_id="user-1", ttl_seconds=600, force_new=False)
    )

    assert action == "reused"
    assert lease.runtime_id == "wa_rt_existing"
    assert lease.generation == 3
    assert lease.lease_expires_at == initial.hard_expires_at
    assert repository.replace_calls == []
    assert len(repository.touch_calls) == 1
    assert repository.touch_calls[0]["expected_generation"] == 3
    assert repository.touch_calls[0]["bridge_base_url"] == "https://bridge.example/wa_rt_existing"
    assert repository.touch_calls[0]["mcp_url"] == "https://mcp.example/wa_rt_existing"


def test_lease_force_new_rotates_generation() -> None:
    now = datetime(2026, 2, 28, 6, 0, 0, tzinfo=timezone.utc)
    initial = RuntimeRecord(
        user_id="user-1",
        runtime_id="wa_rt_existing",
        generation=3,
        state="ready",
        bridge_base_url="https://bridge.example/wa_rt_existing",
        mcp_url="https://mcp.example/wa_rt_existing",
        runtime_started_at=now - timedelta(minutes=10),
        hard_expires_at=now + timedelta(minutes=50),
        lease_expires_at=now + timedelta(minutes=5),
        last_error=None,
    )
    repository = _FakeRuntimeLeaseRepository(initial=initial)
    orchestrator = _FakeRuntimeOrchestrator(health_state="ready")
    manager = RuntimeManager(settings=_settings(), repository=repository, orchestrator=orchestrator)

    lease, action = asyncio.run(
        manager.lease(user_id="user-1", ttl_seconds=120, force_new=True)
    )

    assert action == "rotated"
    assert lease.generation == 4
    assert lease.runtime_id != "wa_rt_existing"
    assert len(repository.replace_calls) == 1
    assert repository.replace_calls[0]["current"] == initial
    assert lease.bridge_base_url.startswith("https://bridge.example/")
    assert lease.mcp_url.startswith("https://mcp.example/")


def test_touch_marks_hard_expired_runtime_stopped() -> None:
    now = datetime(2026, 2, 28, 6, 0, 0, tzinfo=timezone.utc)
    initial = RuntimeRecord(
        user_id="user-1",
        runtime_id="wa_rt_existing",
        generation=2,
        state="ready",
        bridge_base_url="https://bridge.example/wa_rt_existing",
        mcp_url="https://mcp.example/wa_rt_existing",
        runtime_started_at=now - timedelta(minutes=91),
        hard_expires_at=now - timedelta(seconds=1),
        lease_expires_at=now + timedelta(seconds=30),
        last_error=None,
    )
    repository = _FakeRuntimeLeaseRepository(initial=initial)
    orchestrator = _FakeRuntimeOrchestrator(health_state="ready")
    manager = RuntimeManager(settings=_settings(), repository=repository, orchestrator=orchestrator)
    manager._utc_now = lambda: now  # type: ignore[method-assign]

    touched = asyncio.run(manager.touch(user_id="user-1", runtime_id="wa_rt_existing", ttl_seconds=120))

    assert touched is None
    assert len(repository.transition_calls) == 1
    transition = repository.transition_calls[0]
    assert transition["state"] == "stopped"
    assert transition["last_error_code"] == "runtime_hard_expired"


def test_disconnect_stops_runtime_via_orchestrator() -> None:
    now = datetime(2026, 2, 28, 6, 0, 0, tzinfo=timezone.utc)
    initial = RuntimeRecord(
        user_id="user-1",
        runtime_id="wa_rt_existing",
        generation=5,
        state="ready",
        bridge_base_url="https://bridge.example/wa_rt_existing",
        mcp_url="https://mcp.example/wa_rt_existing",
        runtime_started_at=now - timedelta(minutes=10),
        hard_expires_at=now + timedelta(minutes=60),
        lease_expires_at=now + timedelta(minutes=5),
        last_error=None,
    )
    repository = _FakeRuntimeLeaseRepository(initial=initial)
    orchestrator = _FakeRuntimeOrchestrator(health_state="ready")
    manager = RuntimeManager(settings=_settings(), repository=repository, orchestrator=orchestrator)
    manager._utc_now = lambda: now  # type: ignore[method-assign]

    disconnected = asyncio.run(manager.disconnect(user_id="user-1", runtime_id="wa_rt_existing"))

    assert disconnected is not None
    assert disconnected.state == "stopped"
    assert len(orchestrator.disconnect_calls) == 1
    assert orchestrator.disconnect_calls[0]["runtime_id"] == "wa_rt_existing"
