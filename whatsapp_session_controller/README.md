# WhatsApp Session Controller Service

Dedicated control-plane service for WhatsApp runtime lifecycle.

This service is responsible for:
- Issuing runtime leases per user.
- Creating/reusing/stopping WhatsApp runtimes.
- Resolving bridge and MCP endpoints.
- Persisting runtime lease state in a controller-owned table.
- Enforcing JWT auth + scope + user/runtime ownership.

It is designed to be called by BE (`ControllerWhatsAppSessionProvider`) and not exposed publicly.

## Status

Implemented:
- Phase 1: service skeleton
- Phase 2: auth + API validation
- Phase 3: durable lease/state store
- Phase 4: ECS orchestration adapter

Not implemented yet:
- Phase 5: reconciler/expiry worker loop
- Phase 6: full integration rollout and staging cutover steps

Plan source:
- `BE/plans/whatsapp_session_controller_service_plan.md`

## Service Layout

- `whatsapp_session_controller/main.py`: app factory + `/healthz`
- `whatsapp_session_controller/api/endpoints/runtimes.py`: lease/read/touch/disconnect APIs
- `whatsapp_session_controller/auth.py`: bearer JWT validation + scope enforcement
- `whatsapp_session_controller/services/runtime_manager.py`: lease orchestration + persistence logic
- `whatsapp_session_controller/services/runtime_lease_repository.py`: DB repository (service-role client)
- `whatsapp_session_controller/orchestration/`: runtime orchestrators
  - `ecs.py`: ECS implementation
  - `local.py`: local/dev implementation
- `app/db/table_schemas/controller_whatsapp_runtime_leases_schema.sql`: controller-owned runtime lease table schema

## Runtime Ownership Model

- Controller table is the source of truth for runtime infra state.
- BE does not read/write runtime lease DB rows directly.
- BE calls controller APIs (`lease`, `read`, `touch`, `disconnect`) only.

## Data Model

Table: `controller_whatsapp_runtime_leases`

Primary fields:
- `user_id` (PK)
- `runtime_id` (unique)
- `runtime_generation`
- `controller_state`
- `desired_state`
- `bridge_base_url`
- `mcp_url`
- `runtime_started_at`
- `hard_expires_at`
- `lease_expires_at`
- `last_touched_at`
- `last_error_code`
- `last_error_at`

Constraints include:
- `runtime_started_at <= hard_expires_at`
- `lease_expires_at <= hard_expires_at`

RLS:
- enabled with no policies (controller uses service role only).

## API Contract

Base prefix defaults to `/v1`.

### 1) Lease

`POST /v1/whatsapp/runtimes/lease`

Request:
```json
{
  "user_id": "uuid",
  "ttl_seconds": 600,
  "wait_for_ready_seconds": 15,
  "force_new": false,
  "client_request_id": "optional"
}
```

Response (`LeaseRuntimeResponse`):
```json
{
  "runtime_id": "wa_rt_...",
  "generation": 3,
  "state": "ready",
  "bridge_base_url": "http://...",
  "mcp_url": "http://.../mcp",
  "runtime_started_at": "2026-02-28T12:00:00+00:00",
  "hard_expires_at": "2026-02-28T13:30:00+00:00",
  "lease_expires_at": "2026-02-28T12:10:00+00:00",
  "poll_after_seconds": 2,
  "action": "created"
}
```

Notes:
- `state` can be `ready` or `degraded` for successful lease response.
- `wait_for_ready_seconds` is honored in manager probing loop.

### 2) Read

`GET /v1/whatsapp/runtimes/{runtime_id}?user_id=<uuid>`

Response (`RuntimeStatusResponse`) contains runtime metadata/state and endpoints.

### 3) Touch

`POST /v1/whatsapp/runtimes/{runtime_id}/touch`

Request:
```json
{
  "user_id": "uuid",
  "ttl_seconds": 600
}
```

