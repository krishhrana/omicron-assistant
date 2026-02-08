from app.agents.orchestrator_agent import ORCHESTRATOR_HANDOFF_DESCRIPTION, ORCHESTRATOR_SYSTEM_PROMPT, OrchestratorAgent
from app.agents.registry import registered_agents
from app.core.enums import SupportedApps
from app.core.exceptions import AppNotConnectedError
from app.core.settings import get_orchestrator_agent_settings


from agents import Agent, ModelSettings


orch_agent_settings = get_orchestrator_agent_settings()


def init_orchestrator_agent(
    connected_apps: list[SupportedApps] | None = None,
    app_choice: SupportedApps | None = None,
) -> OrchestratorAgent:
    if connected_apps is None:
        connected_apps = list()

    if app_choice is not None and app_choice not in connected_apps:
            raise AppNotConnectedError(app_choice, connected_apps)

    sub_agents = get_sub_agents(connected_apps, app_choice)

    return OrchestratorAgent(
        system_prompt=ORCHESTRATOR_SYSTEM_PROMPT,
        model=orch_agent_settings.model,
        model_settings=ModelSettings(**{
            "reasoning": {
                "effort": orch_agent_settings.reasoning_effort,
                "summary": orch_agent_settings.reasoning_summary,
            }
        }),
        handoffs=sub_agents,
        handoff_description=ORCHESTRATOR_HANDOFF_DESCRIPTION,
    )


def get_sub_agents(connected_apps: list[SupportedApps], app_choice: SupportedApps = None) -> list[Agent]:
    if app_choice:
        return [registered_agents[app_choice.value]()]

    return [registered_agents[app.value]() for app in connected_apps]
