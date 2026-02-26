CREATE TABLE IF NOT EXISTS public.user_onboarding (
    user_id uuid PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    onboarding_completed_at timestamptz,
    onboarding_version integer NOT NULL DEFAULT 1
        CHECK (onboarding_version >= 1),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_user_onboarding_completed_at
    ON public.user_onboarding(onboarding_completed_at);

CREATE OR REPLACE FUNCTION public.set_updated_at()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_user_onboarding_updated_at ON public.user_onboarding;
CREATE TRIGGER trg_user_onboarding_updated_at
BEFORE UPDATE ON public.user_onboarding
FOR EACH ROW
EXECUTE FUNCTION public.set_updated_at();

ALTER TABLE public.user_onboarding ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "user_onboarding_select_own" ON public.user_onboarding;
CREATE POLICY "user_onboarding_select_own"
    ON public.user_onboarding
    FOR SELECT
    USING (auth.uid() = user_id);

DROP POLICY IF EXISTS "user_onboarding_insert_own" ON public.user_onboarding;
CREATE POLICY "user_onboarding_insert_own"
    ON public.user_onboarding
    FOR INSERT
    WITH CHECK (auth.uid() = user_id);

DROP POLICY IF EXISTS "user_onboarding_update_own" ON public.user_onboarding;
CREATE POLICY "user_onboarding_update_own"
    ON public.user_onboarding
    FOR UPDATE
    USING (auth.uid() = user_id)
    WITH CHECK (auth.uid() = user_id);

DROP POLICY IF EXISTS "user_onboarding_delete_own" ON public.user_onboarding;
CREATE POLICY "user_onboarding_delete_own"
    ON public.user_onboarding
    FOR DELETE
    USING (auth.uid() = user_id);
