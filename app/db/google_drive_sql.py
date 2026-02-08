import json
from dataclasses import dataclass

from app.dependencies import create_supabase_user_client
from app.utils.encryption_utils import decrypt_token, encrypt_token


@dataclass(frozen=True)
class GoogleDriveCreds:
    access_token: str | None
    refresh_token: str | None
    status: str | None


def upsert_google_drive_connection(
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
    encrypted_refresh = encrypt_token(refresh_token_encrypted, service="google_drive")
    encrypted_access = encrypt_token(access_token, service="google_drive")
    client = create_supabase_user_client(user_jwt)
    try:
        existing_resp = (
            client.table("google_drive_connections")
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
        client.table("google_drive_connections").upsert(payload, on_conflict="user_id").execute()
    finally:
        client.postgrest.aclose()


def get_google_drive_creds(user_id: str, user_jwt: str) -> GoogleDriveCreds | None:
    client = create_supabase_user_client(user_jwt)
    try:
        response = (
            client.table("google_drive_connections")
            .select("access_token, refresh_token_encrypted, status")
            .eq("user_id", user_id)
            .maybe_single()
            .execute()
        )
        data = response.data if response else None
        if not data:
            return None
        
        return GoogleDriveCreds(
            access_token=decrypt_token(data.get("access_token"), service="google_drive"),
            refresh_token=decrypt_token(data.get("refresh_token_encrypted"), service="google_drive"),
            status=data.get("status"),
        )
    finally:
        client.postgrest.aclose()


def list_google_drive_users(user_jwt: str, limit: int = 100):
    client = create_supabase_user_client(user_jwt)
    try:
        response = client.table("google_drive_connections").select("*").limit(limit).execute()
        return response.data if response else []
    finally:
        client.postgrest.aclose()


