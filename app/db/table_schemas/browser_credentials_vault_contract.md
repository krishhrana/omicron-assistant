# Browser Credentials Vault Contract (v1)

This document defines the per-user secret format for browser website credentials.

## Secret key

Use the existing controller prefix with user id:

- `browser_secrets_<user_id>`

## Secret value

Store JSON with versioned schema:

```json
{
  "version": 1,
  "sites": [
    {
      "site_key": "amazon",
      "site_name": "Amazon",
      "login_url": "https://www.amazon.com/",
      "username": "user@example.com",
      "password": "super-secret",
      "created_at": "2026-02-16T00:00:00Z"
    }
  ]
}
```

## v1 rules

- `username/password` only (no token field in v1).
- `site_key` is a normalized stable id for placeholder generation.
- API responses must never return raw `password`.
- Controller should derive placeholders from `site_key` as:
  - `<SITE_KEY>_USERNAME`
  - `<SITE_KEY>_PASSWORD`
