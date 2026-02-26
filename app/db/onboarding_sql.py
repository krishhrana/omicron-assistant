from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from app.core.settings import get_settings
from app.dependencies import (
    create_supabase_service_client,
    create_supabase_user_client,
)


@dataclass(frozen=True)
class ConnectedAppsStatus:
    gmail: bool
    google_drive: bool
    whatsapp: bool

    @property
    def connected_app_ids(self) -> list[str]:
        connected: list[str] = []
        if self.gmail:
            connected.append("gmail")
        if self.google_drive:
            connected.append("drive")
        if self.whatsapp:
            connected.append("whatsapp")
        return connected

    @property
    def connected_count(self) -> int:
        return int(self.gmail) + int(self.google_drive) + int(self.whatsapp)

    def as_dict(self) -> dict[str, Any]:
        return {
            "gmail": self.gmail,
            "google_drive": self.google_drive,
            "whatsapp": self.whatsapp,
            "connected_app_ids": self.connected_app_ids,
            "connected_count": self.connected_count,
        }


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_browser_credentials_secret_name(user_id: str) -> str:
    prefix = get_settings().browser_runner_vault_secret_prefix
    return f"{prefix}{user_id}"


async def get_user_profile(*, user_id: str, user_jwt: str) -> dict[str, Any] | None:
    client = await create_supabase_user_client(user_jwt)
    try:
        response = await (
            client.table("user_profiles")
            .select("user_id, name, city, age, gender, created_at, updated_at")
            .eq("user_id", user_id)
            .maybe_single()
            .execute()
        )
        return response.data if response else None
    finally:
        await client.postgrest.aclose()


async def upsert_user_profile(
    *,
    user_id: str,
    user_jwt: str,
    name: str,
    city: str | None = None,
    age: int | None = None,
    gender: str | None = None,
) -> dict[str, Any]:
    client = await create_supabase_user_client(user_jwt)
    try:
        payload: dict[str, Any] = {
            "user_id": user_id,
            "name": name,
            "city": city,
            "age": age,
            "gender": gender,
        }
        await client.table("user_profiles").upsert(payload, on_conflict="user_id").execute()
        response = await (
            client.table("user_profiles")
            .select("user_id, name, city, age, gender, created_at, updated_at")
            .eq("user_id", user_id)
            .maybe_single()
            .execute()
        )
        profile = response.data if response else None
        if not profile:
            raise RuntimeError("Failed to load user profile after upsert")
        return profile
    finally:
        await client.postgrest.aclose()


async def get_user_onboarding(*, user_id: str, user_jwt: str) -> dict[str, Any] | None:
    client = await create_supabase_user_client(user_jwt)
    try:
        response = await (
            client.table("user_onboarding")
            .select("user_id, onboarding_completed_at, onboarding_version, created_at, updated_at")
            .eq("user_id", user_id)
            .maybe_single()
            .execute()
        )
        return response.data if response else None
    finally:
        await client.postgrest.aclose()


async def upsert_user_onboarding(
    *,
    user_id: str,
    user_jwt: str,
    onboarding_completed_at: str | None = None,
    onboarding_version: int = 1,
) -> dict[str, Any]:
    client = await create_supabase_user_client(user_jwt)
    try:
        payload: dict[str, Any] = {
            "user_id": user_id,
            "onboarding_version": onboarding_version,
            "onboarding_completed_at": onboarding_completed_at,
        }
        await client.table("user_onboarding").upsert(payload, on_conflict="user_id").execute()
        response = await (
            client.table("user_onboarding")
            .select("user_id, onboarding_completed_at, onboarding_version, created_at, updated_at")
            .eq("user_id", user_id)
            .maybe_single()
            .execute()
        )
        row = response.data if response else None
        if not row:
            raise RuntimeError("Failed to load user onboarding row after upsert")
        return row
    finally:
        await client.postgrest.aclose()


async def mark_user_onboarding_completed(
    *,
    user_id: str,
    user_jwt: str,
    onboarding_version: int = 1,
) -> dict[str, Any]:
    return await upsert_user_onboarding(
        user_id=user_id,
        user_jwt=user_jwt,
        onboarding_completed_at=_utc_now_iso(),
        onboarding_version=onboarding_version,
    )


async def get_connected_apps_status(*, user_id: str, user_jwt: str) -> ConnectedAppsStatus:
    client = await create_supabase_user_client(user_jwt)
    try:
        gmail_resp = await (
            client.table("gmail_connections")
            .select("status")
            .eq("user_id", user_id)
            .maybe_single()
            .execute()
        )
        drive_resp = await (
            client.table("google_drive_connections")
            .select("status")
            .eq("user_id", user_id)
            .maybe_single()
            .execute()
        )
        try:
            whatsapp_resp = await (
                client.table("whatsapp_connections")
                .select("status")
                .eq("user_id", user_id)
                .maybe_single()
                .execute()
            )
        except Exception:
            whatsapp_resp = None
    finally:
        await client.postgrest.aclose()

    gmail_status = (
        gmail_resp.data.get("status")
        if gmail_resp and isinstance(gmail_resp.data, dict)
        else None
    )
    drive_status = (
        drive_resp.data.get("status")
        if drive_resp and isinstance(drive_resp.data, dict)
        else None
    )
    whatsapp_status = (
        whatsapp_resp.data.get("status")
        if whatsapp_resp and isinstance(whatsapp_resp.data, dict)
        else None
    )
    return ConnectedAppsStatus(
        gmail=gmail_status == "active",
        google_drive=drive_status == "active",
        whatsapp=whatsapp_status == "connected",
    )


async def get_browser_credentials_secret(*, user_id: str) -> str | None:
    secret_name = get_browser_credentials_secret_name(user_id)
    client = await create_supabase_service_client()
    try:
        response = await (
            client.rpc("get_vault_secret", {"secret_name": secret_name}).execute()
        )
        secret = response.data if response else None
        if secret is None:
            return None
        return str(secret)
    finally:
        await client.postgrest.aclose()


async def upsert_browser_credentials_secret(
    *,
    user_id: str,
    secret_payload: dict[str, Any] | str,
) -> str:
    secret_name = get_browser_credentials_secret_name(user_id)
    secret_value = (
        json.dumps(secret_payload) if isinstance(secret_payload, dict) else secret_payload
    )
    client = await create_supabase_service_client()
    try:
        await (
            client.rpc(
                "upsert_vault_secret",
                {
                    "secret_name": secret_name,
                    "secret_value": secret_value,
                    "secret_description": f"Omicron - {user_id} - browser website credentials",
                },
            )
            .execute()
        )
        return secret_name
    finally:
        await client.postgrest.aclose()
