import json
from dataclasses import dataclass

from app.utils.encryption_utils import encrypt_token, decrypt_token
from app.dependencies import create_supabase_user_client


@dataclass(frozen=True)
class GmailCreds:
    access_token: str | None
    refresh_token: str | None
    status: str | None


async def upsert_gmail_connection(
    *,
    user_id: str,
    user_jwt: str,
    google_email: str | None,
    refresh_token_encrypted: str | None,
    access_token: str | None,
    access_token_expires_at: str | None,
    scopes: list[str] | None,
    status: str = "active",
    revoked_at: str | None = None,
) -> None:
    scopes_json = json.dumps(scopes) if scopes is not None else None
    encrypted_refresh = encrypt_token(refresh_token_encrypted, service="gmail")
    encrypted_access = encrypt_token(access_token, service="gmail")
    client = await create_supabase_user_client(user_jwt)
    try:
        existing_resp = await (
            client.table("gmail_connections")
            .select(
                "google_email, refresh_token_encrypted, access_token, access_token_expires_at, scopes"
            )
            .eq("user_id", user_id)
            .maybe_single()
            .execute()
        )
        existing = existing_resp.data if existing_resp else None

        payload = {
            "user_id": user_id,
            "google_email": (
                google_email if google_email is not None else (existing.get("google_email") if existing else None)
            ),
            "refresh_token_encrypted": (
                encrypted_refresh
                if encrypted_refresh is not None
                else (existing.get("refresh_token_encrypted") if existing else None)
            ),
            "access_token": (
                encrypted_access
                if encrypted_access is not None
                else (existing.get("access_token") if existing else None)
            ),
            "access_token_expires_at": (
                access_token_expires_at
                if access_token_expires_at is not None
                else (existing.get("access_token_expires_at") if existing else None)
            ),
            "scopes": (
                scopes_json if scopes_json is not None else (existing.get("scopes") if existing else None)
            ),
            "revoked_at": revoked_at,
            "status": status,
        }
        await client.table("gmail_connections").upsert(payload, on_conflict="user_id").execute()
    finally:
        await client.postgrest.aclose()


async def get_gmail_creds(user_id: str, user_jwt: str) -> GmailCreds | None:
    client = await create_supabase_user_client(user_jwt)
    try:
        response = await (
            client.table("gmail_connections")
            .select("access_token, refresh_token_encrypted, status")
            .eq("user_id", user_id)
            .maybe_single()
            .execute()
        )
        data = response.data if response else None
        if not data:
            return None
        return GmailCreds(
            access_token=decrypt_token(data.get("access_token"), service="gmail"),
            refresh_token=decrypt_token(data.get("refresh_token_encrypted"), service="gmail"),
            status=data.get("status"),
        )
    finally:
        await client.postgrest.aclose()


async def list_gmail_users(user_jwt: str, limit: int = 100):
    client = await create_supabase_user_client(user_jwt)
    try:
        response = await client.table("gmail_connections").select("*").limit(limit).execute()
        return response.data if response else []
    finally:
        await client.postgrest.aclose()
