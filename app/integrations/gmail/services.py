from typing import List, Literal

from app.utils.gmail_utils import gmail_api, get_gmail_client_for_user
from app.schemas.integration_schemas.gmail import GmailMessage, GmailSearchMessagesResponse, BatchedGmailMessages

import asyncio
import base64
from html import escape as html_escape


async def list_unread_messages(
    user_id: str,
    max_results: int = 10,
    page_token: str | None = None,
) -> GmailSearchMessagesResponse:
    return await search_messages(user_id=user_id, query="is:unread", max_results=max_results, page_token=page_token)


@gmail_api
def search_messages(
    user_id: str,
    query: str,
    max_results: int = 10,
    page_token: str | None = None,
) -> GmailSearchMessagesResponse:
    service = get_gmail_client_for_user(user_id=user_id)
    resp = (
        service.users()
        .messages()
        .list(
            userId="me",
            q=query,
            maxResults=max_results,
            pageToken=page_token,
        )
        .execute()
    )
    return GmailSearchMessagesResponse.model_validate(resp)


@gmail_api
def read_message_compact(user_id: str, message_id: str) -> GmailMessage: 
    service = get_gmail_client_for_user(user_id)
    message: dict = (
        service.users()
        .messages()
        .get(
            userId="me", 
            id=message_id, 
            format="metadata", 
            metadataHeaders=["From", "To", "Subject", "Date"], 
            fields="id,threadId,labelIds,snippet,payload(headers)"
        )
        .execute()
    )
    headers = message.pop('payload').get('headers', [])
    [message.update({h['name']: h['value']}) for h in headers]
    return GmailMessage(
        id=message.get('id'),
        thread_id=message.get('threadId'),
        label_ids=message.get('labelIds'),
        from_=message.get('From'),
        to=message.get('To'),
        subject=message.get('Subject'),
        date=message.get('Date'),
        msg_body=message.get('snippet')
    )


@gmail_api
def read_message_full(
    user_id: str,
    message_id: str,
) -> GmailMessage:
    service = get_gmail_client_for_user(user_id)
    message = (
        service.users()
        .messages()
        .get(
            userId="me", 
            id=message_id, 
            format="full", 
        )
        .execute()
    )

    def decode_body(data: str) -> str:
        padded = data + "=" * (-len(data) % 4)
        return base64.urlsafe_b64decode(padded.encode("utf-8")).decode("utf-8", errors="replace")
    
    def extract_part(payload: dict, mime_type: str) -> str | None:
        if payload.get("mimeType") == mime_type:
            body = payload.get("body") or {}
            data = body.get("data")
            if data:
                return decode_body(data)
        for part in payload.get("parts", []) or []:
            found = extract_part(part, mime_type)
            if found is not None:
                return found
        return None
    
    payload = message.get("payload") or {}
    headers = {h.get("name", "").lower(): h.get("value") for h in payload.get("headers", [])}
    html_body = extract_part(payload, "text/html")
    if html_body is not None:
        msg_body = html_body
    else:
        text_body = extract_part(payload, "text/plain")
        if text_body is not None:
            msg_body = f"<pre>{html_escape(text_body)}</pre>"
        else:
            msg_body = ""
    return GmailMessage(
        id=message.get("id"),
        thread_id=message.get("threadId"),
        label_ids=message.get("labelIds"),
        from_=headers.get("from"),
        to=headers.get("to"),
        subject=headers.get("subject"),
        date=headers.get("date"),
        msg_body=msg_body,
    )


async def batch_read_messages(user_id: str, messages_ids: List[str], format: Literal['compact', 'full'] = 'compact') -> BatchedGmailMessages: 
    fn = read_message_compact if format == 'compact' else read_message_full
    tasks = [fn(user_id, message_id) for message_id in messages_ids]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    error_msg_ids = []
    clean_results = []  
    for idx, res in enumerate(results): 
        if isinstance(res, Exception): 
            error_msg_ids.append(messages_ids[idx])
        else: 
            clean_results.append(res)
    return BatchedGmailMessages(messages=clean_results, error_messages=error_msg_ids)
