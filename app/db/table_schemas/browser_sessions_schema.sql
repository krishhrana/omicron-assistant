CREATE TABLE IF NOT EXISTS public.browser_sessions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    chat_session_id uuid NOT NULL REFERENCES public.chat_sessions(id) ON DELETE CASCADE,
    status text NOT NULL DEFAULT 'starting'
        CHECK (status IN ('starting', 'ready', 'ended', 'error')),
    mcp_url text,
    namespace text,
    pod_name text,
    service_name text,
    artifacts_s3_prefix text,
    claim_id uuid,
    expires_at timestamptz NOT NULL,
    last_used_at timestamptz NOT NULL DEFAULT now(),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_browser_sessions_user_chat_session
    ON public.browser_sessions(user_id, chat_session_id);

CREATE INDEX IF NOT EXISTS idx_browser_sessions_expires_at
    ON public.browser_sessions(expires_at);

CREATE INDEX IF NOT EXISTS idx_browser_sessions_status
    ON public.browser_sessions(status);

CREATE OR REPLACE FUNCTION public.set_updated_at()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_browser_sessions_updated_at ON public.browser_sessions;
CREATE TRIGGER trg_browser_sessions_updated_at
BEFORE UPDATE ON public.browser_sessions
FOR EACH ROW
EXECUTE FUNCTION public.set_updated_at();

ALTER TABLE public.browser_sessions ENABLE ROW LEVEL SECURITY;

-- Intentionally no RLS policies: this table is controller-owned. The controller uses service role
-- (bypasses RLS); normal user JWTs should not be able to read/write these rows.

