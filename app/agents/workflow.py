from app.agents.orchestrator_agent import ORCHESTRATOR_HANDOFF_DESCRIPTION, ORCHESTRATOR_SYSTEM_PROMPT, OrchestratorAgent
from app.agents.registry import registered_agents
from app.core.enums import SupportedApps
from app.core.settings import get_orchestrator_agent_settings


from agents import Agent, ModelSettings


orch_agent_settings = get_orchestrator_agent_settings()


def init_orchestrator_agent(
    connected_apps: list[SupportedApps] | None = None,
) -> OrchestratorAgent:
    if connected_apps is None:
        connected_apps = list()

    sub_agents = get_sub_agents(connected_apps)

    return OrchestratorAgent(
        system_prompt=ORCHESTRATOR_SYSTEM_PROMPT,
        model=orch_agent_settings.model,
        model_settings=ModelSettings(**{
            "reasoning": {
                "effort": orch_agent_settings.reasoning_effort,
                "summary": orch_agent_settings.reasoning_summary,
            }
        }),
        tools = [
            agent.as_tool() for agent in sub_agents
        ]
        # handoffs=sub_agents,
        # handoff_description=ORCHESTRATOR_HANDOFF_DESCRIPTION,
    )


def get_sub_agents(connected_apps: list[SupportedApps]) -> list[Agent]:
    return [registered_agents[app.value]() for app in connected_apps]
