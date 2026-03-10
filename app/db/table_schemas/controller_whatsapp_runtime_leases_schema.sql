-- Controller-owned WhatsApp runtime leases.
-- This table is authoritative for runtime lifecycle state in the WhatsApp session controller.

CREATE TABLE IF NOT EXISTS public.controller_whatsapp_runtime_leases (
    user_id uuid PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    runtime_id text NOT NULL UNIQUE,
    runtime_generation integer NOT NULL CHECK (runtime_generation > 0),
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
    bridge_base_url text NOT NULL,
    mcp_url text NOT NULL,
    runtime_started_at timestamptz NOT NULL,
    hard_expires_at timestamptz NOT NULL,
    lease_expires_at timestamptz NOT NULL,
    last_touched_at timestamptz NOT NULL DEFAULT now(),
    last_error_code text,
    last_error_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CHECK (runtime_started_at <= hard_expires_at),
    CHECK (lease_expires_at <= hard_expires_at)
);

CREATE INDEX IF NOT EXISTS idx_controller_whatsapp_runtime_leases_lease_expires_at
    ON public.controller_whatsapp_runtime_leases(lease_expires_at);

CREATE INDEX IF NOT EXISTS idx_controller_whatsapp_runtime_leases_hard_expires_at
    ON public.controller_whatsapp_runtime_leases(hard_expires_at);

CREATE INDEX IF NOT EXISTS idx_controller_whatsapp_runtime_leases_state
    ON public.controller_whatsapp_runtime_leases(controller_state);

CREATE INDEX IF NOT EXISTS idx_controller_whatsapp_runtime_leases_desired_state
    ON public.controller_whatsapp_runtime_leases(desired_state);

CREATE OR REPLACE FUNCTION public.set_updated_at()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_controller_whatsapp_runtime_leases_updated_at
    ON public.controller_whatsapp_runtime_leases;
CREATE TRIGGER trg_controller_whatsapp_runtime_leases_updated_at
BEFORE UPDATE ON public.controller_whatsapp_runtime_leases
FOR EACH ROW
EXECUTE FUNCTION public.set_updated_at();

ALTER TABLE public.controller_whatsapp_runtime_leases ENABLE ROW LEVEL SECURITY;

-- Intentionally no RLS policies: controller service is the only writer/reader via service role.
