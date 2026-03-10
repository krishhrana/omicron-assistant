from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx

from whatsapp_session_controller.core.settings import WhatsAppSessionControllerSettings
from whatsapp_session_controller.orchestration.base import OrchestratedRuntime
from whatsapp_session_controller.services.runtime_types import RuntimeState

logger = logging.getLogger(__name__)


class ECSRuntimeOrchestrator:
    """ECS-backed runtime orchestration adapter."""

    TASK_IP_WAIT_TIMEOUT_SECONDS = 30.0
    TASK_IP_WAIT_POLL_INTERVAL_SECONDS = 1.0
    RUNTIME_HOT_STORE_ROOT = "/app/whatsapp-hot-store"
    RUNTIME_PERSISTENT_STORE_ROOT = "/app/whatsapp-bridge/store"
    RUNTIME_MESSAGE_STORE_MODE = "hot_local_sync"
    RUNTIME_MESSAGE_STORE_SYNC_INTERVAL_SECONDS = 5
    BRIDGE_CONTAINER_NAME = "whatsapp-bridge"
    MCP_CONTAINER_NAME = "whatsapp-mcp-server"

    def __init__(self, *, settings: WhatsAppSessionControllerSettings) -> None:
        """Store controller settings and prepare lazy ECS client initialization."""
        self._settings = settings
        self._ecs_client: Any | None = None

    @staticmethod
    def _safe_user_label(user_id: str) -> str:
        normalized = user_id.strip()
        if not normalized:
            return "unknown"
        if len(normalized) <= 6:
            return normalized
        return f"{normalized[:3]}...{normalized[-2:]}"

    def _require_ecs_client(self) -> Any:
        """Return a cached boto3 ECS client, creating it on first use."""
        if self._ecs_client is not None:
            return self._ecs_client

        try:
            import boto3
        except Exception as exc:  # pragma: no cover - import path differs by env
            raise RuntimeError(
                "boto3 is required for ECS runtime orchestration. Install boto3 in the backend environment."
            ) from exc

        profile_name = (self._settings.aws_profile or "").strip() or None
        try:
            if profile_name:
                session = boto3.session.Session(
                    profile_name=profile_name,
                    region_name=self._settings.aws_region,
                )
                self._ecs_client = session.client("ecs")
            else:
                self._ecs_client = boto3.client(
                    "ecs",
                    region_name=self._settings.aws_region,
                )
        except Exception as exc:  # pragma: no cover - depends on local AWS setup
            profile_hint = f" using profile '{profile_name}'" if profile_name else ""
            raise RuntimeError(
                f"Failed to initialize boto3 ECS client{profile_hint}. "
                "Verify AWS credentials and region configuration."
            ) from exc

        logger.info(
            "whatsapp.ecs.client.initialized region=%s profile=%s cluster=%s task_definition=%s",
            self._settings.aws_region,
            profile_name,
            self._settings.ecs_cluster,
            self._settings.ecs_task_definition,
        )
        return self._ecs_client

    @staticmethod
    def _task_id(task_arn: str) -> str:
        """Extract the task ID from a full ECS task ARN."""
        return task_arn.rsplit("/", 1)[-1]

    @staticmethod
    def _safe_format(template: str, context: dict[str, str]) -> str:
        """Format a URL template and surface missing placeholders clearly."""
        try:
            return template.format_map(context)
        except KeyError as exc:
            missing = str(exc).strip("'")
            raise RuntimeError(
                f"Missing template key '{missing}' while resolving runtime endpoint URL."
            ) from exc

    def _started_by(self, runtime_id: str) -> str:
        """Build the deterministic ECS `startedBy` value for a runtime."""
        prefix = (self._settings.ecs_started_by_prefix or "").strip()
        raw = f"{prefix}{runtime_id}"
        return raw[:128]

    def _runtime_env_overrides(self, *, user_id: str) -> list[dict[str, str]]:
        raw_scope = user_id.strip().lower()
        if not raw_scope:
            raise RuntimeError("user_id is required for runtime environment overrides.")
        try:
            user_scope = str(uuid.UUID(raw_scope)).lower()
        except ValueError as exc:
            raise RuntimeError(
                f"user_id must be a UUID for runtime scope injection. Received: {user_id!r}"
            ) from exc
        return [
            {"name": "WHATSAPP_RUNTIME_USER_SCOPE", "value": user_scope},
            {"name": "WHATSAPP_RUNTIME_ECS_MODE", "value": "true"},
            {"name": "WHATSAPP_MESSAGE_STORE_MODE", "value": self.RUNTIME_MESSAGE_STORE_MODE},
            {
                "name": "WHATSAPP_MESSAGE_STORE_PERSISTENT_DIR",
                "value": self.RUNTIME_PERSISTENT_STORE_ROOT,
            },
            {
                "name": "WHATSAPP_MESSAGE_STORE_HOT_DIR",
                "value": self.RUNTIME_HOT_STORE_ROOT,
            },
            {
                "name": "WHATSAPP_MESSAGE_STORE_SYNC_INTERVAL_SECONDS",
                "value": str(self.RUNTIME_MESSAGE_STORE_SYNC_INTERVAL_SECONDS),
            },
        ]

    def _container_overrides(self, *, user_id: str) -> list[dict[str, Any]]:
        env_overrides = self._runtime_env_overrides(user_id=user_id)
        return [
            {"name": self.BRIDGE_CONTAINER_NAME, "environment": env_overrides},
            {"name": self.MCP_CONTAINER_NAME, "environment": env_overrides},
        ]

    async def _list_task_arns(self, *, runtime_id: str, desired_status: str) -> list[str]:
        """List ECS task ARNs for the runtime filtered by desired status."""
        ecs = self._require_ecs_client()
        response = await asyncio.to_thread(
            ecs.list_tasks,
            cluster=self._settings.ecs_cluster,
            startedBy=self._started_by(runtime_id),
            desiredStatus=desired_status,
        )
        task_arns = response.get("taskArns") or []
        normalized_arns = [str(arn) for arn in task_arns if isinstance(arn, str) and arn.strip()]
        logger.info(
            "whatsapp.ecs.tasks.list runtime_id=%s desired_status=%s task_count=%s",
            runtime_id,
            desired_status,
            len(normalized_arns),
        )
        return normalized_arns

    async def _describe_tasks(self, *, task_arns: list[str]) -> list[dict[str, Any]]:
        """Describe ECS tasks and return only dictionary task objects."""
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
        """Pick the best candidate task preferring RUNNING then PENDING."""
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
        """Find an existing ECS task for the runtime, if one exists."""
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
        """Build normalized kwargs for `ecs.run_task`."""
        kwargs: dict[str, Any] = {
            "cluster": self._settings.ecs_cluster,
            "taskDefinition": self._settings.ecs_task_definition,
            "count": 1,
            "enableExecuteCommand": True,
            "overrides": {"containerOverrides": self._container_overrides(user_id=user_id)},
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
                    "assignPublicIp": "DISABLED",
                }
            }

        return kwargs

    async def _run_task(self, *, user_id: str, runtime_id: str, generation: int) -> dict[str, Any]:
        """Launch a new ECS task and return the created task payload."""
        ecs = self._require_ecs_client()
        kwargs = self._run_task_kwargs(user_id=user_id, runtime_id=runtime_id, generation=generation)
        logger.info(
            "whatsapp.ecs.task.run.request user=%s runtime_id=%s generation=%s cluster=%s task_definition=%s launch_type=%s capacity_provider=%s execute_command=%s subnet_count=%s security_group_count=%s",
            self._safe_user_label(user_id),
            runtime_id,
            generation,
            self._settings.ecs_cluster,
            self._settings.ecs_task_definition,
            kwargs.get("launchType"),
            self._settings.ecs_capacity_provider,
            kwargs.get("enableExecuteCommand"),
            len(self._settings.ecs_subnets),
            len(self._settings.ecs_security_groups),
        )
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
            logger.warning(
                "whatsapp.ecs.task.run.failed runtime_id=%s generation=%s details=%s",
                runtime_id,
                generation,
                summary,
            )
            raise RuntimeError(f"ECS run_task failed for runtime {runtime_id}: {summary}")

        tasks = response.get("tasks") or []
        if not tasks or not isinstance(tasks[0], dict):
            raise RuntimeError(f"ECS run_task returned no task for runtime {runtime_id}.")
        task_arn = str(tasks[0].get("taskArn") or "").strip()
        logger.info(
            "whatsapp.ecs.task.run.created runtime_id=%s generation=%s task_arn=%s",
            runtime_id,
            generation,
            task_arn or None,
        )
        return tasks[0]

    @staticmethod
    def _extract_task_ips(task: dict[str, Any]) -> tuple[str | None, str | None]:
        """Extract private/public IPv4 addresses from ECS task metadata."""
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

    def _requires_task_private_ip(self) -> bool:
        """Return whether endpoint resolution depends on task private IP."""
        bridge_template = (self._settings.runtime_bridge_base_url_template or "").strip()
        mcp_template = (self._settings.runtime_mcp_url_template or "").strip()
        return not (bridge_template and mcp_template)

    async def _wait_for_task_private_ip(
        self,
        *,
        runtime_id: str,
        task_arn: str,
        initial_task: dict[str, Any],
    ) -> dict[str, Any]:
        """Poll ECS task metadata until a private IP becomes available."""
        latest_task = initial_task
        private_ip, _ = self._extract_task_ips(latest_task)
        if private_ip:
            return latest_task

        timeout_seconds = max(0.0, float(self.TASK_IP_WAIT_TIMEOUT_SECONDS))
        poll_interval = max(0.1, float(self.TASK_IP_WAIT_POLL_INTERVAL_SECONDS))
        deadline = asyncio.get_running_loop().time() + timeout_seconds
        attempts = 0

        while asyncio.get_running_loop().time() < deadline:
            attempts += 1
            described = await self._describe_tasks(task_arns=[task_arn])
            if described:
                latest_task = described[0]
            status = str(latest_task.get("lastStatus") or "").strip().upper()
            stop_reason = str(latest_task.get("stoppedReason") or "").strip()
            private_ip, _ = self._extract_task_ips(latest_task)

            if private_ip:
                logger.info(
                    "whatsapp.ecs.runtime.private_ip.ready runtime_id=%s task_arn=%s private_ip=%s attempts=%s",
                    runtime_id,
                    task_arn,
                    private_ip,
                    attempts,
                )
                return latest_task

            if status == "STOPPED":
                detail = stop_reason or "task stopped before network initialization"
                raise RuntimeError(
                    f"ECS task stopped before private IP was assigned for runtime {runtime_id}: {detail}"
                )

            logger.info(
                "whatsapp.ecs.runtime.private_ip.waiting runtime_id=%s task_arn=%s task_status=%s attempts=%s",
                runtime_id,
                task_arn,
                status or None,
                attempts,
            )
            await asyncio.sleep(poll_interval)

        status = str(latest_task.get("lastStatus") or "").strip().upper()
        raise RuntimeError(
            "Timed out waiting for ECS task private IP while resolving runtime endpoints "
            f"(runtime_id={runtime_id}, task_arn={task_arn}, last_status={status or 'UNKNOWN'})."
        )

    @staticmethod
    def _join_probe_url(base_url: str, probe_path: str) -> str:
        """Construct a health probe URL from runtime base URL and path."""
        split = urlsplit(base_url.rstrip("/"))
        path = probe_path if probe_path.startswith("/") else f"/{probe_path}"
        return urlunsplit((split.scheme, split.netloc, path, "", ""))

    async def _probe_url(self, url: str) -> bool:
        """Run an HTTP GET probe and return whether the endpoint is healthy."""
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
        """Resolve bridge and MCP endpoint URLs for a runtime task."""
        task_arn = str(task.get("taskArn") or "").strip()
        if not task_arn:
            raise RuntimeError(f"ECS taskArn missing while resolving endpoints for {runtime_id}.")
        private_ip, _ = self._extract_task_ips(task)
        task_id = self._task_id(task_arn)
        context = {
            "runtime_id": runtime_id,
            "task_arn": task_arn,
            "task_id": task_id,
            "task_private_ip": private_ip or "",
            "bridge_port": str(self._settings.runtime_bridge_port),
            "mcp_port": str(self._settings.runtime_mcp_port),
            "mcp_path": self._settings.runtime_mcp_path,
        }

        bridge_template = (self._settings.runtime_bridge_base_url_template or "").strip()
        mcp_template = (self._settings.runtime_mcp_url_template or "").strip()
        if bridge_template and mcp_template:
            bridge_base_url = self._safe_format(bridge_template, context)
            mcp_url = self._safe_format(mcp_template, context)
            logger.info(
                "whatsapp.ecs.runtime.endpoints runtime_id=%s task_id=%s task_private_ip=%s bridge_base_url=%s mcp_url=%s source=template",
                runtime_id,
                task_id,
                private_ip,
                bridge_base_url,
                mcp_url,
            )
            return bridge_base_url, mcp_url

        host = private_ip
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
        logger.info(
            "whatsapp.ecs.runtime.endpoints runtime_id=%s task_id=%s task_private_ip=%s bridge_base_url=%s mcp_url=%s source=task_ip",
            runtime_id,
            task_id,
            private_ip,
            bridge_base_url,
            mcp_url,
        )
        return bridge_base_url, mcp_url

    async def get_or_create_runtime(
        self,
        *,
        user_id: str,
        runtime_id: str,
        generation: int,
    ) -> OrchestratedRuntime:
        """Reuse an existing task or start one, then return resolved endpoints."""
        logger.info(
            "whatsapp.ecs.runtime.get_or_create.begin user=%s runtime_id=%s generation=%s",
            self._safe_user_label(user_id),
            runtime_id,
            generation,
        )
        task = await self._find_existing_task(runtime_id=runtime_id)
        if task is None:
            logger.info(
                "whatsapp.ecs.runtime.get_or_create.no_existing_task runtime_id=%s",
                runtime_id,
            )
            task = await self._run_task(user_id=user_id, runtime_id=runtime_id, generation=generation)
            task_arn = str(task.get("taskArn") or "").strip()
            if task_arn:
                described = await self._describe_tasks(task_arns=[task_arn])
                if described:
                    task = described[0]
        else:
            logger.info(
                "whatsapp.ecs.runtime.get_or_create.reusing_task runtime_id=%s task_arn=%s task_status=%s",
                runtime_id,
                str(task.get("taskArn") or "").strip() or None,
                str(task.get("lastStatus") or "").strip() or None,
            )

        task_arn = str(task.get("taskArn") or "").strip()
        if task_arn and self._requires_task_private_ip():
            task = await self._wait_for_task_private_ip(
                runtime_id=runtime_id,
                task_arn=task_arn,
                initial_task=task,
            )
        bridge_base_url, mcp_url = self._resolve_runtime_endpoints(runtime_id=runtime_id, task=task)
        logger.info(
            "whatsapp.ecs.runtime.get_or_create.complete runtime_id=%s task_arn=%s bridge_base_url=%s mcp_url=%s",
            runtime_id,
            task_arn or None,
            bridge_base_url,
            mcp_url,
        )
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
        """Stop all ECS tasks associated with the runtime."""
        user_label = self._safe_user_label(user_id)
        _ = generation
        ecs = self._require_ecs_client()
        logger.info(
            "whatsapp.ecs.runtime.disconnect.begin user=%s runtime_id=%s",
            user_label,
            runtime_id,
        )

        task_arns = await self._list_task_arns(runtime_id=runtime_id, desired_status="RUNNING")
        task_arns.extend(await self._list_task_arns(runtime_id=runtime_id, desired_status="PENDING"))
        unique_task_arns = list(dict.fromkeys(task_arns))
        if not unique_task_arns:
            logger.info(
                "whatsapp.ecs.runtime.disconnect.no_tasks user=%s runtime_id=%s",
                user_label,
                runtime_id,
            )
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
            logger.warning(
                "whatsapp.ecs.runtime.disconnect.partial_failure user=%s runtime_id=%s errors=%s",
                user_label,
                runtime_id,
                errors,
            )
            raise RuntimeError("Failed to stop one or more ECS tasks: " + "; ".join(errors))
        logger.info(
            "whatsapp.ecs.runtime.disconnect.complete user=%s runtime_id=%s task_count=%s",
            user_label,
            runtime_id,
            len(unique_task_arns),
        )

    async def probe_runtime(
        self,
        *,
        runtime: OrchestratedRuntime,
    ) -> RuntimeState:
        """Probe bridge and MCP health endpoints and map to runtime state."""
        if not self._settings.runtime_health_probe_enabled:
            logger.info(
                "whatsapp.ecs.runtime.probe.skipped runtime_id=%s reason=health_probe_disabled",
                runtime.runtime_id,
            )
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
        logger.info(
            "whatsapp.ecs.runtime.probe.result runtime_id=%s bridge_probe_url=%s bridge_ok=%s mcp_probe_url=%s mcp_ok=%s",
            runtime.runtime_id,
            bridge_probe_url,
            bridge_ok,
            mcp_probe_url,
            mcp_ok,
        )
        return "ready" if (bridge_ok and mcp_ok) else "degraded"
