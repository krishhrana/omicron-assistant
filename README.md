# Omicron Assistant API

FastAPI service for a multi-agent assistant. The orchestrator routes user requests to
specialist agents; current focus is Gmail, Google Drive, browser automation, and WhatsApp agents.

## Current scope

- Orchestrator agent with handoff to Gmail and Google Drive agents (OpenAI Agents SDK, `agents`).
- Gmail + Google Drive OAuth connect flows with token storage in Supabase.
- Optional Playwright MCP browser agent for web navigation and guided web tasks.
- Optional WhatsApp MCP agent for contact/chat lookup and messaging workflows.
- Gmail tools: list unread, search, read, and batch read (compact/full).
- Google Drive tools: search/list files with metadata + webViewLink (read-only).
- Streaming agent output via SSE (`/v1/run-agent`).
- Tokens are encrypted at rest (per-service Fernet keys derived from a master key).

## Setup

1. Create and activate a virtual environment.
2. Install dependencies from `pyproject.toml` plus Gmail/Agents extras:
   - `agents` (OpenAI Agents SDK)
   - `google-api-python-client`, `google-auth`, `google-auth-oauthlib`
3. Copy `.env.example` to `.env` and update values.
4. Put your OAuth client secrets JSON at `.creds/gmail/credentials.json`
   or update `GOOGLE_CLIENT_SECRETS_FILE` in `.env` (shared by Gmail + Drive).

## Configuration

- `APP_TITLE` and `API_V1_PREFIX`: API metadata and routing prefix.
- `SESSION_SECRET_KEY`: session cookie signing key (required for OAuth flow).
- `SUPABASE_URL`, `SUPABASE_API_KEY`, `SUPABASE_SERVICE_ROLE_KEY`: Supabase connection + Vault access.
- `SUPABASE_JWT_SECRET`: optional signed-JWT verifier fallback.
  Runtime always uses validated tokens and fails fast on startup unless Supabase-native validation
  config (`SUPABASE_URL` + `SUPABASE_API_KEY`) is present.
- `GMAIL_TOKENS_ENCRYPTION_KEY`: master Fernet key for token encryption.
  If omitted, it is fetched from Supabase Vault with secret name `gmail_tokens_encryption_key`.
- `OPENAI_API_KEY` and `MAX_RETRIES`: OpenAI client settings.
- `GOOGLE_CLIENT_SECRETS_FILE`: path to the Google OAuth client secrets JSON.
- `GMAIL_SCOPES`: list of Gmail OAuth scopes.
- `GMAIL_REDIRECT_URI`: callback URL (must match Google OAuth settings).
- `GMAIL_POST_CONNECT_REDIRECT`: browser redirect after successful OAuth.
- `GOOGLE_DRIVE_SCOPES`: list of Google Drive OAuth scopes.
- `GOOGLE_DRIVE_REDIRECT_URI`: callback URL (must match Google OAuth settings).
- `GOOGLE_DRIVE_POST_CONNECT_REDIRECT`: browser redirect after successful OAuth.
- `ORCHESTRATOR_AGENT_*`, `GMAIL_AGENT_*`, `GOOGLE_DRIVE_AGENT_*`, `BROWSER_AGENT_*`: model + reasoning settings.
- `PLAYWRIGHT_MCP_URL`: Streamable HTTP MCP endpoint (example: `http://localhost:8080/mcp`).
- `PLAYWRIGHT_MCP_TIMEOUT`, `PLAYWRIGHT_MCP_SSE_READ_TIMEOUT`, `PLAYWRIGHT_MCP_CLIENT_SESSION_TIMEOUT_SECONDS`, `PLAYWRIGHT_MCP_MAX_RETRY_ATTEMPTS`: browser MCP connection tuning.
- `PLAYWRIGHT_MCP_CONNECT_ON_STARTUP`: local-dev only; when `true`, connect a global Playwright MCP server on API startup.
- `PLAYWRIGHT_MCP_AUTH_TOKEN`: required when `PLAYWRIGHT_MCP_CONNECT_ON_STARTUP=true`.
- `WHATSAPP_AGENT_*`: model + reasoning settings for the WhatsApp specialist agent.
- `WHATSAPP_MCP_URL`: Streamable HTTP WhatsApp MCP endpoint (default: `http://127.0.0.1:8000/mcp`).
- `WHATSAPP_MCP_TIMEOUT`, `WHATSAPP_MCP_SSE_READ_TIMEOUT`, `WHATSAPP_MCP_CLIENT_SESSION_TIMEOUT_SECONDS`, `WHATSAPP_MCP_MAX_RETRY_ATTEMPTS`: WhatsApp MCP connection tuning.
- `WHATSAPP_MCP_CONNECT_ON_STARTUP`: feature flag for WhatsApp MCP availability.
  WhatsApp MCP clients are created lazily per agent run (per request), not as a global startup singleton.
