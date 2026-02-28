CREATE TABLE IF NOT EXISTS public.oauth_transactions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    provider text NOT NULL
        CHECK (provider IN ('gmail', 'google-drive')),
    user_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    status text NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'connected', 'error', 'expired')),
    return_to text NOT NULL,
    error_detail text,
    expires_at timestamptz NOT NULL,
    completed_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_oauth_transactions_user_provider_status
    ON public.oauth_transactions(user_id, provider, status);

CREATE INDEX IF NOT EXISTS idx_oauth_transactions_expires_at
    ON public.oauth_transactions(expires_at);

CREATE INDEX IF NOT EXISTS idx_oauth_transactions_created_at_desc
    ON public.oauth_transactions(created_at DESC);

CREATE OR REPLACE FUNCTION public.set_updated_at()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_oauth_transactions_updated_at ON public.oauth_transactions;
CREATE TRIGGER trg_oauth_transactions_updated_at
BEFORE UPDATE ON public.oauth_transactions
FOR EACH ROW
EXECUTE FUNCTION public.set_updated_at();

ALTER TABLE public.oauth_transactions ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "oauth_transactions_select_own" ON public.oauth_transactions;
CREATE POLICY "oauth_transactions_select_own"
    ON public.oauth_transactions
    FOR SELECT
    USING (auth.uid() = user_id);

DROP POLICY IF EXISTS "oauth_transactions_insert_own" ON public.oauth_transactions;
CREATE POLICY "oauth_transactions_insert_own"
    ON public.oauth_transactions
    FOR INSERT
    WITH CHECK (auth.uid() = user_id);

DROP POLICY IF EXISTS "oauth_transactions_update_own" ON public.oauth_transactions;
CREATE POLICY "oauth_transactions_update_own"
    ON public.oauth_transactions
    FOR UPDATE
    USING (auth.uid() = user_id)
    WITH CHECK (auth.uid() = user_id);

DROP POLICY IF EXISTS "oauth_transactions_delete_own" ON public.oauth_transactions;
CREATE POLICY "oauth_transactions_delete_own"
    ON public.oauth_transactions
    FOR DELETE
    USING (auth.uid() = user_id);