Response:
```json
{
  "ok": true,
  "runtime_id": "wa_rt_...",
  "hard_expires_at": "...",
  "lease_expires_at": "..."
}
```

### 4) Disconnect

`POST /v1/whatsapp/runtimes/{runtime_id}/disconnect`

Request:
```json
{
  "user_id": "uuid",
  "stop_reason": "user_disconnect"
}
```

Response:
```json
{
  "ok": true,
  "runtime_id": "wa_rt_...",
  "state": "stopped"
}
```

## Auth and Authorization

Bearer JWT is required.

Validation:
- signature (`WHATSAPP_SESSION_CONTROLLER_JWT_SECRET`)
- `aud` (`WHATSAPP_SESSION_CONTROLLER_JWT_AUDIENCE`)
- `iss` (`WHATSAPP_SESSION_CONTROLLER_JWT_ISSUER`)
- required claims: `sub`, `iat`, `exp`, `user_id`

Scopes by endpoint:
- lease: `whatsapp:runtime:lease`
- read: `whatsapp:runtime:read`
- touch: `whatsapp:runtime:touch`
- disconnect: `whatsapp:runtime:disconnect`

Ownership checks:
- token `user_id` must equal request `user_id`
- if token includes `runtime_id`, it must equal path runtime ID

## Lease and Lifecycle Logic

- Sliding TTL is capped by `WHATSAPP_RUNTIME_SLIDING_TTL_SECONDS`.
- Hard max runtime lifetime is `WHATSAPP_RUNTIME_MAX_LIFETIME_SECONDS`.
- Effective lease expiry is `min(now + ttl, hard_expires_at)`.
- Reuse path:
  - reuse only if state in `{ready, degraded}` and not hard-expired
  - probe runtime health and refresh endpoints/state
- Create/rotate path:
  - allocate new runtime ID + increment generation
  - orchestrator ensures runtime exists
  - probe runtime and persist resolved endpoints/state
- Touch path:
  - if hard-expired, transition to `stopped` with `runtime_hard_expired`
  - else refresh lease and endpoint/state metadata
- Disconnect path:
  - orchestrator stop semantics first
  - persist `stopped` state

## Orchestration Providers

Configured via `WHATSAPP_RUNTIME_ORCHESTRATOR`:
- `ecs` (default)
- `local`

### ECS Provider

Implemented in `orchestration/ecs.py`.

Behavior:
- Finds existing tasks via `list_tasks(startedBy=...)`.
- Starts runtime via `run_task` when missing.
- Stops runtime via `stop_task` on disconnect.
- Probes bridge + MCP health URLs.
- Resolves endpoints from:
  - templates (if provided), or
  - ECS task private/public IP + configured ports/paths.

`startedBy` strategy:
- `WHATSAPP_CONTROLLER_ECS_STARTED_BY_PREFIX + runtime_id` (trimmed to ECS max length).

Template placeholders supported:
- `{runtime_id}`
- `{task_arn}`
- `{task_id}`
- `{task_private_ip}`
- `{bridge_port}`
- `{mcp_port}`
- `{mcp_path}`

### Local Provider

Implemented in `orchestration/local.py`.

Behavior:
- Builds runtime URLs from host template or localhost defaults.
- Optional health probes.
- No-op disconnect.

## Configuration

### Required (controller service)

- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`
- `WHATSAPP_SESSION_CONTROLLER_JWT_SECRET`
- `WHATSAPP_SESSION_CONTROLLER_JWT_AUDIENCE`
- `WHATSAPP_SESSION_CONTROLLER_JWT_ISSUER`

### Required when `WHATSAPP_RUNTIME_ORCHESTRATOR=ecs`

- `WHATSAPP_CONTROLLER_AWS_REGION`
- `WHATSAPP_CONTROLLER_ECS_CLUSTER`
- `WHATSAPP_CONTROLLER_ECS_TASK_DEFINITION`

### Optional for local AWS profile usage

- `WHATSAPP_CONTROLLER_AWS_PROFILE` (for example: `omicron-local`)

### Core runtime knobs

- `WHATSAPP_RUNTIME_ORCHESTRATOR` (`ecs` or `local`)
- `WHATSAPP_RUNTIME_SLIDING_TTL_SECONDS` (default `600`)
- `WHATSAPP_RUNTIME_MAX_LIFETIME_SECONDS` (default `5400`)
- `WHATSAPP_RUNTIME_HEALTH_PROBE_ENABLED` (default `true`)
- `WHATSAPP_RUNTIME_HEALTH_PROBE_TIMEOUT_SECONDS` (default `2`)
- `WHATSAPP_RUNTIME_BRIDGE_HEALTH_PATH` (default `/health`)
- `WHATSAPP_RUNTIME_MCP_HEALTH_PATH` (default `/health`)

### Endpoint resolution knobs

- `WHATSAPP_RUNTIME_ENDPOINT_SCHEME` (`http`/`https`)
- `WHATSAPP_RUNTIME_BRIDGE_PORT` (default `8080`)
- `WHATSAPP_RUNTIME_MCP_PORT` (default `8000`)
- `WHATSAPP_RUNTIME_MCP_PATH` (default `/mcp`)
- `WHATSAPP_RUNTIME_ENDPOINT_HOST_TEMPLATE` (used by local provider)
- `WHATSAPP_RUNTIME_BRIDGE_BASE_URL_TEMPLATE` (optional)
- `WHATSAPP_RUNTIME_MCP_URL_TEMPLATE` (optional)

### ECS network/placement knobs

- `WHATSAPP_CONTROLLER_ECS_CAPACITY_PROVIDER`
- `WHATSAPP_CONTROLLER_ECS_SUBNETS`
- `WHATSAPP_CONTROLLER_ECS_SECURITY_GROUPS`
- `WHATSAPP_CONTROLLER_ECS_ASSIGN_PUBLIC_IP`
- `WHATSAPP_CONTROLLER_ECS_LAUNCH_TYPE` (`EC2` or `FARGATE`, default `EC2`)
- `WHATSAPP_CONTROLLER_ECS_STARTED_BY_PREFIX`

Runtime network policy:
- `WHATSAPP_CONTROLLER_ECS_ASSIGN_PUBLIC_IP` must be `false` (public runtime exposure is not supported).
- Use private subnets and security groups that only allow ingress from backend/controller security groups.
- Runtime URL templates may not use `{task_public_ip}`.

See `.env.example` for full key list.

## Run Locally

From backend root:

```bash
python run_whatsapp_session_controller.py
```

Or:

```bash
uvicorn whatsapp_session_controller.main:app --host 0.0.0.0 --port 8101
```

Health checks:
- `GET /healthz`
- `GET /v1/health`

## Database Migration

Apply:
- `app/db/table_schemas/controller_whatsapp_runtime_leases_schema.sql`

This is safe to apply before traffic cutover because it is controller-owned.

## Testing

Targeted tests:

```bash
python -m pytest -q tests/test_whatsapp_controller_provider.py tests/test_whatsapp_session_controller_runtime_manager.py
```

In this workspace we validated with:

```bash
conda run -n omicron python -m pytest -q tests/test_whatsapp_controller_provider.py tests/test_whatsapp_session_controller_runtime_manager.py
```

## Security Notes

- Service-role key must remain server-side only.
- Controller endpoint should be internal/private network only.
- No token/session payload logging.
- Runtime APIs are fail-closed on auth/scope/ownership mismatch.
- Do not add broad list endpoints that can enumerate other users' runtimes.

## Known Gaps (Next)

- Add reconciler worker for expiry/stuck/error recovery (Phase 5).
- Add integration tests that mock ECS API surfaces and readiness transitions.
- Finalize rollout automation and staging cutover (Phase 6).
