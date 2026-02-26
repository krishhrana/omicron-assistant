# Omicron Assistant API

FastAPI backend for a multi-agent assistant that combines:
- OpenAI Agents SDK orchestration
- user-connected app data (Gmail and Google Drive)
- browser automation via Playwright MCP
- WhatsApp runtime + MCP integration

## Overview

The API exposes a single streaming agent endpoint (`/v1/run-agent`) plus onboarding, OAuth, session history, and WhatsApp connect endpoints.

At runtime:
- `orchestrator_agent` is the main entry point.
- Connected user-data agents (`gmail`, `drive`, `whatsapp`) are exposed to the orchestrator as tools.
- Handoff-enabled specialists (currently `browser`) can receive delegated control.
- Browser and WhatsApp MCP clients are created lazily per run and cleaned up after streaming completes.

## Core Capabilities

- Gmail OAuth connect/disconnect and read-only Gmail tools.
- Google Drive OAuth connect/disconnect and read-only file search tools.
- Browser agent via Playwright MCP for guided web workflows.
- WhatsApp runtime connect/status/disconnect endpoints + WhatsApp MCP agent support.
- SSE streaming from the agent with tool/handoff/reasoning events.
- Chat session persistence in Supabase (`chat_sessions`) linked to OpenAI conversation IDs.
- Onboarding profile + browser credential management with secrets stored in Supabase Vault.

## Architecture

### Agent graph
- `orchestrator_agent`
- Tool-access agents: `gmail`, `drive`, `whatsapp` (when connected/available)
- Handoff agent: `browser` (when Playwright MCP is configured)

The workflow is assembled in `app/agents/workflow.py` and agent registration is in `app/agents/registry.py`.

### Auth model
- Most API routes require `Authorization: Bearer <supabase_user_jwt>`.
- Token validation attempts Supabase native `auth.get_user` first.
- Fallback validation uses `SUPABASE_JWT_SECRET` if native validation is unavailable.

### Runtime/session providers
- Browser session provider (`BROWSER_SESSION_PROVIDER`):
  - `local` implemented
  - `controller` placeholder (not implemented)
- WhatsApp session provider (`WHATSAPP_SESSION_PROVIDER`):
  - `local` implemented
  - `controller` placeholder (not implemented)

## Requirements

- Python `>=3.10`
- Supabase project with required tables/RPC functions
- OpenAI API key
- Google OAuth client secrets JSON (shared by Gmail + Drive)
- Playwright MCP endpoint (required by startup validation)

## Installation

1. Create/activate an environment (venv or conda).
2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Copy env file:

```bash
cp .env.example .env
```

4. Set required variables in `.env` (see below).

## Environment Configuration

### Always required

- `SESSION_SECRET_KEY`
- `SUPABASE_URL`
- `SUPABASE_API_KEY`
- `SUPABASE_SERVICE_ROLE_KEY` (needed for vault RPC access)
- `OPENAI_API_KEY`
- `GOOGLE_CLIENT_SECRETS_FILE`
- `GMAIL_SCOPES`
- `GMAIL_REDIRECT_URI`
- `GMAIL_POST_CONNECT_REDIRECT`
- `GOOGLE_DRIVE_SCOPES`
- `GOOGLE_DRIVE_REDIRECT_URI`
- `GOOGLE_DRIVE_POST_CONNECT_REDIRECT`
- `PLAYWRIGHT_MCP_URL`
- `WHATSAPP_SESSION_PROVIDER` (`local` by default)
- `WHATSAPP_BRIDGE_JWT_SECRET` (required when `WHATSAPP_SESSION_PROVIDER=local`)

### Conditionally required

If `WHATSAPP_MCP_CONNECT_ON_STARTUP=true`:
- `WHATSAPP_MCP_URL`
- `WHATSAPP_MCP_JWT_AUDIENCE`
- `WHATSAPP_MCP_JWT_SUBJECT`
- `WHATSAPP_MCP_JWT_SCOPES`
- `WHATSAPP_BRIDGE_JWT_SECRET`

If `WHATSAPP_SESSION_PROVIDER=controller`:
- `WHATSAPP_SESSION_CONTROLLER_URL`
- `WHATSAPP_SESSION_CONTROLLER_JWT_SECRET`

If `BROWSER_SESSION_PROVIDER=controller`:
- controller fields exist in settings, but controller mode is currently not implemented.

### Optional/fallback

