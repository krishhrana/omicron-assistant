from app.utils.google_utils import get_google_client_for_user, google_api
from app.core.enums import GoogleApps
from app.core.settings import get_google_drive_settings
from app.db.google_drive_sql import get_google_drive_creds


def google_drive_api(fn=None):
    decorator = google_api(service_label=GoogleApps.DRIVE.value)
    if fn is None: 
        return decorator
    return decorator(fn)


def get_google_drive_client_for_user(user_id: str, user_jwt: str): 
    return get_google_client_for_user(
        user_id=user_id, 
        user_jwt=user_jwt, 
        token_loader=get_google_drive_creds, 
        settings=get_google_drive_settings(), 
        api_service='drive', 
        api_version='v3', 
        service_label=GoogleApps.DRIVE.value,
    )
