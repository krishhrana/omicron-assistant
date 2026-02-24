from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

from app.db.onboarding_sql import (
    get_browser_credentials_secret,
    get_connected_apps_status,
    get_user_onboarding,
    get_user_profile,
    mark_user_onboarding_completed,
    upsert_browser_credentials_secret,
    upsert_user_profile,
)

_SITE_KEY_PATTERN = re.compile(r"[^a-z0-9]+")


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_site_key(value: str) -> str:
    lowered = value.strip().lower()
    normalized = _SITE_KEY_PATTERN.sub("_", lowered).strip("_")
    return normalized or "site"


def _site_key_from_inputs(site_name: str, login_url: str | None) -> str:
    if site_name.strip():
        return _normalize_site_key(site_name)

    if login_url:
        parsed = urlparse(login_url)
        if parsed.hostname:
            return _normalize_site_key(parsed.hostname)

    return "site"


def _mask_username(username: str) -> str:
    if not username:
        return ""

    if "@" in username:
        local_part, domain = username.split("@", 1)
        if len(local_part) <= 2:
            masked_local = "*" * len(local_part)
        else:
            masked_local = f"{local_part[0]}{'*' * (len(local_part) - 2)}{local_part[-1]}"
        return f"{masked_local}@{domain}"

    if len(username) <= 2:
        return "*" * len(username)

    return f"{username[0]}{'*' * (len(username) - 2)}{username[-1]}"


def _parse_json_credentials(payload: dict[str, Any]) -> list[dict[str, Any]]:
    raw_sites = payload.get("sites")
    if not isinstance(raw_sites, list):
        return []

    parsed: list[dict[str, Any]] = []
    for raw_site in raw_sites:
        if not isinstance(raw_site, dict):
            continue

        username = raw_site.get("username")
        password = raw_site.get("password")
        if not isinstance(username, str) or not username.strip():
            continue
        if not isinstance(password, str) or not password:
            continue

        site_name = raw_site.get("site_name")
        login_url = raw_site.get("login_url")
        site_key = raw_site.get("site_key")

        resolved_site_name = site_name.strip() if isinstance(site_name, str) else ""
        resolved_login_url = login_url.strip() if isinstance(login_url, str) else None
        resolved_site_key = (
            _normalize_site_key(site_key)
            if isinstance(site_key, str) and site_key.strip()
            else _site_key_from_inputs(resolved_site_name, resolved_login_url)
        )

        parsed.append(
            {
                "site_key": resolved_site_key,
                "site_name": resolved_site_name or resolved_site_key.replace("_", " ").title(),
                "login_url": resolved_login_url,
                "username": username.strip(),
                "password": password,
                "created_at": (
                    raw_site.get("created_at")
                    if isinstance(raw_site.get("created_at"), str)
                    else None
                ),
            }
        )

    return parsed


def _empty_credentials_payload() -> dict[str, Any]:
    return {"version": 1, "sites": []}


def _parse_browser_credentials_secret(secret_value: str | None) -> dict[str, Any]:
    if not secret_value:
        return _empty_credentials_payload()

    try:
        parsed = json.loads(secret_value)
    except json.JSONDecodeError:
        raise ValueError("Browser credential secret must be valid JSON")

    if isinstance(parsed, dict):
        version = parsed.get("version")
        resolved_version = version if isinstance(version, int) and version >= 1 else 1
        return {
            "version": resolved_version,
            "sites": _parse_json_credentials(parsed),
        }

    raise ValueError("Browser credential secret JSON must be an object")


def _sanitize_browser_credential(credential: dict[str, Any]) -> dict[str, Any]:
    username = credential.get("username")
    return {
        "site_key": credential.get("site_key"),
        "site_name": credential.get("site_name"),
        "login_url": credential.get("login_url"),
        "username_masked": _mask_username(username if isinstance(username, str) else ""),
        "created_at": credential.get("created_at"),
    }


def _profile_complete(profile: dict[str, Any] | None) -> bool:
    if not profile:
        return False

    name = profile.get("name")
    city = profile.get("city")
    age = profile.get("age")

    if not isinstance(name, str) or not name.strip():
        return False
    if not isinstance(city, str) or not city.strip():
        return False
    if isinstance(age, bool):
        return False
    if not isinstance(age, int):
        return False

    return 13 <= age <= 120


def _resolve_current_step(
    *,
    profile_complete: bool,
    app_connected: bool,
    browser_credentials_added: bool,
) -> int:
    if not profile_complete:
        return 2
    if not app_connected or not browser_credentials_added:
        return 3
    return 3


def _trim_optional(value: str | None) -> str | None:
    if value is None:
        return None
    trimmed = value.strip()
    return trimmed or None


async def list_browser_credentials(*, user_id: str) -> dict[str, Any]:
    secret = await get_browser_credentials_secret(user_id=user_id)
    return _parse_browser_credentials_secret(secret)


async def list_browser_credentials_metadata(*, user_id: str) -> list[dict[str, Any]]:
    credentials_payload = await list_browser_credentials(user_id=user_id)
    credentials = credentials_payload.get("sites", [])
    return [_sanitize_browser_credential(item) for item in credentials]


