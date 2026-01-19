# Omicron Assistant API

FastAPI service for a multi-agent assistant. The orchestrator routes user requests to
specialist agents; current focus is a read-only Gmail agent.

## Current scope

- Orchestrator agent with handoff to a Gmail agent (OpenAI Agents SDK, `agents`).
- Gmail OAuth connect flow with token storage in SQLite (`omicron.db`).
- Gmail tools: list unread, search, read, and batch read (compact/full).
- Streaming agent output via SSE (`/v1/run-agent`).
- TODOs: real user auth (currently `dummy_user_id`), token encryption, refresh handling.

## Setup

1. Create and activate a virtual environment.
2. Install dependencies from `pyproject.toml` plus Gmail/Agents extras:
   - `agents` (OpenAI Agents SDK)
   - `google-api-python-client`, `google-auth`, `google-auth-oauthlib`
3. Copy `.env.example` to `.env` and update values.
4. Put your OAuth client secrets JSON at `.creds/gmail_client_secrets.json`
   or update `GMAIL_CLIENT_SECRETS_FILE` in `.env`.

## Configuration

- `APP_TITLE` and `API_V1_PREFIX`: API metadata and routing prefix.
- `SESSION_SECRET_KEY`: session cookie signing key (required for OAuth flow).
- `SQLITE_DB_PATH`: location of the SQLite database (default `omicron.db`).
- `OPENAI_API_KEY` and `MAX_RETRIES`: OpenAI client settings.
- `GMAIL_CLIENT_SECRETS_FILE`: path to the Google OAuth client secrets JSON.
- `GMAIL_SCOPES`: list of Gmail OAuth scopes.
- `GMAIL_REDIRECT_URI`: callback URL (must match Google OAuth settings).
- `GMAIL_POST_CONNECT_REDIRECT`: browser redirect after successful OAuth.
- `ORCHESTRATOR_AGENT_*` and `GMAIL_AGENT_*`: model + reasoning settings.

## Run the API

```bash
python run.py
```

or

```bash
uvicorn app.main:app --reload
```

For local OAuth over HTTP, set `OAUTHLIB_INSECURE_TRANSPORT=1` (handled in `run.py`).

## OAuth flow

- `GET /v1/oauth/gmail/start` redirects to Google.
- `GET /v1/oauth/gmail/callback` stores tokens in SQLite and redirects to
  `GMAIL_POST_CONNECT_REDIRECT`.

Note: OAuth state/user are stored in the session cookie; keep the same browser session.

## Agent API

`POST /v1/run-agent` accepts:

- `query` (string, required)
- `app` (string enum, optional; currently only `gmail`)
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

- `app/agents/` orchestrator + Gmail agent definitions
- `app/api/v1/endpoints/` HTTP routes
- `app/core/` settings, enums, exceptions
- `app/db/` SQLite helpers and schema
- `app/integrations/gmail/` Gmail tools and services
- `app/schemas/` request/response models
- `app/utils/` agent and Gmail helpers
- `tests/` manual scripts

## Tests

```bash
pytest
```
