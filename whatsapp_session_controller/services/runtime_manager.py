from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import logging
from typing import Literal
from uuid import uuid4

from whatsapp_session_controller.core.settings import (
    WhatsAppSessionControllerSettings,
    get_controller_settings,
)
from whatsapp_session_controller.orchestration import get_runtime_orchestrator
from whatsapp_session_controller.orchestration.base import RuntimeOrchestrator
from whatsapp_session_controller.services.runtime_lease_repository import RuntimeLeaseRepository
from whatsapp_session_controller.services.runtime_types import RuntimeRecord, RuntimeState

logger = logging.getLogger(__name__)


class RuntimeManager:
    """Durable runtime lease manager backed by controller-owned DB state."""

    MAX_LEASE_ATTEMPTS = 3

    def __init__(
        self,
        settings: WhatsAppSessionControllerSettings,
        repository: RuntimeLeaseRepository,
        orchestrator: RuntimeOrchestrator,
    ) -> None:
        self._settings = settings
        self._repository = repository
        self._orchestrator = orchestrator
        self._lock_registry_guard = asyncio.Lock()
        self._locks_by_user: dict[str, asyncio.Lock] = {}

    @staticmethod
    def _utc_now() -> datetime:
        return datetime.now(timezone.utc)

    @staticmethod
    def _to_iso(value: datetime) -> str:
        return value.isoformat()

    @staticmethod
    def _new_runtime_id() -> str:
        return f"wa_rt_{uuid4().hex}"

    @staticmethod
    def _safe_user_label(user_id: str) -> str:
        normalized = user_id.strip()
        if not normalized:
            return "unknown"
        if len(normalized) <= 6:
            return normalized
        return f"{normalized[:3]}...{normalized[-2:]}"

    def _bounded_ttl_seconds(self, ttl_seconds: int) -> int:
        max_sliding_ttl = max(1, int(self._settings.runtime_sliding_ttl_seconds))
        return max(1, min(int(ttl_seconds), max_sliding_ttl))

    async def _user_lock(self, user_id: str) -> asyncio.Lock:
        async with self._lock_registry_guard:
            lock = self._locks_by_user.get(user_id)
            if lock is None:
                lock = asyncio.Lock()
                self._locks_by_user[user_id] = lock
            return lock

    def _is_reusable(self, record: RuntimeRecord, now: datetime) -> bool:
        if record.state not in {"ready", "degraded"}:
            return False
        return now < record.hard_expires_at

    def _clamp_lease_expiry(self, *, now: datetime, ttl_seconds: int, hard_expires_at: datetime) -> datetime:
        requested = now + timedelta(seconds=ttl_seconds)
        return min(requested, hard_expires_at)

    def _to_status_dict(self, record: RuntimeRecord) -> dict[str, str | int | None]:
        return {
            "runtime_id": record.runtime_id,
            "generation": record.generation,
            "state": record.state,
            "bridge_base_url": record.bridge_base_url,
            "mcp_url": record.mcp_url,
            "runtime_started_at": self._to_iso(record.runtime_started_at),
            "hard_expires_at": self._to_iso(record.hard_expires_at),
            "lease_expires_at": self._to_iso(record.lease_expires_at),
            "last_error": record.last_error,
        }

    async def _ensure_runtime(
        self,
        *,
        user_id: str,
        runtime_id: str,
        generation: int,
        wait_for_ready_seconds: int = 0,
    ) -> tuple[str, str, RuntimeState]:
        user_label = self._safe_user_label(user_id)
        logger.info(
            "whatsapp.runtime.ensure.begin user=%s runtime_id=%s generation=%s wait_for_ready_seconds=%s",
            user_label,
            runtime_id,
            generation,
            wait_for_ready_seconds,
        )
        orchestrated = await self._orchestrator.get_or_create_runtime(
            user_id=user_id,
            runtime_id=runtime_id,
            generation=generation,
        )
        logger.info(
            "whatsapp.runtime.ensure.orchestrated user=%s runtime_id=%s task_arn=%s bridge_base_url=%s mcp_url=%s",
            user_label,
            runtime_id,
            orchestrated.task_arn,
            orchestrated.bridge_base_url,
            orchestrated.mcp_url,
        )
        probe_state = await self._orchestrator.probe_runtime(runtime=orchestrated)
        logger.info(
            "whatsapp.runtime.ensure.probe_initial user=%s runtime_id=%s probe_state=%s",
            user_label,
            runtime_id,
            probe_state,
        )
        wait_budget_seconds = max(0, int(wait_for_ready_seconds))
        if wait_budget_seconds > 0 and probe_state != "ready":
            deadline = self._utc_now() + timedelta(seconds=wait_budget_seconds)
            logger.info(
                "whatsapp.runtime.ensure.waiting user=%s runtime_id=%s wait_budget_seconds=%s initial_probe_state=%s",
                user_label,
                runtime_id,
                wait_budget_seconds,
                probe_state,
            )
            while probe_state != "ready" and self._utc_now() < deadline:
                await asyncio.sleep(1)
                probe_state = await self._orchestrator.probe_runtime(runtime=orchestrated)
        normalized_probe_state: RuntimeState = probe_state if probe_state in {"ready", "degraded"} else "degraded"
        logger.info(
            "whatsapp.runtime.ensure.complete user=%s runtime_id=%s runtime_state=%s",
            user_label,
            runtime_id,
            normalized_probe_state,
        )
        return (
            orchestrated.bridge_base_url.rstrip("/"),
            orchestrated.mcp_url.strip(),
            normalized_probe_state,
        )

    async def lease(
        self,
        *,
        user_id: str,
        ttl_seconds: int,
        force_new: bool,
        wait_for_ready_seconds: int = 0,
    ) -> tuple[RuntimeRecord, Literal["created", "reused", "rotated"]]:
        normalized_user_id = user_id.strip()
        if not normalized_user_id:
            raise ValueError("user_id must be non-empty")

        user_label = self._safe_user_label(normalized_user_id)
        requested_ttl = self._bounded_ttl_seconds(ttl_seconds)
        logger.info(
            "whatsapp.runtime.lease.begin user=%s requested_ttl_seconds=%s bounded_ttl_seconds=%s force_new=%s wait_for_ready_seconds=%s",
            user_label,
            ttl_seconds,
            requested_ttl,
            force_new,
            wait_for_ready_seconds,
        )
        user_lock = await self._user_lock(normalized_user_id)
        async with user_lock:
            for _ in range(self.MAX_LEASE_ATTEMPTS):
                now = self._utc_now()
                existing = await self._repository.get_by_user(user_id=normalized_user_id)
                if existing and not force_new and self._is_reusable(existing, now):
                    logger.info(
                        "whatsapp.runtime.lease.reuse_candidate user=%s runtime_id=%s generation=%s state=%s",
                        user_label,
                        existing.runtime_id,
                        existing.generation,
                        existing.state,
                    )
                    bridge_base_url, mcp_url, runtime_state = await self._ensure_runtime(
                        user_id=normalized_user_id,
                        runtime_id=existing.runtime_id,
                        generation=existing.generation,
                        wait_for_ready_seconds=wait_for_ready_seconds,
                    )
                    lease_expires_at = self._clamp_lease_expiry(
                        now=now,
                        ttl_seconds=requested_ttl,
                        hard_expires_at=existing.hard_expires_at,
                    )
                    reused = await self._repository.touch_runtime(
                        user_id=normalized_user_id,
                        runtime_id=existing.runtime_id,
                        expected_generation=existing.generation,
                        lease_expires_at=lease_expires_at,
                        state=runtime_state,
                        bridge_base_url=bridge_base_url,
                        mcp_url=mcp_url,
                        desired_state="warm",
                        last_error_code=None,
                        last_error_at=None,
                    )
                    if reused is not None:
                        logger.info(
                            "whatsapp.runtime.lease.reused user=%s runtime_id=%s generation=%s state=%s bridge_base_url=%s mcp_url=%s",
                            user_label,
                            reused.runtime_id,
                            reused.generation,
                            reused.state,
                            reused.bridge_base_url,
                            reused.mcp_url,
                        )
                        return reused, "reused"
                    continue

                next_generation = (existing.generation + 1) if existing else 1
                runtime_id = self._new_runtime_id()
                logger.info(
                    "whatsapp.runtime.lease.create_candidate user=%s runtime_id=%s generation=%s previous_runtime_id=%s",
                    user_label,
                    runtime_id,
                    next_generation,
                    existing.runtime_id if existing else None,
                )
                runtime_started_at = now
                hard_expires_at = runtime_started_at + timedelta(
                    seconds=self._settings.runtime_max_lifetime_seconds
                )
                lease_expires_at = self._clamp_lease_expiry(
                    now=now,
                    ttl_seconds=requested_ttl,
                    hard_expires_at=hard_expires_at,
                )
                bridge_base_url, mcp_url, runtime_state = await self._ensure_runtime(
                    user_id=normalized_user_id,
                    runtime_id=runtime_id,
                    generation=next_generation,
                    wait_for_ready_seconds=wait_for_ready_seconds,
                )
                candidate = RuntimeRecord(
                    user_id=normalized_user_id,
                    runtime_id=runtime_id,
                    generation=next_generation,
                    state=runtime_state,
                    bridge_base_url=bridge_base_url,
                    mcp_url=mcp_url,
                    runtime_started_at=runtime_started_at,
                    hard_expires_at=hard_expires_at,
                    lease_expires_at=lease_expires_at,
                    last_error=None,
                )
                persisted = await self._repository.replace_runtime(
                    current=existing,
                    next_record=candidate,
                    desired_state="warm",
                )
                if persisted is not None:
                    action = "rotated" if existing else "created"
                    logger.info(
                        "whatsapp.runtime.lease.%s user=%s runtime_id=%s generation=%s state=%s bridge_base_url=%s mcp_url=%s",
                        action,
                        user_label,
                        persisted.runtime_id,
                        persisted.generation,
                        persisted.state,
                        persisted.bridge_base_url,
                        persisted.mcp_url,
                    )
                    return persisted, ("rotated" if existing else "created")

            raise RuntimeError("Failed to acquire runtime lease due to concurrent updates. Retry.")

    async def get(self, *, user_id: str, runtime_id: str) -> RuntimeRecord | None:
        normalized_user_id = user_id.strip()
        normalized_runtime_id = runtime_id.strip()
        if not normalized_user_id or not normalized_runtime_id:
            return None
        return await self._repository.get_by_user_runtime(
            user_id=normalized_user_id,
            runtime_id=normalized_runtime_id,
        )

    async def get_current(self, *, user_id: str) -> RuntimeRecord | None:
        normalized_user_id = user_id.strip()
        if not normalized_user_id:
            return None

        record = await self._repository.get_by_user(user_id=normalized_user_id)
        if record is None:
            return None

        now = self._utc_now()
        if now >= record.lease_expires_at:
            return None
        if now >= record.hard_expires_at:
            return None
        if record.state not in {"ready", "degraded"}:
            return None
        return record

    async def touch(
        self,
        *,
        user_id: str,
        runtime_id: str,
        ttl_seconds: int,
    ) -> RuntimeRecord | None:
        normalized_user_id = user_id.strip()
        normalized_runtime_id = runtime_id.strip()
        if not normalized_user_id or not normalized_runtime_id:
            return None

        user_label = self._safe_user_label(normalized_user_id)
        now = self._utc_now()
        requested_ttl = self._bounded_ttl_seconds(ttl_seconds)
        logger.info(
            "whatsapp.runtime.touch.begin user=%s runtime_id=%s requested_ttl_seconds=%s bounded_ttl_seconds=%s",
            user_label,
            normalized_runtime_id,
            ttl_seconds,
            requested_ttl,
        )
        user_lock = await self._user_lock(normalized_user_id)
        async with user_lock:
            record = await self._repository.get_by_user_runtime(
                user_id=normalized_user_id,
                runtime_id=normalized_runtime_id,
            )
            if record is None:
                logger.info(
                    "whatsapp.runtime.touch.not_found user=%s runtime_id=%s",
                    user_label,
                    normalized_runtime_id,
                )
                return None

            if now >= record.hard_expires_at:
                logger.info(
                    "whatsapp.runtime.touch.hard_expired user=%s runtime_id=%s generation=%s",
                    user_label,
                    normalized_runtime_id,
                    record.generation,
                )
                await self._repository.transition_state(
                    user_id=normalized_user_id,
                    runtime_id=normalized_runtime_id,
                    expected_generation=record.generation,
                    state="stopped",
                    desired_state="stopped",
                    lease_expires_at=now,
                    last_error_code="runtime_hard_expired",
                    last_error_at=now,
                )
                return None

            lease_expires_at = self._clamp_lease_expiry(
                now=now,
                ttl_seconds=requested_ttl,
                hard_expires_at=record.hard_expires_at,
            )
            bridge_base_url, mcp_url, runtime_state = await self._ensure_runtime(
                user_id=normalized_user_id,
                runtime_id=normalized_runtime_id,
                generation=record.generation,
            )
            touched = await self._repository.touch_runtime(
                user_id=normalized_user_id,
                runtime_id=normalized_runtime_id,
                expected_generation=record.generation,
                lease_expires_at=lease_expires_at,
                state=runtime_state,
                bridge_base_url=bridge_base_url,
                mcp_url=mcp_url,
                desired_state="warm",
                last_error_code=None,
                last_error_at=None,
            )
            if touched is not None:
                logger.info(
                    "whatsapp.runtime.touch.complete user=%s runtime_id=%s generation=%s state=%s bridge_base_url=%s mcp_url=%s",
                    user_label,
                    touched.runtime_id,
                    touched.generation,
                    touched.state,
                    touched.bridge_base_url,
                    touched.mcp_url,
                )
            return touched

    async def disconnect(self, *, user_id: str, runtime_id: str) -> RuntimeRecord | None:
        normalized_user_id = user_id.strip()
        normalized_runtime_id = runtime_id.strip()
        if not normalized_user_id or not normalized_runtime_id:
            return None

        user_label = self._safe_user_label(normalized_user_id)
        logger.info(
            "whatsapp.runtime.disconnect.begin user=%s runtime_id=%s",
            user_label,
            normalized_runtime_id,
        )
        user_lock = await self._user_lock(normalized_user_id)
        async with user_lock:
            record = await self._repository.get_by_user_runtime(
                user_id=normalized_user_id,
                runtime_id=normalized_runtime_id,
            )
            if record is None:
                logger.info(
                    "whatsapp.runtime.disconnect.not_found user=%s runtime_id=%s",
                    user_label,
                    normalized_runtime_id,
                )
                return None

            now = self._utc_now()
            await self._orchestrator.disconnect_runtime(
                user_id=normalized_user_id,
                runtime_id=normalized_runtime_id,
                generation=record.generation,
            )
            transitioned = await self._repository.transition_state(
                user_id=normalized_user_id,
                runtime_id=normalized_runtime_id,
                expected_generation=record.generation,
                state="stopped",
                desired_state="stopped",
                lease_expires_at=now,
                last_error_code=None,
                last_error_at=None,
            )
            logger.info(
                "whatsapp.runtime.disconnect.complete user=%s runtime_id=%s generation=%s",
                user_label,
                normalized_runtime_id,
                record.generation,
            )
            return transitioned

    async def status(self, *, user_id: str, runtime_id: str) -> dict[str, str | int | None] | None:
        record = await self.get(user_id=user_id, runtime_id=runtime_id)
        if record is None:
            return None
        return self._to_status_dict(record)


_runtime_manager: RuntimeManager | None = None


def get_runtime_manager() -> RuntimeManager:
    global _runtime_manager
    if _runtime_manager is None:
        settings = get_controller_settings()
        repository = RuntimeLeaseRepository(table_name=settings.runtime_lease_table)
        orchestrator = get_runtime_orchestrator()
        _runtime_manager = RuntimeManager(
            settings=settings,
            repository=repository,
            orchestrator=orchestrator,
        )
    return _runtime_manager
