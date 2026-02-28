from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from postgrest.exceptions import APIError

from whatsapp_session_controller.db.client import create_service_supabase_client
from whatsapp_session_controller.services.runtime_types import RuntimeRecord, RuntimeState


_VALID_RUNTIME_STATES: set[str] = {
    "provisioning",
    "starting",
    "ready",
    "degraded",
    "stopping",
    "stopped",
    "error",
}


class RuntimeLeaseRepository:
    _SELECT_COLUMNS = (
        "user_id, runtime_id, runtime_generation, controller_state, desired_state, "
        "bridge_base_url, mcp_url, runtime_started_at, hard_expires_at, lease_expires_at, "
        "last_touched_at, last_error_code, last_error_at, created_at, updated_at"
    )

    def __init__(self, *, table_name: str) -> None:
        normalized_table_name = table_name.strip()
        if not normalized_table_name:
            raise ValueError("table_name must be non-empty")
        self._table_name = normalized_table_name

    @staticmethod
    def _parse_iso_datetime(raw: Any, *, field_name: str) -> datetime:
        if isinstance(raw, datetime):
            parsed = raw
        elif isinstance(raw, str):
            normalized = raw.strip()
            if not normalized:
                raise ValueError(f"{field_name} is empty")
            if normalized.endswith("Z"):
                normalized = normalized[:-1] + "+00:00"
            parsed = datetime.fromisoformat(normalized)
        else:
            raise ValueError(f"{field_name} is invalid")

        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    @staticmethod
    def _to_iso(value: datetime) -> str:
        return value.astimezone(timezone.utc).isoformat()

    @classmethod
    def _normalize_state(cls, raw: Any) -> RuntimeState:
        state = str(raw or "").strip().lower()
        if state not in _VALID_RUNTIME_STATES:
            raise ValueError(f"Invalid runtime state in DB row: {raw!r}")
        return state  # type: ignore[return-value]

    @classmethod
    def _from_row(cls, row: dict[str, Any] | None) -> RuntimeRecord | None:
        if row is None:
            return None
        runtime_generation = row.get("runtime_generation")
        generation = int(runtime_generation) if isinstance(runtime_generation, int) else 0
        if generation <= 0:
            raise ValueError("runtime_generation must be a positive integer")

        user_id = str(row.get("user_id") or "").strip()
        runtime_id = str(row.get("runtime_id") or "").strip()
        bridge_base_url = str(row.get("bridge_base_url") or "").strip()
        mcp_url = str(row.get("mcp_url") or "").strip()
        if not user_id or not runtime_id or not bridge_base_url or not mcp_url:
            raise ValueError("Missing required runtime lease fields")

        return RuntimeRecord(
            user_id=user_id,
            runtime_id=runtime_id,
            generation=generation,
            state=cls._normalize_state(row.get("controller_state")),
            bridge_base_url=bridge_base_url,
            mcp_url=mcp_url,
            runtime_started_at=cls._parse_iso_datetime(
                row.get("runtime_started_at"), field_name="runtime_started_at"
            ),
            hard_expires_at=cls._parse_iso_datetime(
                row.get("hard_expires_at"), field_name="hard_expires_at"
            ),
            lease_expires_at=cls._parse_iso_datetime(
                row.get("lease_expires_at"), field_name="lease_expires_at"
            ),
            last_error=(
                str(row.get("last_error_code")).strip()
                if isinstance(row.get("last_error_code"), str)
                and str(row.get("last_error_code")).strip()
                else None
            ),
        )

    async def get_by_user(self, *, user_id: str) -> RuntimeRecord | None:
        client = await create_service_supabase_client()
        try:
            response = await (
                client.table(self._table_name)
                .select(self._SELECT_COLUMNS)
                .eq("user_id", user_id)
                .maybe_single()
                .execute()
            )
            return self._from_row(response.data if response else None)
        finally:
            await client.postgrest.aclose()

    async def get_by_user_runtime(
        self,
        *,
        user_id: str,
        runtime_id: str,
    ) -> RuntimeRecord | None:
        client = await create_service_supabase_client()
        try:
            response = await (
                client.table(self._table_name)
                .select(self._SELECT_COLUMNS)
                .eq("user_id", user_id)
                .eq("runtime_id", runtime_id)
                .maybe_single()
                .execute()
            )
            return self._from_row(response.data if response else None)
        finally:
            await client.postgrest.aclose()

    async def replace_runtime(
        self,
        *,
        current: RuntimeRecord | None,
        next_record: RuntimeRecord,
        desired_state: str = "warm",
    ) -> RuntimeRecord | None:
        now_iso = self._to_iso(datetime.now(timezone.utc))
        insert_payload: dict[str, Any] = {
            "user_id": next_record.user_id,
            "runtime_id": next_record.runtime_id,
            "runtime_generation": next_record.generation,
            "controller_state": next_record.state,
            "desired_state": desired_state,
            "bridge_base_url": next_record.bridge_base_url,
            "mcp_url": next_record.mcp_url,
            "runtime_started_at": self._to_iso(next_record.runtime_started_at),
            "hard_expires_at": self._to_iso(next_record.hard_expires_at),
            "lease_expires_at": self._to_iso(next_record.lease_expires_at),
            "last_touched_at": now_iso,
            "last_error_code": next_record.last_error,
            "last_error_at": now_iso if next_record.last_error else None,
        }
        update_payload = {key: value for key, value in insert_payload.items() if key != "user_id"}

        client = await create_service_supabase_client()
        try:
            if current is None:
                try:
                    response = await (
                        client.table(self._table_name)
                        .insert(insert_payload)
                        .select(self._SELECT_COLUMNS)
                        .maybe_single()
                        .execute()
                    )
                except APIError as exc:
                    # Concurrent create for same user_id. Treat only unique violation as CAS miss.
                    if str(getattr(exc, "code", "")).strip() != "23505":
                        raise
                    return None
                return self._from_row(response.data if response else None)

            response = await (
                client.table(self._table_name)
                .update(update_payload)
                .eq("user_id", current.user_id)
                .eq("runtime_id", current.runtime_id)
                .eq("runtime_generation", current.generation)
                .select(self._SELECT_COLUMNS)
                .maybe_single()
                .execute()
            )
            return self._from_row(response.data if response else None)
        finally:
            await client.postgrest.aclose()

    async def touch_runtime(
        self,
        *,
        user_id: str,
        runtime_id: str,
        expected_generation: int,
        lease_expires_at: datetime,
        state: RuntimeState,
        bridge_base_url: str | None = None,
        mcp_url: str | None = None,
        desired_state: str = "warm",
        last_error_code: str | None = None,
        last_error_at: datetime | None = None,
    ) -> RuntimeRecord | None:
        now = datetime.now(timezone.utc)
        payload: dict[str, Any] = {
            "lease_expires_at": self._to_iso(lease_expires_at),
            "controller_state": state,
            "desired_state": desired_state,
            "last_touched_at": self._to_iso(now),
            "last_error_code": last_error_code,
            "last_error_at": self._to_iso(last_error_at) if last_error_at else None,
        }
        if bridge_base_url is not None:
            payload["bridge_base_url"] = bridge_base_url
        if mcp_url is not None:
            payload["mcp_url"] = mcp_url

        client = await create_service_supabase_client()
        try:
            response = await (
                client.table(self._table_name)
                .update(payload)
                .eq("user_id", user_id)
                .eq("runtime_id", runtime_id)
                .eq("runtime_generation", expected_generation)
                .select(self._SELECT_COLUMNS)
                .maybe_single()
                .execute()
            )
            return self._from_row(response.data if response else None)
        finally:
            await client.postgrest.aclose()

    async def transition_state(
        self,
        *,
        user_id: str,
        runtime_id: str,
        expected_generation: int,
        state: RuntimeState,
        desired_state: str | None = None,
        lease_expires_at: datetime | None = None,
        last_error_code: str | None = None,
        last_error_at: datetime | None = None,
    ) -> RuntimeRecord | None:
        now = datetime.now(timezone.utc)
        payload: dict[str, Any] = {
            "controller_state": state,
            "last_touched_at": self._to_iso(now),
            "last_error_code": last_error_code,
            "last_error_at": self._to_iso(last_error_at) if last_error_at else None,
        }
        if desired_state is not None:
            payload["desired_state"] = desired_state
        if lease_expires_at is not None:
            payload["lease_expires_at"] = self._to_iso(lease_expires_at)

        client = await create_service_supabase_client()
        try:
            response = await (
                client.table(self._table_name)
                .update(payload)
                .eq("user_id", user_id)
                .eq("runtime_id", runtime_id)
                .eq("runtime_generation", expected_generation)
                .select(self._SELECT_COLUMNS)
                .maybe_single()
                .execute()
            )
            return self._from_row(response.data if response else None)
        finally:
            await client.postgrest.aclose()

    async def delete_runtime(
        self,
        *,
        user_id: str,
        runtime_id: str,
        expected_generation: int,
    ) -> bool:
        client = await create_service_supabase_client()
        try:
            response = await (
                client.table(self._table_name)
                .delete()
                .eq("user_id", user_id)
                .eq("runtime_id", runtime_id)
                .eq("runtime_generation", expected_generation)
                .execute()
            )
            deleted_rows = response.data if response else None
            return bool(deleted_rows)
        finally:
            await client.postgrest.aclose()
