
from asyncio import Task
import asyncio

from agents import StreamEvent
from app.browser_sessions.controller_client import BrowserSessionControllerClient


def should_init_browser_heartbeat(
        controller_client: BrowserSessionControllerClient | None, 
        heartbeat_task: Task | None,
        event: StreamEvent | None
): 
    return (
        controller_client is not None
        and heartbeat_task is None
        and (
            (
                event.type == "agent_updated_stream_event"
                and getattr(getattr(event, "new_agent", None), "name", None) == "browser_agent"
            )
            or (
                event.type == "run_item_stream_event"
                and event.name == "handoff_occured"
                and getattr(getattr(getattr(event, "item", None), "target_agent", None), "name", None)
                == "browser_agent"
            )
        )
    )


async def heartbeat_loop(
        controller_client: BrowserSessionControllerClient, 
        effective_session_id: str, 
        heartbeat_stop: asyncio.Event
) -> None:
    assert controller_client is not None
    while not heartbeat_stop.is_set():
        try:
            await controller_client.heartbeat(session_id=effective_session_id)
        except Exception as exc:
            print(f"browser session heartbeat failed: {exc}")
        try:
            await asyncio.wait_for(heartbeat_stop.wait(), timeout=30)
        except asyncio.TimeoutError:
            continue


async def cleanup_heartbeat_task(heartbeat_task: Task | None):
    if heartbeat_task is not None:
        if not heartbeat_task.done():
            heartbeat_task.cancel()
        try:
            await heartbeat_task
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            print(f"browser session heartbeat task failed: {exc}") 
    

