## Per-User Browser Sessions on EKS (Playwright MCP Runners)

### Summary
Deploy Playwright MCP as **ephemeral per-chat-session runner pods** in Kubernetes, managed by a **separate controller service**. The main Omicron API requests/leases a runner for `(user_id, conversation_id)`, connects to its internal MCP endpoint, and runs the BrowserAgent. Runner pods **pull per-user secrets from Supabase Vault via an internal broker API**, record **video only**, upload artifacts to **S3**, and are reaped on **10-minute idle TTL**. This enables safe(ish) multi-user isolation at ~100 concurrent sessions.

---

## Goals & Success Criteria
- Each end user gets an **isolated browser session** (cookies/storage not shared with other users).
- Session scope: **per chat session** (recommended mapping to OpenAI `conversation_id`).
- Runner lifetime: **idle TTL 10 minutes**, extended by heartbeat during activity.
- Concurrency: support **up to ~100** active runner pods.
- Secrets: never stored in repo; no secret files read by app logic; secrets fetched at runtime.
- Artifacts: **video only**, uploaded to **S3**, access **internal admins only**.
- No public MCP endpoints; all MCP traffic stays inside the cluster VPC.

---

## High-Level Architecture

### Components
1. **Omicron API** (existing FastAPI)
   - Handles end-user auth (Supabase JWT), SSE streaming, orchestrator + agents.
   - When BrowserAgent is needed, it requests a browser runner session from the controller and connects to MCP.

2. **Browser Session Controller Service** (new FastAPI service, internal)
   - Owns session lifecycle and Kubernetes pod/service creation/deletion.
   - Stores session leases/mappings in **Supabase Postgres**.
   - Provides a **broker endpoint** for runners to fetch secrets (controller fetches from Supabase Vault using service role).

3. **Runner Pods** (ephemeral, one per `(user_id, conversation_id)` active session)
   - Container runs `@playwright/mcp` with `--isolated`.
   - At startup: fetches per-user secrets from controller broker, writes to an in-memory/ephemeral file, then starts MCP server.
   - Records video, writes to an ephemeral output dir, uploads to S3 on termination.

4. **S3 bucket** (artifacts)
   - SSE-KMS or SSE-S3, lifecycle expiry (e.g., 7 days), blocked public access.

### Network Boundaries
- Public: only Omicron API ingress (and FE).
- Internal-only (ClusterIP): controller service; runner services.
- NetworkPolicy restricts runner ingress to only Omicron API (and optionally controller for health).

---

## Interfaces / APIs

### Controller (internal) API
All endpoints served on `browser-session-controller.<ns>.svc.cluster.local`.

1. `POST /internal/browser-sessions/get-or-create`
   - Request (from Omicron API):
     - `user_id: string`
     - `conversation_id: string`
     - `ttl_seconds: int` (default 600)
     - `record_video: bool` (default true)
   - Response:
     - `session_id: string`
     - `mcp_url: string` (e.g. `http://pw-mcp-<session_id>.<ns>.svc.cluster.local:8080/mcp`)
     - `expires_at: iso8601`
     - `status: starting|ready`

2. `POST /internal/browser-sessions/{session_id}/heartbeat`
   - Extends TTL and updates `last_used_at`.

3. `DELETE /internal/browser-sessions/{session_id}`
   - Tears down K8s Service + Pod; marks session ended.

### Controller broker endpoint (runner-only)
4. `POST /internal/runner-secrets`
   - Auth: `Authorization: Bearer <runner_broker_token>`
   - Response: a single secrets payload for that session/user (format compatible with `@playwright/mcp --secrets`).
   - Important: broker token is **short-lived** and **scoped to exactly one session**.

### Auth between Omicron API and controller
- Use a **service-to-service JWT** signed with a shared secret stored in Kubernetes Secret:
  - API includes `Authorization: Bearer <api_to_controller_jwt>` with 60s expiry and audience `browser-session-controller`.
  - Controller verifies signature + aud + expiry.

---

## Data Model (Supabase Postgres)

### Table: `browser_sessions`
One row per `(user_id, conversation_id)`; reused across restarts.

Recommended columns:
- `id uuid primary key default gen_random_uuid()`
- `user_id text not null`
- `conversation_id text not null`
- `status text not null` (`starting|ready|ended|error`)
- `mcp_url text null`
- `k8s_namespace text not null`
- `pod_name text null`
- `service_name text null`
- `created_at timestamptz default now()`
- `updated_at timestamptz default now()`
- `last_used_at timestamptz default now()`
- `expires_at timestamptz not null`
- `claim_id uuid null` (used to coordinate “who is creating the pod”)
- `error text null`
- `artifacts_s3_prefix text null`

