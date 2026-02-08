from agents import ModelSettings

from app.agents.gmail_agent import GmailAgent
from app.agents.google_drive_agent import GoogleDriveAgent
from app.core.enums import SupportedApps
from app.core.settings import get_gmail_agent_settings, get_google_drive_agent_settings


gmail_agent_settings = get_gmail_agent_settings()
google_drive_agent_settings = get_google_drive_agent_settings()


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


registered_agents = {
    SupportedApps.GMAIL.value: init_gmail_agent,
    SupportedApps.GOOGLE_DRIVE.value: init_google_drive_agent,
}
