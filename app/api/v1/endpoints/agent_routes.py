import asyncio
import json
from datetime import datetime, timezone
import traceback
from typing import AsyncIterator, Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from agents import (
    AgentToolStreamEvent,
    OpenAIConversationsSession,
    Runner,
    ItemHelpers,
    RunConfig,
)
from agents.stream_events import StreamEvent

from openai.types.responses import ResponseReasoningSummaryTextDeltaEvent, ResponseReasoningSummaryTextDoneEvent

from app.auth import AuthContext, get_auth_context
from app.browser_sessions.controller_client import get_controller_client
from app.browser_sessions.lazy_mcp_server import LazyBrowserSessionMCPServer
from app.dependencies import get_openai_client
from app.utils.agent_utils import UserContext
from app.db.chat_sessions_sql import (
    create_chat_session_stub,
    get_chat_session,
    get_chat_session_by_conversation_id,
    upsert_chat_session,
    update_chat_session_by_id,
)
from app.schemas.endpoint_schemas.agent import AgentRunPayload
from app.agents.workflow import create_agent_workflow
from app.agents.registry import get_connected_apps
from app.utils.runtime_utils import heartbeat_loop, should_init_browser_heartbeat, cleanup_heartbeat_task



router = APIRouter()

_SSE_HEADERS = {
    # Prevent intermediary/proxy buffering for SSE where supported.
    "Cache-Control": "no-cache",
    "X-Accel-Buffering": "no",
}

_STREAM_END_SENTINEL = 'STREAM_END'


def _extract_tool_name(raw_item: Any) -> str | None:
    if isinstance(raw_item, dict):
        return raw_item.get("name") or raw_item.get("tool_name")
    return getattr(raw_item, "name", None) or getattr(raw_item, "tool_name", None)


