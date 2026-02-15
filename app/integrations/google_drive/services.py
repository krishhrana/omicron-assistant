from fastapi.concurrency import run_in_threadpool

from app.schemas.integration_schemas.google_drive import GoogleDriveSearchFilesResponse
from app.utils.google_drive_utils import get_google_drive_client_for_user, google_drive_api


@google_drive_api
async def search_files(
        user_id: str,
        user_jwt: str,
        query: str, 
        max_results: int = 10,
        page_token: str | None = None, 
) -> GoogleDriveSearchFilesResponse:
    service = await get_google_drive_client_for_user(user_id=user_id, user_jwt=user_jwt)
    resp = await run_in_threadpool(
        lambda: service.files().list(
            q=query, 
            fields="files(kind,id,name,modifiedTime,mimeType,webViewLink), nextPageToken",
            pageSize=max_results, 
            spaces="drive",
            pageToken=page_token,
            supportsAllDrives=True,
            includeItemsFromAllDrives=True,
        ).execute()
    )
    return GoogleDriveSearchFilesResponse.model_validate(resp)
