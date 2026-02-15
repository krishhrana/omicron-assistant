CREATE TABLE IF NOT EXISTS public.gmail_connections (
    user_id uuid PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    google_email text UNIQUE,
    refresh_token_encrypted text,
    access_token text,
    access_token_expires_at timestamptz,
    scopes text,
    connected_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    revoked_at timestamptz,
    status text NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'revoked', 'disconnected'))
);

CREATE INDEX IF NOT EXISTS idx_gmail_connections_status
    ON public.gmail_connections(status);

CREATE OR REPLACE FUNCTION public.set_updated_at()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_gmail_connections_updated_at ON public.gmail_connections;
CREATE TRIGGER trg_gmail_connections_updated_at
BEFORE UPDATE ON public.gmail_connections
FOR EACH ROW
EXECUTE FUNCTION public.set_updated_at();

ALTER TABLE public.gmail_connections ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "gmail_connections_select_own" ON public.gmail_connections;
CREATE POLICY "gmail_connections_select_own"
    ON public.gmail_connections
    FOR SELECT
    USING (auth.uid() = user_id);

DROP POLICY IF EXISTS "gmail_connections_insert_own" ON public.gmail_connections;
CREATE POLICY "gmail_connections_insert_own"
    ON public.gmail_connections
    FOR INSERT
    WITH CHECK (auth.uid() = user_id);

DROP POLICY IF EXISTS "gmail_connections_update_own" ON public.gmail_connections;
CREATE POLICY "gmail_connections_update_own"
    ON public.gmail_connections
    FOR UPDATE
    USING (auth.uid() = user_id)
    WITH CHECK (auth.uid() = user_id);

DROP POLICY IF EXISTS "gmail_connections_delete_own" ON public.gmail_connections;
CREATE POLICY "gmail_connections_delete_own"
    ON public.gmail_connections
    FOR DELETE
    USING (auth.uid() = user_id);
