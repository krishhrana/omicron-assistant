from __future__ import annotations

import re
from typing import Any

from app.core.enums import SupportedApps
from app.services import list_browser_credentials_metadata
from app.utils.agent_utils import UserContext


_SECRET_REF_NORMALIZER = re.compile(r"[^A-Z0-9]+")


def _normalize_secret_ref_site_key(site_key: str) -> str:
    normalized = _SECRET_REF_NORMALIZER.sub("_", site_key.strip().upper()).strip("_")
    return normalized or "SITE"


def build_browser_credential_secret_refs(credentials: list[dict[str, Any]]) -> list[str]:
    refs: list[str] = []
    for credential in credentials:
        site_key = credential.get("site_key")
        if not isinstance(site_key, str) or not site_key.strip():
            continue

        normalized_site_key = _normalize_secret_ref_site_key(site_key)
        username_ref = f"{normalized_site_key}_USERNAME"
        password_ref = f"{normalized_site_key}_PASSWORD"

        site_name = credential.get("site_name")
        resolved_site_name = (
            site_name.strip()
            if isinstance(site_name, str) and site_name.strip()
            else site_key
        )
        login_url = credential.get("login_url")
        login_suffix = (
            f" (login: {login_url})"
            if isinstance(login_url, str) and login_url.strip()
            else ""
        )
        refs.append(
            f"{resolved_site_name} [{site_key}]: `{username_ref}`, `{password_ref}`{login_suffix}"
        )

    return list(dict.fromkeys(refs))


async def resolve_browser_credential_secret_refs(
    *,
    user_ctx: UserContext | None,
) -> list[str]:
    if user_ctx is None or not user_ctx.user_id:
        return []

    connected_apps = user_ctx.connected_apps or []
    if SupportedApps.BROWSER not in connected_apps:
        return []

    try:
        browser_credentials = await list_browser_credentials_metadata(user_id=user_ctx.user_id)
        return build_browser_credential_secret_refs(browser_credentials)
    except Exception as exc:
        # Local best-effort: agent still runs without refs if secret metadata lookup fails.
        print(f"Failed to load browser credential refs for user_id={user_ctx.user_id}: {exc}")
        return []
