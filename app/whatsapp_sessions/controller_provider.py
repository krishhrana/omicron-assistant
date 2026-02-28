from __future__ import annotations

from typing import Any

import httpx

from app.core.settings import WhatsAppSessionSettings

from .controller_auth import (
    WhatsAppControllerAuthError,
    mint_controller_disconnect_bearer_header,
    mint_controller_lease_bearer_header,
    mint_controller_read_current_bearer_header,
    mint_controller_touch_bearer_header,
)
from .base import WhatsAppRuntimeLease


class ControllerLeaseUnavailableError(RuntimeError):
    """Transient lease failure when controller endpoint is unavailable."""


class ControllerLeaseResponseError(RuntimeError):
    """Non-transient lease failure from controller response."""


class ControllerLeaseNotReadyError(RuntimeError):
    """Lease call succeeded but runtime is still warming up."""


class ControllerWhatsAppSessionProvider:
    """ECS/Kubernetes-backed WhatsApp session controller provider."""

    LEASE_TTL_SECONDS = 600

    def __init__(self, settings: WhatsAppSessionSettings) -> None:
        self._settings = settings

    def _required_controller_base_url(self) -> str:
        base_url = (self._settings.controller_url or "").strip().rstrip("/")
        if not base_url:
            raise RuntimeError(
                "WHATSAPP_SESSION_CONTROLLER_URL is required when "
                "WHATSAPP_SESSION_PROVIDER=controller."
            )
        return base_url

    def _controller_timeout(self) -> float:
        timeout = float(self._settings.controller_timeout_seconds)
        if timeout <= 0:
            raise RuntimeError("WHATSAPP_SESSION_CONTROLLER_TIMEOUT_SECONDS must be greater than 0.")
        return timeout

    @staticmethod
    def _normalize_runtime_lease(payload: dict[str, Any]) -> WhatsAppRuntimeLease:
        runtime_id = str(payload.get("runtime_id") or "").strip()
        bridge_base_url = str(payload.get("bridge_base_url") or "").strip().rstrip("/")
        mcp_url_raw = payload.get("mcp_url")
        mcp_url = str(mcp_url_raw).strip() if isinstance(mcp_url_raw, str) else None
        state = str(payload.get("state") or "").strip().lower()
        poll_after_seconds = payload.get("poll_after_seconds")

        if not runtime_id:
            raise ControllerLeaseResponseError("Controller lease response missing runtime_id")
        if not bridge_base_url:
            raise ControllerLeaseResponseError("Controller lease response missing bridge_base_url")

        normalized_state = state if state else "starting"
        if normalized_state not in {
            "provisioning",
            "starting",
            "ready",
            "degraded",
            "stopping",
            "stopped",
            "error",
        }:
            normalized_state = "error"

        if normalized_state not in {"ready", "degraded"}:
            poll_hint = (
                int(poll_after_seconds)
                if isinstance(poll_after_seconds, int) and poll_after_seconds > 0
                else 2
            )
            raise ControllerLeaseNotReadyError(
                f"WhatsApp runtime is not ready yet (state={normalized_state}). "
                f"Retry after {poll_hint}s."
            )
        return WhatsAppRuntimeLease(
            runtime_id=runtime_id,
            bridge_base_url=bridge_base_url,
            mcp_url=mcp_url,
        )

    async def _request_controller_lease(
        self,
        *,
        user_id: str,
    ) -> WhatsAppRuntimeLease:  # noqa: PLR0911
        base_url = self._required_controller_base_url()
        timeout = self._controller_timeout()
        try:
            headers = mint_controller_lease_bearer_header(user_id=user_id)
        except WhatsAppControllerAuthError as exc:
            raise RuntimeError(str(exc)) from exc

        payload = {
            "user_id": user_id,
            "ttl_seconds": self.LEASE_TTL_SECONDS,
            "wait_for_ready_seconds": 15,
            "force_new": False,
        }
        url = f"{base_url}/v1/whatsapp/runtimes/lease"
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(url, headers=headers, json=payload)
        except httpx.RequestError as exc:
            raise ControllerLeaseUnavailableError(
                f"WhatsApp session controller is unavailable: {exc}"
            ) from exc

        detail = f"Failed to lease WhatsApp runtime (HTTP {response.status_code})"
        try:
            response_body = response.json()
            if isinstance(response_body, dict):
                message = response_body.get("message") or response_body.get("detail")
                if isinstance(message, str) and message.strip():
                    detail = message.strip()
            else:
                response_body = None
        except Exception:
            response_body = None

        if response.status_code in {200, 202}:
            if not isinstance(response_body, dict):
                raise ControllerLeaseResponseError("Invalid controller lease response payload")
            return self._normalize_runtime_lease(response_body)

        if response.status_code == 429 or response.status_code >= 500:
            raise ControllerLeaseUnavailableError(detail)
        raise ControllerLeaseResponseError(detail)

    async def _request_controller_current(
        self,
        *,
        user_id: str,
    ) -> WhatsAppRuntimeLease | None:
        base_url = self._required_controller_base_url()
        timeout = self._controller_timeout()
        try:
            headers = mint_controller_read_current_bearer_header(user_id=user_id)
        except WhatsAppControllerAuthError as exc:
            raise RuntimeError(str(exc)) from exc

        url = f"{base_url}/v1/whatsapp/runtimes/current"
        query_params = {"user_id": user_id}
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.get(url, headers=headers, params=query_params)
        except httpx.RequestError as exc:
            raise ControllerLeaseUnavailableError(
                f"WhatsApp session controller is unavailable: {exc}"
            ) from exc

        if response.status_code == 404:
            return None

        detail = f"Failed to read WhatsApp runtime (HTTP {response.status_code})"
        try:
            response_body = response.json()
            if isinstance(response_body, dict):
                message = response_body.get("message") or response_body.get("detail")
                if isinstance(message, str) and message.strip():
                    detail = message.strip()
            else:
                response_body = None
        except Exception:
            response_body = None

        if response.status_code == 200:
            if not isinstance(response_body, dict):
                raise ControllerLeaseResponseError("Invalid controller runtime response payload")
            try:
                return self._normalize_runtime_lease(response_body)
            except ControllerLeaseNotReadyError:
                return None

        if response.status_code == 429 or response.status_code >= 500:
            raise ControllerLeaseUnavailableError(detail)
        raise ControllerLeaseResponseError(detail)

    async def get_or_create(
        self,
        *,
        user_id: str,
        user_jwt: str,
    ) -> WhatsAppRuntimeLease:
        _ = user_jwt
        try:
            return await self._request_controller_lease(user_id=user_id)
        except ControllerLeaseUnavailableError as exc:
            raise RuntimeError(str(exc)) from exc
        except ControllerLeaseNotReadyError as exc:
            raise RuntimeError(str(exc)) from exc

    async def read_current(
        self,
        *,
        user_id: str,
        user_jwt: str,
    ) -> WhatsAppRuntimeLease | None:
        _ = user_jwt
        try:
            return await self._request_controller_current(user_id=user_id)
        except ControllerLeaseUnavailableError as exc:
            raise RuntimeError(str(exc)) from exc

    async def disconnect(
        self,
        *,
        user_id: str,
        user_jwt: str,
        runtime_id: str | None = None,
    ) -> None:
        _ = user_jwt
        resolved_runtime_id = (runtime_id or "").strip()
        if not resolved_runtime_id:
            return

        base_url = self._required_controller_base_url()
        timeout = self._controller_timeout()

        try:
            headers = mint_controller_disconnect_bearer_header(
                user_id=user_id,
                runtime_id=resolved_runtime_id,
            )
        except WhatsAppControllerAuthError as exc:
            raise RuntimeError(str(exc)) from exc

        url = f"{base_url}/v1/whatsapp/runtimes/{resolved_runtime_id}/disconnect"
        payload = {
            "user_id": user_id,
            "stop_reason": "user_disconnect",
        }

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(url, headers=headers, json=payload)
        except httpx.RequestError as exc:
            raise RuntimeError(f"WhatsApp session controller is unavailable: {exc}") from exc

        detail = f"Failed to disconnect WhatsApp runtime (HTTP {response.status_code})"
        try:
            parsed = response.json()
            if isinstance(parsed, dict):
                message = parsed.get("message") or parsed.get("detail")
                if isinstance(message, str) and message.strip():
                    detail = message.strip()
        except Exception:
            pass

        if response.status_code not in {200, 202, 204, 404}:
            raise RuntimeError(detail)

    async def touch(
        self,
        *,
        user_id: str,
        user_jwt: str,
        runtime_id: str | None = None,
    ) -> None:
        _ = user_jwt
        resolved_runtime_id = (runtime_id or "").strip()
        if not resolved_runtime_id:
            return

        base_url = self._required_controller_base_url()
        timeout = self._controller_timeout()
        try:
            headers = mint_controller_touch_bearer_header(
                user_id=user_id,
                runtime_id=resolved_runtime_id,
            )
        except WhatsAppControllerAuthError as exc:
            raise RuntimeError(str(exc)) from exc

        payload = {
            "user_id": user_id,
            "ttl_seconds": self.LEASE_TTL_SECONDS,
        }
        url = f"{base_url}/v1/whatsapp/runtimes/{resolved_runtime_id}/touch"
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(url, headers=headers, json=payload)
        except httpx.RequestError as exc:
            raise RuntimeError(f"WhatsApp session controller is unavailable: {exc}") from exc

        detail = f"Failed to refresh WhatsApp runtime lease (HTTP {response.status_code})"
        try:
            parsed = response.json()
            if isinstance(parsed, dict):
                message = parsed.get("message") or parsed.get("detail")
                if isinstance(message, str) and message.strip():
                    detail = message.strip()
        except Exception:
            pass

        if response.status_code not in {200, 202, 204, 404}:
            raise RuntimeError(detail)
