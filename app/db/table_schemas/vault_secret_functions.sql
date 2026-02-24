-- Service-role-only helpers used by Omicron backend for per-user secret storage.
-- These are expected to run in Supabase with Vault enabled.
-- Assumes public.get_vault_secret(secret_name text) already exists in your database.

CREATE OR REPLACE FUNCTION public.upsert_vault_secret(
    secret_name text,
    secret_value text,
    secret_description text DEFAULT NULL
)
RETURNS uuid
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, vault
AS $$
DECLARE
    existing_secret_id uuid;
    resolved_description text;
BEGIN
    IF secret_name IS NULL OR btrim(secret_name) = '' THEN
        RAISE EXCEPTION 'secret_name is required';
    END IF;
    IF secret_value IS NULL THEN
        RAISE EXCEPTION 'secret_value is required';
    END IF;

    resolved_description := COALESCE(
        NULLIF(btrim(secret_description), ''),
        'Managed by Omicron backend'
    );

    SELECT ds.id
    INTO existing_secret_id
    FROM vault.decrypted_secrets ds
    WHERE ds.name = secret_name
    LIMIT 1;

    IF existing_secret_id IS NULL THEN
        SELECT vault.create_secret(secret_value, secret_name, resolved_description)
        INTO existing_secret_id;
    ELSE
        PERFORM vault.update_secret(
            existing_secret_id,
            secret_value,
            secret_name,
            resolved_description
        );
    END IF;

    RETURN existing_secret_id;
END;
$$;

REVOKE ALL ON FUNCTION public.get_vault_secret(text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.get_vault_secret(text) TO service_role;

REVOKE ALL ON FUNCTION public.upsert_vault_secret(text, text, text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.upsert_vault_secret(text, text, text) TO service_role;