def _format_event(event: StreamEvent) -> dict[str, Any] | None:
    if event.type == "raw_response_event":
        print(type(event.data))
        event_type = getattr(event.data, "type", None)
        if event_type == "response.output_text.delta":
            return {"type": "delta", "text": event.data.delta}
        if isinstance(event.data, ResponseReasoningSummaryTextDeltaEvent):
            print("In Reasoning Delta")
            return {"type": "reasoning_delta", "text": event.data.delta}
        if isinstance(event.data, ResponseReasoningSummaryTextDoneEvent): 
            return {"type": "reasoning_done"}
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
    connected_apps = get_connected_apps()
    controller_client = get_controller_client()
    now_iso = datetime.now(timezone.utc).isoformat()
    event_queue: asyncio.Queue[str | None] = asyncio.Queue()

    # Canonical session key for the product is Supabase chat_sessions.id (UUID).
    effective_session_id: str | None = None
    conversation_id: str | None = None
    should_set_title = False

    # Get or Create Session ID in Supabase
    if payload.session_id:
        effective_session_id = payload.session_id
        session_row = await get_chat_session(
            user_id=auth_ctx.user_id,
            user_jwt=auth_ctx.token,
            session_id=effective_session_id,
        )
        if not session_row:
            raise HTTPException(status_code=404, detail="Session not found")
        conversation_id = session_row.get("conversation_id")
    else:
        effective_session_id = await create_chat_session_stub(
            user_id=auth_ctx.user_id,
            user_jwt=auth_ctx.token,
            title=payload.query,
            last_message_at=now_iso,
        )
        should_set_title = True

    if not effective_session_id:
        raise HTTPException(status_code=500, detail="Failed to resolve session_id")

    user_ctx = UserContext(
        user_id=auth_ctx.user_id,
        user_jwt=auth_ctx.token,
        session_id=effective_session_id,
        connected_apps=connected_apps,
    )

    session = OpenAIConversationsSession(
        conversation_id=conversation_id,
        openai_client=get_openai_client(),
    )

    async def sub_agent_stream(event: AgentToolStreamEvent) -> None:
        payload_data = _format_event(event["event"])
        if payload_data is not None:
            payload_data["scope"] = "tool"
            payload_data["agent"] = event["agent"].name
            data = json.dumps(payload_data, default=str)
            await event_queue.put(f"data: {data}\n\n")

    agent = create_agent_workflow(
        connected_apps=user_ctx.connected_apps, 
        tool_on_stream=sub_agent_stream, 
        session=session
    )

    # agent = init_orchestrator_agent(
    #     connected_apps=user_ctx.connected_apps,
    #     tool_on_stream=sub_agent_stream,
    # )

    result = Runner.run_streamed(
        agent,
        payload.query,
        context=user_ctx,
        max_turns=100,
        session=session,
        run_config=RunConfig(
            nest_handoff_history=False
        ),
    )

    async def event_stream() -> AsyncIterator[str]:
        # Some proxies buffer small chunks; a comment preamble helps force an early flush.
        yield ":" + (" " * 2048) + "\n\n"

        # Emit Supabase chat_sessions.id early so the frontend can persist it immediately.
        yield f"data: {json.dumps({'type': 'session_id', 'session_id': effective_session_id})}\n\n"


        async def main_agent_stream() -> None:
            heartbeat_stop = asyncio.Event()
            heartbeat_task: asyncio.Task | None = None
            curr_agent = 'main'
            try:
                async for event in result.stream_events():
                    if should_init_browser_heartbeat(controller_client, heartbeat_task, event):
                        heartbeat_task = asyncio.create_task(heartbeat_loop(controller_client=controller_client, effective_session_id=effective_session_id, heartbeat_stop=heartbeat_stop))
                    payload_data = _format_event(event)
                    if payload_data is not None:
                        curr_agent = payload_data['agent'] if payload_data['type'] == 'agent_updated' else curr_agent
                        payload_data['agent'] = curr_agent
                        data = json.dumps(payload_data, default=str)
                        await event_queue.put(f"data: {data}\n\n")
            finally:
                heartbeat_stop.set()
                await cleanup_heartbeat_task(heartbeat_task)
                # Wake the SSE loop once the main stream is fully stopped/cleaned up.
                await event_queue.put(_STREAM_END_SENTINEL)

        main_agent_stream_task = asyncio.create_task(main_agent_stream())
        try:
            while True:
                msg = await event_queue.get()
                print(msg)
                print('--------\n')
                if msg == _STREAM_END_SENTINEL:
                    break
                yield msg
        except asyncio.CancelledError:
            main_agent_stream_task.cancel()
            raise
        finally:
            if not main_agent_stream_task.done():
                main_agent_stream_task.cancel()
            try:
                await main_agent_stream_task
            except asyncio.CancelledError:
                pass
            except Exception as exc:
                print(f"agent stream task failed: {traceback.format_exc()}")
        
        openai_conversation_id = await session._get_session_id()
        try:
            await update_chat_session_by_id(
                session_id=effective_session_id,
                user_id=auth_ctx.user_id,
                user_jwt=auth_ctx.token,
                conversation_id=openai_conversation_id,
                title=payload.query if should_set_title else None,
                last_message_at=datetime.now(timezone.utc).isoformat(),
            )
        except Exception as exc:
            print(f"Failed to update chat session: {exc}")

        # Best-effort: clean up per-run MCP client sessions (do not touch global dev MCP server).
        try:
            for sub_agent in getattr(agent, "handoffs", []) or []:
                for server in getattr(sub_agent, "mcp_servers", []) or []:
                    if isinstance(server, LazyBrowserSessionMCPServer):
                        await server.cleanup()
        except Exception as exc:
            print(f"browser MCP cleanup failed: {exc}")

        # Backwards-compatible: also emit session_id at the end.
        # yield f"data: {json.dumps({'type': 'session_id', 'session_id': effective_session_id})}\n\n"
        yield "data: [DONE]\n\n"
    return StreamingResponse(event_stream(), media_type="text/event-stream", headers=_SSE_HEADERS)