- `WHATSAPP_MCP_JWT_AUDIENCE`, `WHATSAPP_MCP_JWT_SUBJECT`, `WHATSAPP_MCP_JWT_SCOPES`:
  claims used by backend when minting short-lived internal JWTs for WhatsApp MCP calls.
- `WHATSAPP_BRIDGE_JWT_SECRET`: required when `WHATSAPP_SESSION_PROVIDER=local`; used to mint short-lived
  internal JWTs for both WhatsApp MCP and bridge control-plane calls.
- `WHATSAPP_BRIDGE_JWT_AUDIENCE`, `WHATSAPP_BRIDGE_JWT_ISSUER`, `WHATSAPP_BRIDGE_JWT_TTL_SECONDS`:
  shared internal JWT claim controls.
- `BROWSER_SESSION_CONTROLLER_URL`, `BROWSER_SESSION_CONTROLLER_JWT_SECRET`, `BROWSER_SESSION_CONTROLLER_JWT_AUDIENCE`, `BROWSER_SESSION_CONTROLLER_TIMEOUT_SECONDS`: production path for lazy per-session Playwright MCP runners (controller provisions runner Pods keyed by Supabase `chat_sessions.id`).

Note: scope lists must be valid JSON arrays, e.g.
`GMAIL_SCOPES=["https://www.googleapis.com/auth/gmail.readonly"]`.

## Run the API

```bash
python run.py
```

or

```bash
uvicorn app.main:app --reload
```

For local OAuth over HTTP, set `OAUTHLIB_INSECURE_TRANSPORT=1` (handled in `run.py`).
Scope unions from incremental auth are allowed via `OAUTHLIB_RELAX_TOKEN_SCOPE=1`.

## OAuth flow

- `GET /v1/oauth/gmail/start` redirects to Google.
- `GET /v1/oauth/gmail/callback` stores tokens in Supabase and redirects to
  `GMAIL_POST_CONNECT_REDIRECT`.
- `GET /v1/oauth/google-drive/start` redirects to Google.
- `GET /v1/oauth/google-drive/callback` stores tokens in Supabase and redirects to
  `GOOGLE_DRIVE_POST_CONNECT_REDIRECT`.

Note: OAuth state/user are stored in the session cookie; keep the same browser session.

## Agent API

`POST /v1/run-agent` accepts:

- `query` (string, required)
- `session_id` (string, optional)

Response is `text/event-stream` with events like: `delta`, `message`, `tool_called`,
`tool_output`, `reasoning`, `agent_updated`, `handoff`, `session_id`, and `[DONE]`.

Example:

```bash
curl -N -X POST http://localhost:8000/v1/run-agent \
  -H "Content-Type: application/json" \
  -d '{"query":"Find unread emails from last week"}'
```

For manual streaming tests, see `tests/test_agent_route.py` and `tests/test_gmail_agent.py`.

## Project layout

- `app/agents/` orchestrator + Gmail/Google Drive/Browser/WhatsApp agent definitions
- `app/api/v1/endpoints/` HTTP routes
- `app/core/` settings, enums
- `app/db/` database helpers and schema
- `app/integrations/gmail/` Gmail tools and services
- `app/integrations/google_drive/` Google Drive tools and services
- `app/schemas/` request/response models
- `app/utils/` agent helpers, Google API utils, encryption utilities
- `tests/` manual scripts

## Tests

```bash
pytest
```