Constraints & indexes:
- Unique: `(user_id, conversation_id)`
- Index: `(expires_at)`
- Index: `(status)`

### Session creation concurrency control (decision complete)
Controller implements leader election using `status + claim_id`:
1. Read row by `(user_id, conversation_id)`.
2. If `status=ready` and `expires_at > now()`: return it.
3. Else attempt atomic “claim”:
   - `UPDATE browser_sessions SET status='starting', claim_id=<new uuid>, expires_at=now()+ttl WHERE user_id=? AND conversation_id=? AND (status!='starting' OR updated_at < now()-interval '2 minutes')`
   - If update affected 1 row: this controller instance is leader; create pod/service then set `status='ready'` and fill fields.
   - If update affected 0 rows and row is `starting`: poll until `ready` or timeout; if timeout -> takeover rule triggers via stale `updated_at`.

---

## Secrets Strategy (no secret files in repo)

### Per-user secret location
- Supabase Vault secret name derived by controller (do not trust caller input), e.g.:
  - `pw_site_creds__<user_id>` (or `<tenant>__<user_id>` if you add tenants later)

### Secret schema (concrete)
Store JSON in Vault:
```json
{
  "credentials": {
    "walmart": { "username": "…", "password": "…" },
    "slack": { "username": "…", "password": "…" }
  }
}
```

Runner translation step:
- Runner fetches JSON from broker and writes a runtime secrets file for MCP, emitting keys like:
  - `<SITE>_USERNAME` and `<SITE>_PASSWORD` (uppercased site key)
- The BrowserAgent prompt stays “use secret key names only” and relies on MCP’s secrets substitution.

Broker security:
- Runner never receives Supabase service role key.
- Broker uses controller’s service role key to call `get_vault_secret(secret_name)`.

---

## Kubernetes Design (EKS)

### Namespaces
- `omicron` (Omicron API)
- `omicron-browser` (controller + runner pods + runner services)

### Controller Deployment
- Deployment `browser-session-controller` in `omicron-browser`
- ServiceAccount `browser-session-controller-sa`
- RBAC in `omicron-browser`:
  - Role allowing create/get/list/watch/delete on:
    - `pods`, `pods/log`, `services`, `endpoints`
- ClusterIP Service `browser-session-controller`

### Runner Pod Template (per session)
- Pod name: `pw-mcp-<session_id>`
- Service name: `pw-mcp-<session_id>` (ClusterIP)
- Labels:
  - `app=pw-mcp-runner`
  - `session_id=<session_id>`
  - `user_id_hash=<sha256(user_id)>` (avoid raw user id in labels)
- Container image: `omicron/playwright-mcp-runner:<version>` built from `mcr.microsoft.com/playwright` base.
- Command/entrypoint:
  1. Fetch secrets from controller broker using runner token.
  2. Write secrets file to `/secrets/runtime.env` (emptyDir, 0600).
  3. Start MCP:
     - `npx -y @playwright/mcp@<pinned> --port 8080 --isolated --secrets /secrets/runtime.env --output-dir /output --save-video 1920x1080 --viewport-size 1920x1080`
  4. On SIGTERM: upload `/output` to S3 prefix then exit.

Volumes:
- `emptyDir` for `/secrets`
- `emptyDir` for `/output`
- `emptyDir` (medium: Memory) mounted to `/dev/shm` for Chromium stability

Resources (starting point):
- requests: `cpu: 1`, `memory: 2Gi`
- limits: `cpu: 2`, `memory: 4Gi`
- Dedicated node group:
  - nodeSelector `workload=browser`
  - taints/tolerations to keep browsers off API nodes
  - Cluster autoscaler/Karpenter enabled for this node group

Readiness:
- `tcpSocket` readinessProbe on `8080` (avoid brittle HTTP checks)

### NetworkPolicy (CNI permitting)
- Allow ingress to runner pods on `8080` only from:
  - Omicron API namespace pods (label selector)
- Allow egress from runner pods to:
  - controller service (broker endpoint)
  - S3 (prefer VPC endpoint)
  - internet egress (target websites) via NAT (cannot fully restrict by domain with vanilla NP)

### AWS IAM (IRSA)
- ServiceAccount for runners: `pw-mcp-runner-sa` with IRSA role:
  - S3 `PutObject`, `AbortMultipartUpload`, `ListBucket` (scoped to prefix)
  - Optional KMS `Encrypt` if SSE-KMS
