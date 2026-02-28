from __future__ import annotations

import asyncio
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx

from whatsapp_session_controller.core.settings import WhatsAppSessionControllerSettings
from whatsapp_session_controller.orchestration.base import OrchestratedRuntime
from whatsapp_session_controller.services.runtime_types import RuntimeState


class ECSRuntimeOrchestrator:
    """ECS-backed runtime orchestration adapter."""

    def __init__(self, *, settings: WhatsAppSessionControllerSettings) -> None:
        self._settings = settings
        self._ecs_client: Any | None = None

    def _require_ecs_client(self) -> Any:
        if self._ecs_client is not None:
            return self._ecs_client

        try:
            import boto3
        except Exception as exc:  # pragma: no cover - import path differs by env
            raise RuntimeError(
                "boto3 is required for ECS runtime orchestration. Install boto3 in the backend environment."
            ) from exc

        self._ecs_client = boto3.client(
            "ecs",
            region_name=self._settings.aws_region,
        )
        return self._ecs_client

    @staticmethod
    def _task_id(task_arn: str) -> str:
        return task_arn.rsplit("/", 1)[-1]

    @staticmethod
    def _safe_format(template: str, context: dict[str, str]) -> str:
        try:
            return template.format_map(context)
        except KeyError as exc:
            missing = str(exc).strip("'")
            raise RuntimeError(
                f"Missing template key '{missing}' while resolving runtime endpoint URL."
            ) from exc

    def _started_by(self, runtime_id: str) -> str:
        prefix = (self._settings.ecs_started_by_prefix or "").strip()
        raw = f"{prefix}{runtime_id}"
        return raw[:128]

    async def _list_task_arns(self, *, runtime_id: str, desired_status: str) -> list[str]:
        ecs = self._require_ecs_client()
        response = await asyncio.to_thread(
            ecs.list_tasks,
            cluster=self._settings.ecs_cluster,
            startedBy=self._started_by(runtime_id),
            desiredStatus=desired_status,
        )
        task_arns = response.get("taskArns") or []
        return [str(arn) for arn in task_arns if isinstance(arn, str) and arn.strip()]

    async def _describe_tasks(self, *, task_arns: list[str]) -> list[dict[str, Any]]:
        if not task_arns:
            return []
        ecs = self._require_ecs_client()
        response = await asyncio.to_thread(
            ecs.describe_tasks,
            cluster=self._settings.ecs_cluster,
            tasks=task_arns,
        )
        tasks = response.get("tasks") or []
        return [task for task in tasks if isinstance(task, dict)]

    @staticmethod
    def _pick_active_task(tasks: list[dict[str, Any]]) -> dict[str, Any] | None:
        if not tasks:
            return None
        running = [task for task in tasks if str(task.get("lastStatus") or "").upper() == "RUNNING"]
        if running:
            return running[0]
        pending = [task for task in tasks if str(task.get("lastStatus") or "").upper() == "PENDING"]
        if pending:
            return pending[0]
        return tasks[0]

    async def _find_existing_task(self, *, runtime_id: str) -> dict[str, Any] | None:
        running_task_arns = await self._list_task_arns(runtime_id=runtime_id, desired_status="RUNNING")
        if running_task_arns:
            tasks = await self._describe_tasks(task_arns=running_task_arns)
            task = self._pick_active_task(tasks)
            if task is not None:
                return task

        pending_task_arns = await self._list_task_arns(runtime_id=runtime_id, desired_status="PENDING")
        if pending_task_arns:
            tasks = await self._describe_tasks(task_arns=pending_task_arns)
            return self._pick_active_task(tasks)
        return None

    def _run_task_kwargs(self, *, user_id: str, runtime_id: str, generation: int) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "cluster": self._settings.ecs_cluster,
            "taskDefinition": self._settings.ecs_task_definition,
            "count": 1,
            "startedBy": self._started_by(runtime_id),
            "tags": [
                {"key": "service", "value": "whatsapp-runtime"},
                {"key": "user_id", "value": user_id},
                {"key": "runtime_id", "value": runtime_id},
                {"key": "generation", "value": str(generation)},
            ],
        }

        capacity_provider = (self._settings.ecs_capacity_provider or "").strip()
        if capacity_provider:
            kwargs["capacityProviderStrategy"] = [{"capacityProvider": capacity_provider, "weight": 1}]
        else:
            kwargs["launchType"] = self._settings.ecs_launch_type

        if self._settings.ecs_subnets:
            kwargs["networkConfiguration"] = {
                "awsvpcConfiguration": {
                    "subnets": self._settings.ecs_subnets,
                    "securityGroups": self._settings.ecs_security_groups,
                    "assignPublicIp": "ENABLED" if self._settings.ecs_assign_public_ip else "DISABLED",
                }
            }

        return kwargs

    async def _run_task(self, *, user_id: str, runtime_id: str, generation: int) -> dict[str, Any]:
        ecs = self._require_ecs_client()
        kwargs = self._run_task_kwargs(user_id=user_id, runtime_id=runtime_id, generation=generation)
        response = await asyncio.to_thread(ecs.run_task, **kwargs)
        failures = response.get("failures") or []
        if failures:
            messages: list[str] = []
            for item in failures:
                if not isinstance(item, dict):
                    continue
                reason = str(item.get("reason") or "").strip()
                arn = str(item.get("arn") or "").strip()
                detail = f"{reason} ({arn})" if arn else reason
                if detail:
                    messages.append(detail)
            summary = "; ".join(messages) if messages else "unknown failure"
            raise RuntimeError(f"ECS run_task failed for runtime {runtime_id}: {summary}")

        tasks = response.get("tasks") or []
        if not tasks or not isinstance(tasks[0], dict):
            raise RuntimeError(f"ECS run_task returned no task for runtime {runtime_id}.")
        return tasks[0]

    @staticmethod
    def _extract_task_ips(task: dict[str, Any]) -> tuple[str | None, str | None]:
        private_ip: str | None = None
        public_ip: str | None = None

        for attachment in task.get("attachments") or []:
            if not isinstance(attachment, dict):
                continue
            for detail in attachment.get("details") or []:
                if not isinstance(detail, dict):
                    continue
                name = str(detail.get("name") or "").strip().lower()
                value = str(detail.get("value") or "").strip()
                if not value:
                    continue
                if name in {"privateipv4address", "private_ipv4_address"} and private_ip is None:
                    private_ip = value
                if name in {"publicipv4address", "public_ipv4_address"} and public_ip is None:
                    public_ip = value

        for container in task.get("containers") or []:
            if not isinstance(container, dict):
                continue
            for interface in container.get("networkInterfaces") or []:
                if not isinstance(interface, dict):
                    continue
                private = str(interface.get("privateIpv4Address") or "").strip()
                if private and private_ip is None:
                    private_ip = private

        return private_ip, public_ip

    @staticmethod
    def _join_probe_url(base_url: str, probe_path: str) -> str:
        split = urlsplit(base_url.rstrip("/"))
        path = probe_path if probe_path.startswith("/") else f"/{probe_path}"
        return urlunsplit((split.scheme, split.netloc, path, "", ""))

    async def _probe_url(self, url: str) -> bool:
        timeout = max(0.1, float(self._settings.runtime_health_probe_timeout_seconds))
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.get(url)
            return 200 <= response.status_code < 300
        except Exception:
            return False

    def _resolve_runtime_endpoints(
        self,
        *,
        runtime_id: str,
        task: dict[str, Any],
    ) -> tuple[str, str]:
        task_arn = str(task.get("taskArn") or "").strip()
        if not task_arn:
            raise RuntimeError(f"ECS taskArn missing while resolving endpoints for {runtime_id}.")

        private_ip, public_ip = self._extract_task_ips(task)
        task_id = self._task_id(task_arn)
        context = {
            "runtime_id": runtime_id,
            "task_arn": task_arn,
            "task_id": task_id,
            "task_private_ip": private_ip or "",
            "task_public_ip": public_ip or "",
            "bridge_port": str(self._settings.runtime_bridge_port),
            "mcp_port": str(self._settings.runtime_mcp_port),
            "mcp_path": self._settings.runtime_mcp_path,
        }

        bridge_template = (self._settings.runtime_bridge_base_url_template or "").strip()
        mcp_template = (self._settings.runtime_mcp_url_template or "").strip()
        if bridge_template and mcp_template:
            return (
                self._safe_format(bridge_template, context),
                self._safe_format(mcp_template, context),
            )

        host = public_ip if (self._settings.ecs_assign_public_ip and public_ip) else private_ip
        if not host:
            raise RuntimeError(
                "Could not resolve ECS task IP for runtime endpoint construction. "
                "Configure runtime URL templates or awsvpc networking."
            )

        bridge_base_url = (
            f"{self._settings.runtime_endpoint_scheme}://{host}:{self._settings.runtime_bridge_port}"
        )
        mcp_url = (
            f"{self._settings.runtime_endpoint_scheme}://{host}:{self._settings.runtime_mcp_port}"
            f"{self._settings.runtime_mcp_path}"
        )
        return bridge_base_url, mcp_url

    async def get_or_create_runtime(
        self,
        *,
        user_id: str,
        runtime_id: str,
        generation: int,
    ) -> OrchestratedRuntime:
        task = await self._find_existing_task(runtime_id=runtime_id)
        if task is None:
            task = await self._run_task(user_id=user_id, runtime_id=runtime_id, generation=generation)
            task_arn = str(task.get("taskArn") or "").strip()
            if task_arn:
                described = await self._describe_tasks(task_arns=[task_arn])
                if described:
                    task = described[0]

        task_arn = str(task.get("taskArn") or "").strip()
        bridge_base_url, mcp_url = self._resolve_runtime_endpoints(runtime_id=runtime_id, task=task)
        return OrchestratedRuntime(
            runtime_id=runtime_id,
            bridge_base_url=bridge_base_url,
            mcp_url=mcp_url,
            task_arn=task_arn or None,
        )

    async def disconnect_runtime(
        self,
        *,
        user_id: str,
        runtime_id: str,
        generation: int,
    ) -> None:
        _ = user_id
        _ = generation
        ecs = self._require_ecs_client()

        task_arns = await self._list_task_arns(runtime_id=runtime_id, desired_status="RUNNING")
        task_arns.extend(await self._list_task_arns(runtime_id=runtime_id, desired_status="PENDING"))
        unique_task_arns = list(dict.fromkeys(task_arns))
        if not unique_task_arns:
            return

        errors: list[str] = []
        for task_arn in unique_task_arns:
            try:
                await asyncio.to_thread(
                    ecs.stop_task,
                    cluster=self._settings.ecs_cluster,
                    task=task_arn,
                    reason=f"runtime_disconnect:{runtime_id}",
                )
            except Exception as exc:
                errors.append(f"{task_arn}: {exc}")

        if errors:
            raise RuntimeError("Failed to stop one or more ECS tasks: " + "; ".join(errors))

    async def probe_runtime(
        self,
        *,
        runtime: OrchestratedRuntime,
    ) -> RuntimeState:
        if not self._settings.runtime_health_probe_enabled:
            return "ready"

        bridge_probe_url = self._join_probe_url(
            runtime.bridge_base_url,
            self._settings.runtime_bridge_health_path,
        )
        mcp_probe_url = self._join_probe_url(runtime.mcp_url, self._settings.runtime_mcp_health_path)

        bridge_ok, mcp_ok = await asyncio.gather(
            self._probe_url(bridge_probe_url),
            self._probe_url(mcp_probe_url),
        )
        return "ready" if (bridge_ok and mcp_ok) else "degraded"
