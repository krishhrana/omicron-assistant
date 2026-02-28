CREATE TABLE IF NOT EXISTS public.whatsapp_runtime_leases (
    user_id uuid PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    runtime_id text NOT NULL,
    runtime_generation integer NOT NULL DEFAULT 1 CHECK (runtime_generation > 0),
    bridge_base_url text NOT NULL,
    mcp_url text NOT NULL,
    controller_state text NOT NULL
        CHECK (
            controller_state IN (
                'provisioning',
                'starting',
                'ready',
                'degraded',
                'stopping',
                'stopped',
                'error'
            )
        ),
    desired_state text NOT NULL DEFAULT 'warm'
        CHECK (desired_state IN ('warm', 'stopped')),
    lease_expires_at timestamptz NOT NULL,
    last_touched_at timestamptz NOT NULL DEFAULT now(),
    last_error_code text,
    last_error_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_whatsapp_runtime_leases_lease_expires_at
    ON public.whatsapp_runtime_leases(lease_expires_at);

CREATE INDEX IF NOT EXISTS idx_whatsapp_runtime_leases_controller_state
    ON public.whatsapp_runtime_leases(controller_state);

CREATE INDEX IF NOT EXISTS idx_whatsapp_runtime_leases_runtime_id
    ON public.whatsapp_runtime_leases(runtime_id);

CREATE OR REPLACE FUNCTION public.set_updated_at()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_whatsapp_runtime_leases_updated_at ON public.whatsapp_runtime_leases;
CREATE TRIGGER trg_whatsapp_runtime_leases_updated_at
BEFORE UPDATE ON public.whatsapp_runtime_leases
FOR EACH ROW
EXECUTE FUNCTION public.set_updated_at();

ALTER TABLE public.whatsapp_runtime_leases ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "whatsapp_runtime_leases_select_own" ON public.whatsapp_runtime_leases;
CREATE POLICY "whatsapp_runtime_leases_select_own"
    ON public.whatsapp_runtime_leases
    FOR SELECT
    USING (auth.uid() = user_id);

DROP POLICY IF EXISTS "whatsapp_runtime_leases_insert_own" ON public.whatsapp_runtime_leases;
CREATE POLICY "whatsapp_runtime_leases_insert_own"
    ON public.whatsapp_runtime_leases
    FOR INSERT
    WITH CHECK (auth.uid() = user_id);

DROP POLICY IF EXISTS "whatsapp_runtime_leases_update_own" ON public.whatsapp_runtime_leases;
CREATE POLICY "whatsapp_runtime_leases_update_own"
    ON public.whatsapp_runtime_leases
    FOR UPDATE
    USING (auth.uid() = user_id)
    WITH CHECK (auth.uid() = user_id);

DROP POLICY IF EXISTS "whatsapp_runtime_leases_delete_own" ON public.whatsapp_runtime_leases;
CREATE POLICY "whatsapp_runtime_leases_delete_own"
    ON public.whatsapp_runtime_leases
    FOR DELETE
    USING (auth.uid() = user_id);
