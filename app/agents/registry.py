from typing import Any, Callable, List, TypedDict

from agents import Handoff, ModelSettings, Tool

from app.agents.base_agent import BaseAgent
from app.agents.browser_agent import BrowserAgent
from app.agents.gmail_agent import GmailAgent
from app.agents.google_drive_agent import GoogleDriveAgent
from app.agents.orchestrator_agent import OrchestratorAgent
from app.browser_sessions.controller_client import get_controller_client
from app.browser_sessions.lazy_mcp_server import LazyBrowserSessionMCPServer
from app.core.enums import SupportedApps
from app.core.settings import (
    get_browser_agent_settings,
    get_browser_session_controller_settings,
    get_gmail_agent_settings,
    get_google_drive_agent_settings,
    get_orchestrator_agent_settings
)
from app.dependencies import get_browser_mcp_server


class AgentAttributes(TypedDict):
    name: str
    initializer: Callable[..., BaseAgent]
    handoff_enabled: bool
    can_gather_user_data: bool
    verify_connected: bool = False



gmail_agent_settings = get_gmail_agent_settings()
google_drive_agent_settings = get_google_drive_agent_settings()
browser_agent_settings = get_browser_agent_settings()
browser_session_controller_settings = get_browser_session_controller_settings()
orch_agent_settings = get_orchestrator_agent_settings()



def init_gmail_agent() -> GmailAgent:
    return GmailAgent(
        model=gmail_agent_settings.model,
        model_settings=ModelSettings(
            **{
                "reasoning": {
                    "effort": gmail_agent_settings.reasoning_effort,
                    "summary": gmail_agent_settings.reasoning_summary,
                }
            }
        ),
    )


def init_google_drive_agent() -> GoogleDriveAgent:
    return GoogleDriveAgent(
        model=google_drive_agent_settings.model,
        model_settings=ModelSettings(
            **{
                "reasoning": {
                    "effort": google_drive_agent_settings.reasoning_effort,
                    "summary": google_drive_agent_settings.reasoning_summary,
                }
            }
        ),
    )


def init_browser_agent(handoffs: List[BaseAgent] | None = None) -> BrowserAgent:
    controller = get_controller_client()
    return BrowserAgent(
        model=browser_agent_settings.model,
        model_settings=ModelSettings(
            **{
                "reasoning": {
                    "effort": browser_agent_settings.reasoning_effort,
                    "summary": browser_agent_settings.reasoning_summary,
                }
            }
        ),
        mcp_servers=(
            [
                LazyBrowserSessionMCPServer(
                    controller=controller,
                    mcp_timeout=browser_agent_settings.playwright_mcp_timeout,
                    mcp_sse_read_timeout=browser_agent_settings.playwright_mcp_sse_read_timeout,
                    client_session_timeout_seconds=browser_agent_settings.playwright_mcp_client_session_timeout_seconds,
                    max_retry_attempts=browser_agent_settings.playwright_mcp_max_retry_attempts,
                )
            ]
            if controller is not None
            else [get_browser_mcp_server()]
        ),
        handoffs=handoffs,
    )

def init_orchestrator_agent(
    tools: list[Tool] | None = None,
    handoffs: list[BaseAgent] | list[Handoff] | None = None,
) -> OrchestratorAgent:
    return OrchestratorAgent(
        model=orch_agent_settings.model,
        model_settings=ModelSettings(**{
            "reasoning": {
                "effort": orch_agent_settings.reasoning_effort,
                "summary": orch_agent_settings.reasoning_summary,
            }
        }),
        tools=tools,
        handoffs=handoffs,
    )


def is_browser_connected() -> bool:
    if browser_session_controller_settings.url and browser_session_controller_settings.jwt_secret:
        return True
    try:
        get_browser_mcp_server()
        return True
    except RuntimeError:
        return False


def get_connected_apps() -> list[SupportedApps]:
    apps = [SupportedApps.GMAIL, SupportedApps.GOOGLE_DRIVE]
    if is_browser_connected():
        apps.append(SupportedApps.BROWSER)
    return apps


registered_agents: List[AgentAttributes] = [
    AgentAttributes(
        name=SupportedApps.GMAIL.value,
        initializer=init_gmail_agent,
        handoff_enabled=GmailAgent.HANDOFF_ENABLED,
        can_gather_user_data=GmailAgent.CAN_GATHER_USER_DATA,
        verify_connected=True,
    ),
    AgentAttributes(
        name=SupportedApps.GOOGLE_DRIVE.value,
        initializer=init_google_drive_agent,
        handoff_enabled=GoogleDriveAgent.HANDOFF_ENABLED,
        can_gather_user_data=GoogleDriveAgent.CAN_GATHER_USER_DATA,
        verify_connected=True,
    ),
    AgentAttributes(
        name=SupportedApps.BROWSER.value,
        initializer=init_browser_agent,
        handoff_enabled=BrowserAgent.HANDOFF_ENABLED,
        can_gather_user_data=BrowserAgent.CAN_GATHER_USER_DATA,
        verify_connected=True,
    ),
    AgentAttributes(
        name=OrchestratorAgent.name, 
        initializer=init_orchestrator_agent,
        handoff_enabled=OrchestratorAgent.HANDOFF_ENABLED,
        can_gather_user_data=OrchestratorAgent.CAN_GATHER_USER_DATA,
        verify_connected=False
    )
]
