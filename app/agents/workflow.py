from typing import Any, Callable

from app.agents.base_agent import BaseAgent
from app.agents.orchestrator_agent import ORCHESTRATOR_SYSTEM_PROMPT, OrchestratorAgent
from app.agents.registry import init_orchestrator_agent, registered_agents
from app.core.enums import SupportedApps
from app.core.settings import get_orchestrator_agent_settings
from agents import ModelSettings


# orch_agent_settings = get_orchestrator_agent_settings()

# def get_sub_agents(connected_apps: list[SupportedApps]) -> list[BaseAgent]:
#     connected = {app.value for app in connected_apps}
#     sub_agents: list[BaseAgent] = []
#     for attrs in registered_agents:
#         if attrs["name"] not in connected:
#             continue
#         sub_agents.append(attrs["initializer"]())
#     return sub_agents


# def init_orchestrator_agent(
#     connected_apps: list[SupportedApps] | None = None,
#     tool_on_stream: Callable[..., Any] | None = None,
# ) -> OrchestratorAgent:
#     if connected_apps is None:
#         connected_apps = list()

#     sub_agents = get_sub_agents(connected_apps)

#     return OrchestratorAgent(
#         system_prompt=ORCHESTRATOR_SYSTEM_PROMPT,
#         model=orch_agent_settings.model,
#         model_settings=ModelSettings(**{
#             "reasoning": {
#                 "effort": orch_agent_settings.reasoning_effort,
#                 "summary": orch_agent_settings.reasoning_summary,
#             }
#         }),
#         tools=[
#             agent.as_tool(tool_name=agent.name, tool_description=agent.handoff_description, on_stream=tool_on_stream)
#             for agent in sub_agents
#             if agent.can_gather_user_data
#         ],
#         handoffs=[agent for agent in sub_agents if agent.handoff_enabled],
#     )


def create_agent_workflow(
        connected_apps: list[SupportedApps] | None = None, 
        tool_on_stream: Callable[..., Any] | None = None,
        session: Any | None = None,
):
    """
    Agent Arch: 
    1. User Data Gathering Agents are connected as tools to Main Agent
    2. All Handoff enabled Agents are connected to each other and the Main agent

    Roles: 
    1. Main Agent: 
        1. Responsible for calling User specific Apps (Agents)
    2. Handoff Agents: 
        1. Can perform Auxilary fucntions for Users Like Web Browsing, etc. 
        2. Need to hand control back to Main Agent to interact with User Connectd Apps.
    """
    available_agents = registered_agents.copy()
    if connected_apps is not None:
        available_agents = [
            agent for agent in available_agents if (not agent['verify_connected']) or (agent['verify_connected'] and agent['name'] in {app.value for app in connected_apps})
        ]
    agent_as_tools = [
        agent['initializer']()
        .as_tool(
            tool_name=None, 
            tool_description=None,
            on_stream=tool_on_stream,
            session=session,
            max_turns=100
        )
        for agent in available_agents
        if agent['can_gather_user_data']
    ]


    agent_as_handoffs = [
        agent['initializer']()
        for agent in available_agents
        if agent['handoff_enabled']
        if agent['name'] != OrchestratorAgent.name
    ]

    main_agent = init_orchestrator_agent(
        tools=agent_as_tools,
        handoffs=agent_as_handoffs,
    )

    for agent in agent_as_handoffs: 
        agent.handoffs = [hf for hf in agent_as_handoffs if hf.name != agent.name]
        agent.handoffs.append(main_agent)

    return main_agent
    


