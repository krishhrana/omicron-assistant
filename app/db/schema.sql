PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS gmail_connections (
    user_id TEXT PRIMARY KEY,
    google_email TEXT UNIQUE,
    refresh_token_encrypted TEXT,
    access_token TEXT,
    access_token_expires_at DATETIME,
    scopes TEXT,
    connected_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    revoked_at DATETIME,
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'revoked', 'disconnected'))
);

CREATE INDEX IF NOT EXISTS idx_gmail_connections_status ON gmail_connections(status);
