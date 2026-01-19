from pydantic import BaseModel

from app.core.enums import SupportedApps

class AgentRunPayload(BaseModel): 
    query: str
    app: SupportedApps | None = None
    session_id: str | None = None
