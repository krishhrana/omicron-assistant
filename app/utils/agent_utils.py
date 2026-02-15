from dataclasses import dataclass
from agents import RunContextWrapper


from app.core.enums import SupportedApps

@dataclass
class UserContext:
    user_id: str
    user_jwt: str | None = None
    # Supabase chat_sessions.id. Canonical identifier for multi-user session state (e.g., browser runners).
    session_id: str | None = None
    connected_apps: list[SupportedApps] | None = None


def get_user_id(ctx: RunContextWrapper[UserContext]) -> str:
    user_id = ctx.context.user_id
    if not user_id:
        raise RuntimeError("Missing user_id in Gmail tool context")
    return user_id


def get_user_jwt(ctx: RunContextWrapper[UserContext]) -> str:
    user_jwt = ctx.context.user_jwt
    if not user_jwt:
        raise RuntimeError("Missing user_jwt in Gmail tool context")
    return user_jwt
