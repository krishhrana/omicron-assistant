from pydantic import BaseModel

class AgentRunPayload(BaseModel): 
    query: str
    session_id: str | None = None
