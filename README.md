# Omicron Assistant API

FastAPI service for a multi-agent assistant. The orchestrator routes user requests to
specialist agents; current focus is read-only Gmail and Google Drive agents.

## Current scope

- Orchestrator agent with handoff to Gmail and Google Drive agents (OpenAI Agents SDK, `agents`).
- Gmail + Google Drive OAuth connect flows with token storage in Supabase.
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
- `SUPABASE_JWT_SECRET`: verify Supabase JWTs (optional; unsigned decode if omitted).
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
- `ORCHESTRATOR_AGENT_*`, `GMAIL_AGENT_*`, `GOOGLE_DRIVE_AGENT_*`: model + reasoning settings.

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
- `app` (string enum, optional; `gmail` or `drive`)
- `session_id` (string, optional)

Response is `text/event-stream` with events like: `delta`, `message`, `tool_called`,
`tool_output`, `reasoning`, `agent_updated`, `handoff`, `session_id`, and `[DONE]`.

Example:

```bash
curl -N -X POST http://localhost:8000/v1/run-agent \
  -H "Content-Type: application/json" \
  -d '{"query":"Find unread emails from last week","app":"gmail"}'
```

For manual streaming tests, see `tests/test_agent_route.py` and `tests/test_gmail_agent.py`.

## Project layout

- `app/agents/` orchestrator + Gmail/Google Drive agent definitions
- `app/api/v1/endpoints/` HTTP routes
- `app/core/` settings, enums, exceptions
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
