from agents import ModelSettings

from app.agents.browser_agent import BrowserAgent
from app.agents.gmail_agent import GmailAgent
from app.agents.google_drive_agent import GoogleDriveAgent
from app.browser_sessions.controller_client import get_controller_client
from app.browser_sessions.lazy_mcp_server import LazyBrowserSessionMCPServer
from app.core.enums import SupportedApps
from app.core.settings import (
    get_browser_agent_settings,
    get_browser_session_controller_settings,
    get_gmail_agent_settings,
    get_google_drive_agent_settings,
)
from app.dependencies import get_browser_mcp_server


gmail_agent_settings = get_gmail_agent_settings()
google_drive_agent_settings = get_google_drive_agent_settings()
browser_agent_settings = get_browser_agent_settings()
browser_session_controller_settings = get_browser_session_controller_settings()


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


def init_browser_agent() -> BrowserAgent:
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


registered_agents = {
    SupportedApps.GMAIL.value: init_gmail_agent,
    SupportedApps.GOOGLE_DRIVE.value: init_google_drive_agent,
    SupportedApps.BROWSER.value: init_browser_agent,
}
