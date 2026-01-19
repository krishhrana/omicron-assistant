from app.agents import GmailAgent
from app.core.enums import SupportedApps
from app.integrations.gmail.tools import GMAIL_TOOLS, UserContext
from app.dependencies import startup
from app.utils.agent_utils import init_orchestrator_agent

from agents import RunConfig, Runner, ItemHelpers, ModelSettings
import asyncio


startup()

agent = init_orchestrator_agent(
            connected_apps=[SupportedApps.GMAIL],
            app_choice=SupportedApps.GMAIL,
        )

gmail_agent = GmailAgent(
    system_prompt="You are a gmail agent with access to user's gmail account with the provided tools. You help the users work with their gmail account, search the emails and answer questions", 
    tools=GMAIL_TOOLS, 
    model='gpt-5.2', 
    model_settings=ModelSettings(**{
        "reasoning": {
            "effort": "high", 
            "summary": "detailed",  
        }
    }),
    handoff_description="Handoff to this agent when the users asks questiosn about their gmail account"
)

async def run_agent(): 
    ctx = UserContext(user_id="dummy_user_id")
    while True: 
        query = input("Query: ")
        result = Runner.run_streamed(
            agent, query, 
            context=ctx,
            run_config=RunConfig(
                nest_handoff_history=False
            )
        )
        async for event in result.stream_events():
            if event.type == "agent_updated_stream_event":
                print("Switched to agent:", event.new_agent.name)
            elif event.type == "run_item_stream_event":
                if event.item.type == "tool_call_item":
                    print("Tool called")
                elif event.item.type == "tool_call_output_item":
                    print("Tool output:", event.item.output)
                elif event.item.type == 'reasoning_item': 
                    print("Reasoning:", event.item.raw_item.model_dump_json(indent=2))
                elif event.item.type == "message_output_item":
                    print("Message:", ItemHelpers.text_message_output(event.item))
        if query == "quit":
            break

asyncio.run(run_agent())
