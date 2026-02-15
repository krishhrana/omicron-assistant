from __future__ import annotations

import asyncio
import time
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field
import jwt

from browser_session_controller.auth import ApiAuthContext, RunnerAuthContext, require_api_auth, require_runner_auth
from browser_session_controller.k8s import (
    delete_runner_resources,
    ensure_runner_pod,
    ensure_runner_service,
    wait_for_pod_ready,
)
from browser_session_controller.settings import get_settings
from browser_session_controller.supabase_admin import create_supabase_admin_client


def _iso_z(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


class GetOrCreateRequest(BaseModel):
    user_id: str
    session_id: str = Field(description="Supabase chat_sessions.id (UUID)")
    ttl_seconds: int | None = None


class GetOrCreateResponse(BaseModel):
    session_id: str
    mcp_url: str
    expires_at: str
    status: str


class HeartbeatRequest(BaseModel):
    ttl_seconds: int | None = None


app = FastAPI(title="Browser Session Controller", version="0.1.0")


async def _select_browser_session_row(*, user_id: str, chat_session_id: str) -> dict | None:
    client = await create_supabase_admin_client()
    try:
        resp = await (
            client.table("browser_sessions")
            .select("*")
            .eq("user_id", user_id)
            .eq("chat_session_id", chat_session_id)
            .maybe_single()
            .execute()
        )
        return resp.data if resp else None
    finally:
        await client.postgrest.aclose()


def _mint_runner_broker_token(*, user_id: str, session_id: str) -> str:
    settings = get_settings()
    now = int(time.time())
    return jwt.encode(
        {
            "aud": settings.runner_broker_jwt_audience,
            "iat": now,
            "exp": now + 300,
            "session_id": session_id,
            "user_id": user_id,
        },
        settings.runner_broker_jwt_secret,
        algorithm="HS256",
    )


@app.post("/internal/browser-sessions/get-or-create", response_model=GetOrCreateResponse)
async def get_or_create_browser_session(
    req: GetOrCreateRequest,
    _: ApiAuthContext = Depends(require_api_auth),
) -> GetOrCreateResponse:
    settings = get_settings()
    ttl = req.ttl_seconds or settings.ttl_seconds_default
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(seconds=ttl)
    now_iso = _iso_z(now)

    namespace = settings.runner_namespace
    pod_name = f"pw-mcp-{req.session_id}"
    service_name = f"pw-mcp-{req.session_id}"
    mcp_url = f"http://{service_name}.{namespace}.svc.cluster.local:{settings.runner_port}/mcp"
    artifacts_prefix = (
        f"{settings.artifacts_s3_prefix_base}/{req.session_id}/" if settings.artifacts_s3_bucket else None
    )

    claim_id = str(uuid.uuid4())
    stale_cutoff = _iso_z(now - timedelta(seconds=settings.starting_stale_seconds))

    client = await create_supabase_admin_client()
    try:
        # Check for an existing, still-valid ready session.
        row_resp = await (
            client.table("browser_sessions")
            .select("*")
            .eq("user_id", req.user_id)
            .eq("chat_session_id", req.session_id)
            .maybe_single()
            .execute()
        )
        row = row_resp.data if row_resp else None
        if isinstance(row, dict):
            status = row.get("status")
            existing_expires_at = row.get("expires_at")
            if status == "ready" and existing_expires_at and str(existing_expires_at) > now_iso and row.get("mcp_url"):
                await (
                    client.table("browser_sessions")
                    .update({"expires_at": _iso_z(expires_at), "last_used_at": now_iso})
                    .eq("user_id", req.user_id)
                    .eq("chat_session_id", req.session_id)
                    .execute()
                )
                return GetOrCreateResponse(
                    session_id=req.session_id,
                    mcp_url=str(row["mcp_url"]),
                    expires_at=_iso_z(expires_at),
                    status="ready",
                )

        claimed = False
        if not isinstance(row, dict):
            # Create a new row and claim provisioning. If it races, we'll fall back to polling.
            try:
                insert_resp = await (
                    client.table("browser_sessions")
                    .insert(
                        {
                            "user_id": req.user_id,
                            "chat_session_id": req.session_id,
                            "status": "starting",
                            "claim_id": claim_id,
                            "namespace": namespace,
                            "pod_name": pod_name,
                            "service_name": service_name,
                            "mcp_url": mcp_url,
                            "artifacts_s3_prefix": artifacts_prefix,
                            "expires_at": _iso_z(expires_at),
                            "last_used_at": now_iso,
                        }
                    )
                    .execute()
                )
                inserted = insert_resp.data if insert_resp else None
                if isinstance(inserted, list) and inserted:
                    row = inserted[0]
                else:
                    row = inserted
                claimed = True
            except Exception:
                row = await _select_browser_session_row(user_id=req.user_id, chat_session_id=req.session_id)

        if not claimed:
            # Attempt takeover if expired/ended/error or stale 'starting'.
            takeover_filters = ",".join(
                [
                    f"expires_at.lt.{now_iso}",
                    "status.in.(ended,error)",
                    f"and(status.eq.starting,updated_at.lt.{stale_cutoff})",
                ]
            )
            update_resp = await (
                client.table("browser_sessions")
                .update(
                    {
                        "status": "starting",
                        "claim_id": claim_id,
                        "namespace": namespace,
                        "pod_name": pod_name,
                        "service_name": service_name,
                        "mcp_url": mcp_url,
                        "artifacts_s3_prefix": artifacts_prefix,
                        "expires_at": _iso_z(expires_at),
                        "last_used_at": now_iso,
                    }
                )
                .eq("user_id", req.user_id)
                .eq("chat_session_id", req.session_id)
                .or_(takeover_filters)
                .execute()
            )
            updated = update_resp.data if update_resp else None
            if isinstance(updated, list) and updated:
                claimed = True
            elif isinstance(updated, dict):
                claimed = True

        if not claimed:
            # Another controller (or previous attempt) is starting it. Poll briefly for ready.
            deadline = time.time() + 30
            while time.time() < deadline:
                row = await _select_browser_session_row(user_id=req.user_id, chat_session_id=req.session_id)
                if row and row.get("status") == "ready" and row.get("mcp_url"):
                    return GetOrCreateResponse(
                        session_id=req.session_id,
                        mcp_url=str(row["mcp_url"]),
                        expires_at=str(row.get("expires_at") or _iso_z(expires_at)),
                        status="ready",
                    )
                await asyncio.sleep(1)
            raise HTTPException(status_code=409, detail="Browser session is starting")

        # We own provisioning for this session.
        runner_token = _mint_runner_broker_token(user_id=req.user_id, session_id=req.session_id)
        selector = {"app": "pw-mcp-runner", "session": pod_name}
        await asyncio.to_thread(
            ensure_runner_service,
            namespace=namespace,
            service_name=service_name,
            port=settings.runner_port,
            selector=selector,
        )
        await asyncio.to_thread(
            ensure_runner_pod,
            namespace=namespace,
            pod_name=pod_name,
            image=settings.runner_image,
            service_account_name=settings.runner_service_account_name,
            port=settings.runner_port,
            controller_internal_url=settings.controller_internal_url,
            runner_broker_token=runner_token,
            artifacts_s3_bucket=settings.artifacts_s3_bucket,
            artifacts_s3_prefix=artifacts_prefix,
        )
        await asyncio.to_thread(
            wait_for_pod_ready,
            namespace=namespace,
            pod_name=pod_name,
            timeout_seconds=settings.startup_timeout_seconds,
        )

        await (
            client.table("browser_sessions")
            .update({"status": "ready", "expires_at": _iso_z(expires_at), "last_used_at": now_iso})
            .eq("user_id", req.user_id)
            .eq("chat_session_id", req.session_id)
            .eq("claim_id", claim_id)
            .execute()
        )

        return GetOrCreateResponse(
            session_id=req.session_id,
            mcp_url=mcp_url,
            expires_at=_iso_z(expires_at),
            status="ready",
        )
    finally:
        await client.postgrest.aclose()


@app.post("/internal/browser-sessions/{session_id}/heartbeat")
async def heartbeat_browser_session(
    session_id: str,
    req: HeartbeatRequest,
    _: ApiAuthContext = Depends(require_api_auth),
):
    settings = get_settings()
    ttl = req.ttl_seconds or settings.ttl_seconds_default
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(seconds=ttl)
    now_iso = _iso_z(now)

    client = await create_supabase_admin_client()
    try:
        await (
            client.table("browser_sessions")
            .update({"expires_at": _iso_z(expires_at), "last_used_at": now_iso})
            .eq("chat_session_id", session_id)
            .execute()
        )
    finally:
        await client.postgrest.aclose()
    return {"ok": True}


@app.delete("/internal/browser-sessions/{session_id}")
async def delete_browser_session(
    session_id: str,
    _: ApiAuthContext = Depends(require_api_auth),
):
    settings = get_settings()
    now = datetime.now(timezone.utc)
    now_iso = _iso_z(now)

    client = await create_supabase_admin_client()
    try:
        resp = await (
            client.table("browser_sessions")
            .select("*")
            .eq("chat_session_id", session_id)
            .maybe_single()
            .execute()
        )
        row = resp.data if resp else None
        if not isinstance(row, dict):
            return {"ok": True}

        namespace = row.get("namespace") or settings.runner_namespace
        pod_name = row.get("pod_name") or f"pw-mcp-{session_id}"
        service_name = row.get("service_name") or f"pw-mcp-{session_id}"
        await asyncio.to_thread(
            delete_runner_resources,
            namespace=namespace,
            pod_name=pod_name,
            service_name=service_name,
        )
        await (
            client.table("browser_sessions")
            .update({"status": "ended", "expires_at": now_iso})
            .eq("chat_session_id", session_id)
            .execute()
        )
    finally:
        await client.postgrest.aclose()
    return {"ok": True}


@app.post("/internal/runner-secrets", response_class=PlainTextResponse)
async def runner_secrets(
    runner_ctx: RunnerAuthContext = Depends(require_runner_auth),
):
    settings = get_settings()
    secret_name = f"{settings.vault_secret_prefix}{runner_ctx.user_id}"

    client = await create_supabase_admin_client()
    try:
        session_resp = await (
            client.table("browser_sessions")
            .select("id, status")
            .eq("user_id", runner_ctx.user_id)
            .eq("chat_session_id", runner_ctx.session_id)
            .maybe_single()
            .execute()
        )
        session_row = session_resp.data if session_resp else None
        if not isinstance(session_row, dict) or session_row.get("status") not in {"starting", "ready"}:
            raise HTTPException(status_code=404, detail="Browser session not found")

        resp = await client.rpc("get_vault_secret", {"secret_name": secret_name}).execute()
        secret = resp.data if resp else None
    finally:
        await client.postgrest.aclose()

    if not secret:
        raise HTTPException(status_code=404, detail=f"Vault secret not found: {secret_name}")

    # Vault secret should be a dotenv-formatted string compatible with @playwright/mcp --secrets.
    return str(secret)


async def _reaper_loop() -> None:
    settings = get_settings()
    while True:
        await asyncio.sleep(settings.reaper_interval_seconds)
        now = datetime.now(timezone.utc)
        now_iso = _iso_z(now)

        client = await create_supabase_admin_client()
        try:
            resp = await (
                client.table("browser_sessions")
                .select("*")
                .lt("expires_at", now_iso)
                .in_("status", ["starting", "ready"])
                .limit(50)
                .execute()
            )
            rows = resp.data if resp else []
            if not isinstance(rows, list) or not rows:
                continue
            for row in rows:
                try:
                    session_id = row.get("chat_session_id")
                    namespace = row.get("namespace") or settings.runner_namespace
                    pod_name = row.get("pod_name") or f"pw-mcp-{session_id}"
                    service_name = row.get("service_name") or f"pw-mcp-{session_id}"
                    await asyncio.to_thread(
                        delete_runner_resources,
                        namespace=namespace,
                        pod_name=pod_name,
                        service_name=service_name,
                    )
                    await (
                        client.table("browser_sessions")
                        .update({"status": "ended", "expires_at": now_iso})
                        .eq("id", row.get("id"))
                        .execute()
                    )
                except Exception as exc:
                    await (
                        client.table("browser_sessions")
                        .update({"status": "error"})
                        .eq("id", row.get("id"))
                        .execute()
                    )
                    print(f"reaper failed for browser_session={row.get('id')}: {exc}")
        finally:
            await client.postgrest.aclose()


@app.on_event("startup")
async def _start_reaper() -> None:
    asyncio.create_task(_reaper_loop())
