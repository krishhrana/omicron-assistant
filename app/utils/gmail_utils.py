from app.db.gmail_sql import get_gmail_creds
from app.core.settings import get_gmail_auth_settings
from app.core.enums import GoogleApps
from app.utils.google_utils import google_api, get_google_client_for_user

settings = get_gmail_auth_settings()


def gmail_api(fn=None):
    decorator = google_api(service_label=GoogleApps.GMAIL.value)
    if fn is None:
        return decorator
    return decorator(fn)


async def get_gmail_client_for_user(user_id: str, user_jwt: str): 
    return await get_google_client_for_user(
        user_id=user_id,
        user_jwt=user_jwt,
        token_loader=get_gmail_creds,
        settings=settings,
        api_service="gmail",
        api_version="v1",
        service_label=GoogleApps.GMAIL.value,
    )
