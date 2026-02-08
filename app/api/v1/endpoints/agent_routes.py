import asyncio
import json
from typing import AsyncIterator, Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from agents import (
    OpenAIConversationsSession,
    Runner,
    ItemHelpers,
    RunConfig,
)
from agents.stream_events import StreamEvent

from app.core.enums import SupportedApps
from app.core.exceptions import AppNotConnectedError
from app.auth import AuthContext, get_auth_context
from app.dependencies import get_openai_client
from app.integrations.gmail.tools import UserContext
from app.schemas.endpoint_schemas.agent import AgentRunPayload
from app.agents.workflow import init_orchestrator_agent


router = APIRouter()


def _extract_tool_name(raw_item: Any) -> str | None:
    if isinstance(raw_item, dict):
        return raw_item.get("name") or raw_item.get("tool_name")
    return getattr(raw_item, "name", None) or getattr(raw_item, "tool_name", None)


def _format_event(event: StreamEvent) -> dict[str, Any] | None:
    if event.type == "raw_response_event":
        event_type = getattr(event.data, "type", None)
        if event_type == "response.output_text.delta":
            return {"type": "delta", "text": event.data.delta}
        return None
    if event.type == "agent_updated_stream_event":
        return {"type": "agent_updated", "agent": event.new_agent.name}
    if event.type == "run_item_stream_event":
        if event.name == "message_output_created":
            return {"type": "message", "text": ItemHelpers.text_message_output(event.item)}
        if event.name == "tool_called":
            return {"type": "tool_called", "tool": _extract_tool_name(event.item.raw_item)}
        if event.name == "tool_output":
            return {"type": "tool_output", "output": event.item.output}
        if event.item.type == 'reasoning_item':
            return {"type": "reasoning", "reasoning": event.item.raw_item.model_dump_json()}
        if event.name == "handoff_occured":
            target = getattr(event.item, "target_agent", None)
            return {"type": "handoff", "agent": getattr(target, "name", None)}
    return None


@router.post('/run-agent')
async def run_agent(
    payload: AgentRunPayload,
    auth_ctx: AuthContext = Depends(get_auth_context),
):
    user_ctx = UserContext(
        user_id=auth_ctx.user_id,
        user_jwt=auth_ctx.token,
        connected_apps=[SupportedApps.GMAIL, SupportedApps.GOOGLE_DRIVE],
    )
    session = OpenAIConversationsSession(
        conversation_id=payload.session_id,
        openai_client=get_openai_client(),
    )
    try:
        agent = init_orchestrator_agent(
            connected_apps=user_ctx.connected_apps,
            app_choice=payload.app,
        )
    except AppNotConnectedError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    result = Runner.run_streamed(
        agent,
        payload.query,
        context=user_ctx,
        max_turns=50,
        session=session,
        run_config=RunConfig(
            nest_handoff_history=False
        ),
    )

    async def event_stream() -> AsyncIterator[str]:
        try:
            async for event in result.stream_events():
                payload_data = _format_event(event)
                if payload_data is None:
                    continue
                data = json.dumps(payload_data, default=str)
                print(data)
                yield f"data: {data}\n\n"
        except asyncio.CancelledError:
            return
        yield json.dumps({"type": "session_id", "session_id": await session._get_session_id() if session else ''}) + '\n\n'
        yield "data: [DONE]\n\n"
    return StreamingResponse(event_stream(), media_type="text/event-stream")