- Bucket policy denies public, enforces encryption, and limits prefixes.

S3 key layout:
- `s3://<bucket>/pw-videos/<env>/<session_id>/...`

Lifecycle:
- Expire objects under `pw-videos/` after N days (e.g. 7).

---

## Omicron API Changes (concrete integration points)

1. **Ensure `conversation_id` exists before acquiring a runner**
   - In `/v1/run-agent`, call `await session._get_session_id()` early when browser might be used, so you have a stable per-chat-session key.

2. **Replace global `PLAYWRIGHT_MCP_URL` usage**
   - Keep `PLAYWRIGHT_MCP_URL` only for local dev fallback.
   - In prod:
     - When orchestrator routes to browser, call controller `get-or-create` with `user_id + conversation_id`.
     - Create `MCPServerStreamableHttp` per request using returned `mcp_url`.
     - Connect it, pass into a per-request `BrowserAgent`, then cleanup after run.

3. **Connected apps logic becomes per-user**
   - If controller returns “no credentials configured”, treat browser as not connected for that user and return a clear error (no secret disclosure).

---

## Session Lifecycle (end-to-end)
1. User sends chat message requesting browser task.
2. Omicron API creates/loads OpenAI conversation id.
3. Omicron API requests controller lease for `(user_id, conversation_id)`.
4. Controller creates or reuses runner:
   - claim row -> create Pod + Service -> wait ready -> update DB -> respond with `mcp_url`.
5. Omicron API connects to runner MCP and runs BrowserAgent.
6. Each streamed run sends heartbeat to controller.
7. After idle TTL expires, controller reaper deletes Pod/Service and marks session ended.
8. Runner uploads video artifacts to S3 on termination; controller stores S3 prefix in DB.

---

## Reaper / Cleanup
- Controller runs a background loop every 30–60s:
  - Query sessions where `expires_at < now()` and `status in ('ready','starting')`
  - Delete K8s Service + Pod
  - Update DB `status='ended'`
- Stuck-starting guard:
  - If `status='starting'` for > 2 minutes, mark `error` and allow takeover on next request.

---

## Quotas / Safety Limits (for ~100 concurrency)
- Global cap: max N runner pods in namespace (e.g., 120)
- Per user cap: max 3 active sessions (across conversations); otherwise reject or reuse oldest.
- Backpressure:
  - Controller returns 429 with retry-after if capacity exceeded.
- No “stealth”/anti-bot bypass behavior; respect site policies. If MFA/CAPTCHA occurs, fail gracefully and surface to user.

---

## Observability
- Controller metrics:
  - active_sessions, starting_sessions, session_create_latency, pod_create_failures, reaper_deletes
- Runner logs:
  - startup, broker fetch success/failure, mcp listening, upload success/failure
- S3:
  - object count/size by prefix, lifecycle deletion checks
- Alerting:
  - high error rate in session creation, runaway pods, upload failures

---

## Testing & Acceptance Scenarios
1. **Multi-user isolation**
   - Two distinct users create sessions concurrently; confirm different pods/services and no shared cookies/state.
2. **Session reuse**
   - Same user, same conversation: repeated calls within TTL reuse same runner.
3. **TTL expiry**
   - No activity for >10 min: runner pod deleted; next request recreates.
4. **Concurrent create race**
   - Two API requests simultaneously for same user+conversation: only one runner created; second waits and receives same session.
5. **Artifacts**
   - Video file appears in S3 under correct prefix after session end; not accessible publicly.
6. **Failure**
   - Runner fails to start: controller marks session error and returns actionable error to API.

---

## Rollout Plan
1. Deploy controller in `omicron-browser` with RBAC, no API usage yet.
2. Deploy runner image and IRSA permissions; verify you can create a runner manually and reach `/mcp` from within cluster.
3. Add API integration behind feature flag `BROWSER_SESSIONS_ENABLED`.
4. Enable for internal users only; monitor session creation latency + pod churn.
5. Scale browser node group + set quota caps; then open to all users.

---

## Assumptions / Defaults (explicit)
- Kubernetes: **EKS**.
- Artifacts: **video only**, uploaded to **S3**, visible to **internal admins only**.
- Secrets: stored in **Supabase Vault**, fetched by controller using service role; runners fetch via **controller broker** using short-lived tokens.
- Session scope: **per chat session** keyed by OpenAI `conversation_id`.
- Session auth state: **ephemeral per session** (no persisted storage-state).
- Default idle TTL: **10 minutes**.
- No attempt to bypass bot detection/CAPTCHA; failures are surfaced to user.
