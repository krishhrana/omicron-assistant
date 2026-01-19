from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class GmailMessage(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    thread_id: str = Field(alias="threadId")
    label_ids: list[str] = Field(default_factory=list, alias="labelIds")
    from_: str | None = Field(default=None, alias="from")
    to: str | None = None
    subject: str | None = None
    date: str | None = None
    msg_body: str


class GmailMessageRef(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    thread_id: str = Field(alias="threadId")


class GmailSearchMessagesResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    messages: list[GmailMessageRef] = Field(default_factory=list)
    page_token: str | None = Field(default=None, validation_alias="nextPageToken")


class BatchedGmailMessages(BaseModel): 
    model_config = ConfigDict(populate_by_name=True)

    messages: list[GmailMessage] = Field(default_factory=list)
    error_messages: list[str] = Field(default_factory=list)
