CREATE TABLE IF NOT EXISTS public.whatsapp_connections (
    user_id uuid PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    runtime_id text,
    status text NOT NULL DEFAULT 'disconnected'
        CHECK (
            status IN (
                'disconnected',
                'connecting',
                'awaiting_qr',
                'logging_in',
                'syncing',
                'connected',
                'logged_out',
                'error'
            )
        ),
    reauth_required boolean NOT NULL DEFAULT false,
    last_error_code text,
    connected_at timestamptz,
    disconnected_at timestamptz,
    last_seen_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_whatsapp_connections_status
    ON public.whatsapp_connections(status);

CREATE OR REPLACE FUNCTION public.set_updated_at()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_whatsapp_connections_updated_at ON public.whatsapp_connections;
CREATE TRIGGER trg_whatsapp_connections_updated_at
BEFORE UPDATE ON public.whatsapp_connections
FOR EACH ROW
EXECUTE FUNCTION public.set_updated_at();

ALTER TABLE public.whatsapp_connections ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "whatsapp_connections_select_own" ON public.whatsapp_connections;
CREATE POLICY "whatsapp_connections_select_own"
    ON public.whatsapp_connections
    FOR SELECT
    USING (auth.uid() = user_id);

DROP POLICY IF EXISTS "whatsapp_connections_insert_own" ON public.whatsapp_connections;
CREATE POLICY "whatsapp_connections_insert_own"
    ON public.whatsapp_connections
    FOR INSERT
    WITH CHECK (auth.uid() = user_id);

DROP POLICY IF EXISTS "whatsapp_connections_update_own" ON public.whatsapp_connections;
CREATE POLICY "whatsapp_connections_update_own"
    ON public.whatsapp_connections
    FOR UPDATE
    USING (auth.uid() = user_id)
    WITH CHECK (auth.uid() = user_id);

DROP POLICY IF EXISTS "whatsapp_connections_delete_own" ON public.whatsapp_connections;
CREATE POLICY "whatsapp_connections_delete_own"
    ON public.whatsapp_connections
    FOR DELETE
    USING (auth.uid() = user_id);