async def save_user_profile(
    *,
    user_id: str,
    user_jwt: str,
    name: str,
    city: str | None = None,
    age: int | None = None,
    gender: str | None = None,
) -> dict[str, Any]:
    trimmed_name = name.strip()
    trimmed_city = _trim_optional(city)
    if not trimmed_name:
        raise ValueError("name is required")

    if not trimmed_city:
        raise ValueError("city is required")

    if age is None or isinstance(age, bool):
        raise ValueError("age is required")
    if age < 13 or age > 120:
        raise ValueError("age must be between 13 and 120")

    return await upsert_user_profile(
        user_id=user_id,
        user_jwt=user_jwt,
        name=trimmed_name,
        city=trimmed_city,
        age=age,
        gender=_trim_optional(gender),
    )


async def upsert_browser_credential(
    *,
    user_id: str,
    site_name: str,
    login_url: str | None,
    username: str,
    password: str,
) -> dict[str, Any]:
    trimmed_site_name = site_name.strip()
    trimmed_username = username.strip()
    if not trimmed_site_name:
        raise ValueError("site_name is required")
    if not trimmed_username:
        raise ValueError("username is required")
    if not password:
        raise ValueError("password is required")

    parsed_login_url = _trim_optional(login_url)
    site_key = _site_key_from_inputs(trimmed_site_name, parsed_login_url)

    credentials_payload = await list_browser_credentials(user_id=user_id)
    existing = list(credentials_payload.get("sites", []))
    now_iso = _utc_now_iso()
    created_at = now_iso

    updated = False
    for index, item in enumerate(existing):
        if item.get("site_key") == site_key:
            created_at = (
                item.get("created_at")
                if isinstance(item.get("created_at"), str) and item.get("created_at")
                else now_iso
            )
            existing[index] = {
                "site_key": site_key,
                "site_name": trimmed_site_name,
                "login_url": parsed_login_url,
                "username": trimmed_username,
                "password": password,
                "created_at": created_at,
            }
            updated = True
            break

    if not updated:
        existing.append(
            {
                "site_key": site_key,
                "site_name": trimmed_site_name,
                "login_url": parsed_login_url,
                "username": trimmed_username,
                "password": password,
                "created_at": now_iso,
            }
        )

    await upsert_browser_credentials_secret(
        user_id=user_id,
        secret_payload={
            "version": credentials_payload.get("version", 1),
            "sites": existing,
        },
    )

    return _sanitize_browser_credential(
        {
            "site_key": site_key,
            "site_name": trimmed_site_name,
            "login_url": parsed_login_url,
            "username": trimmed_username,
            "created_at": created_at,
        }
    )


async def delete_browser_credential(*, user_id: str, site_key: str) -> bool:
    normalized_site_key = _normalize_site_key(site_key)
    credentials_payload = await list_browser_credentials(user_id=user_id)
    existing = list(credentials_payload.get("sites", []))
    next_credentials = [
        credential
        for credential in existing
        if credential.get("site_key") != normalized_site_key
    ]

    if len(next_credentials) == len(existing):
        return False

    await upsert_browser_credentials_secret(
        user_id=user_id,
        secret_payload={
            "version": credentials_payload.get("version", 1),
            "sites": next_credentials,
        },
    )
    return True


async def get_onboarding_state(*, user_id: str, user_jwt: str) -> dict[str, Any]:
    profile = await get_user_profile(user_id=user_id, user_jwt=user_jwt)
    onboarding_row = await get_user_onboarding(user_id=user_id, user_jwt=user_jwt)
    connected_apps = await get_connected_apps_status(user_id=user_id, user_jwt=user_jwt)
    browser_credentials_payload = await list_browser_credentials(user_id=user_id)
    browser_credentials = browser_credentials_payload.get("sites", [])

    profile_complete = _profile_complete(profile)
    app_connected = connected_apps.connected_count > 0
    browser_credentials_added = len(browser_credentials) > 0
    requirements = {
        "profile_complete": profile_complete,
        "app_connected": app_connected,
        "browser_credentials_added": browser_credentials_added,
    }
    can_complete = all(requirements.values())

    completion_marked_at = (
        onboarding_row.get("onboarding_completed_at")
        if isinstance(onboarding_row, dict)
        else None
    )
    completion_marked = isinstance(completion_marked_at, str) and bool(
        completion_marked_at.strip()
    )
    is_complete = can_complete and completion_marked

    current_step = _resolve_current_step(
        profile_complete=profile_complete,
        app_connected=app_connected,
        browser_credentials_added=browser_credentials_added,
    )

    return {
        "is_complete": is_complete,
        "can_complete": can_complete,
        "current_step": current_step,
        "profile": profile,
        "connections": connected_apps.as_dict(),
        "website_credentials": [
            _sanitize_browser_credential(credential)
            for credential in browser_credentials
        ],
        "requirements": requirements,
        "onboarding_completed_at": completion_marked_at,
    }


async def mark_onboarding_complete(*, user_id: str, user_jwt: str) -> dict[str, Any]:
    state = await get_onboarding_state(user_id=user_id, user_jwt=user_jwt)
    if not state["can_complete"]:
        raise ValueError("onboarding requirements are not complete")

    await mark_user_onboarding_completed(user_id=user_id, user_jwt=user_jwt)
    return await get_onboarding_state(user_id=user_id, user_jwt=user_jwt)
