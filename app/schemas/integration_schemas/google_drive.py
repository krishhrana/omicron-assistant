from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class GoogleDriveFile(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    kind: str | None = None
    id: str
    name: str | None = None
    mime_type: str | None = Field(default=None, alias="mimeType")
    web_view_link: str | None = Field(default=None, alias="webViewLink")
    modified_time: str | None = Field(default=None, alias="modifiedTime")


class GoogleDriveSearchFilesResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    files: list[GoogleDriveFile] = Field(default_factory=list)
    next_page_token: str | None = Field(default=None, validation_alias="nextPageToken")