- `SUPABASE_JWT_SECRET` (JWT fallback validation)
- `GMAIL_TOKENS_ENCRYPTION_KEY`
  - if omitted, startup fetches vault secret `gmail_tokens_encryption_key`.

### Important note

Use `GOOGLE_CLIENT_SECRETS_FILE` for Google OAuth credentials. Both Gmail and Google Drive settings read this key.

## Database Setup (Supabase)

Apply SQL files from `app/db/table_schemas/`:

- `vault_secret_functions.sql`
- `user_profiles_schema.sql`
- `user_onboarding_schema.sql`
- `gmail_schema.sql`
- `google_drive_schema.sql`
- `sessions_schema.sql`
- `browser_sessions_schema.sql`
- `whatsapp_connections_schema.sql`

Also review:
- `browser_credentials_vault_contract.md`

## Running Locally

Development mode:

```bash
python run.py
```

Alternative:

```bash
uvicorn app.main:app --reload
```

Notes:
- `run.py` sets `OAUTHLIB_INSECURE_TRANSPORT=1` for local HTTP OAuth callbacks.
- API base prefix defaults to `/v1`.

## API Endpoints

### Agent
- `POST /v1/run-agent`
  - Body: `{ "query": "...", "session_id": "..."? }`
  - Response: `text/event-stream`

### Apps
- `GET /v1/apps/supported`

### Gmail OAuth
- `GET /v1/oauth/gmail/start`
- `GET /v1/oauth/gmail/callback`
- `POST /v1/oauth/gmail/disconnect`

### Google Drive OAuth
- `GET /v1/oauth/google-drive/start`
- `GET /v1/oauth/google-drive/callback`
- `POST /v1/oauth/google-drive/disconnect`

### Sessions
- `GET /v1/sessions`
- `POST /v1/sessions`
- `DELETE /v1/sessions/{session_id}`
- `GET /v1/sessions/{session_id}/history`

### Onboarding
- `GET /v1/onboarding/state`
- `PUT /v1/onboarding/profile`
- `GET /v1/onboarding/browser-credentials`
- `POST /v1/onboarding/browser-credentials`
- `DELETE /v1/onboarding/browser-credentials/{site_key}`
- `POST /v1/onboarding/complete`

### WhatsApp connect/runtime
- `POST /v1/whatsapp/connect/start`
- `GET /v1/whatsapp/connect/status`
- `POST /v1/whatsapp/connect/disconnect`

## Streaming Event Contract (`/v1/run-agent`)

SSE messages include:
- `session_id`
- `delta`
- `reasoning_delta`
- `reasoning_done`
- `message`
- `tool_called`
- `tool_output`
- `reasoning`
- `agent_updated`
- `handoff`
- terminal: `[DONE]`

## Example Requests

### Start OAuth (Gmail)

```bash
curl -X GET "http://localhost:8000/v1/oauth/gmail/start" \
  -H "Authorization: Bearer $SUPABASE_USER_JWT"
```

### Run agent (stream)

```bash
curl -N -X POST "http://localhost:8000/v1/run-agent" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $SUPABASE_USER_JWT" \
  -d '{"query":"Summarize unread Gmail from last 7 days"}'
```

## Project Layout

- `app/main.py`: FastAPI app creation + lifespan
- `app/auth.py`: Bearer token validation
- `app/core/settings.py`: typed env settings + startup security validation
- `app/api/v1/endpoints/`: HTTP routes
- `app/agents/`: orchestrator/specialists + workflow wiring
- `app/integrations/gmail/`: Gmail tool/service layer
- `app/integrations/google_drive/`: Drive tool/service layer
- `app/browser_sessions/`: browser runtime provider abstraction + lazy MCP client
- `app/whatsapp_sessions/`: WhatsApp runtime provider abstraction + lazy MCP client + JWT bridge auth
- `app/db/`: Supabase data access
- `tests/`: tests and local/manual scripts

## Tests

Run full test suite:

```bash
pytest
```

Useful focused tests:

```bash
pytest tests/test_startup_security_config.py
pytest tests/test_auth_context.py
pytest tests/test_whatsapp_bridge_auth.py
```

## Current Limitations

- `controller` providers for browser and WhatsApp sessions are not implemented yet.
- Startup currently requires `PLAYWRIGHT_MCP_URL`.
- `pyproject.toml` dependency list is minimal; use `requirements.txt` for full local setup.
