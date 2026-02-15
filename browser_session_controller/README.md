# Browser Session Controller

Internal service that provisions **one Playwright MCP runner Pod per Supabase `chat_sessions.id`**.

## What it does

- `POST /internal/browser-sessions/get-or-create`: creates/reuses a runner keyed by `(user_id, chat_session_id)`
- `POST /internal/browser-sessions/{id}/heartbeat`: extends TTL
- `DELETE /internal/browser-sessions/{id}`: deletes runner resources and marks the session ended
- `POST /internal/runner-secrets`: broker endpoint runner Pods call at startup to fetch a dotenv secrets payload

## Vault secrets format

The controller expects Supabase Vault to store a dotenv-compatible string per user:

- Secret name: `${BROWSER_RUNNER_VAULT_SECRET_PREFIX}${user_id}`
- Secret value example:

```env
WALMART_USERNAME=...
WALMART_PASSWORD=...
```

The runner Pod writes this to `/secrets/runtime.env` and starts `@playwright/mcp` with `--secrets /secrets/runtime.env`.

## Required env vars (controller)

- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`
- `BROWSER_SESSION_CONTROLLER_JWT_SECRET` (API -> controller auth, HS256)
- `BROWSER_RUNNER_BROKER_JWT_SECRET` (controller -> runner broker auth, HS256)
- `BROWSER_RUNNER_IMAGE`
- `BROWSER_SESSION_CONTROLLER_INTERNAL_URL` (cluster URL runners use to call the broker endpoint)

Optional:

- `BROWSER_RUNNER_ARTIFACTS_S3_BUCKET` (enables S3 upload sidecar)
- `BROWSER_RUNNER_ARTIFACTS_S3_PREFIX_BASE` (default `pw-videos`)

