import json
from dataclasses import dataclass

from app.db.sqlite import get_connection


@dataclass(frozen=True)
class GmailCreds:
    access_token: str | None
    refresh_token: str | None
    status: str | None


def upsert_gmail_connection(
    *,
    user_id: str,
    google_email: str | None,
    refresh_token_encrypted: str | None,
    access_token: str | None,
    access_token_expires_at: str | None,
    scopes: list[str] | None,
    status: str = "active",
    revoked_at: str | None = None,
) -> None:
    scopes_json = json.dumps(scopes) if scopes is not None else None
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO gmail_connections (
                user_id,
                google_email,
                refresh_token_encrypted,
                access_token,
                access_token_expires_at,
                scopes,
                revoked_at,
                status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                google_email = COALESCE(excluded.google_email, gmail_connections.google_email),
                refresh_token_encrypted = COALESCE(excluded.refresh_token_encrypted, gmail_connections.refresh_token_encrypted),
                access_token = COALESCE(excluded.access_token, gmail_connections.access_token),
                access_token_expires_at = COALESCE(excluded.access_token_expires_at, gmail_connections.access_token_expires_at),
                scopes = COALESCE(excluded.scopes, gmail_connections.scopes),
                updated_at = CURRENT_TIMESTAMP,
                revoked_at = excluded.revoked_at,
                status = excluded.status
            """,
            (
                user_id,
                google_email,
                refresh_token_encrypted,
                access_token,
                access_token_expires_at,
                scopes_json,
                revoked_at,
                status,
            ),
        )


def get_gmail_creds(user_id: str) -> GmailCreds | None:
    with get_connection() as conn:
        query = """
        Select access_token, refresh_token_encrypted as refresh_token, status 
        from gmail_connections where user_id = ?
        """
        cursor = conn.execute(query, (user_id,))
        row = cursor.fetchone()
        if row is None:
            return None
        return GmailCreds(
            access_token=row[0],
            refresh_token=row[1],
            status=row[2],
        )


def list_gmail_users(limit: int = 100):
    with get_connection() as conn:
        cursor = conn.execute(
            """
            SELECT * FROM gmail_connections LIMIT ?
            """,
            (limit,),
        )
        return cursor.fetchall()
