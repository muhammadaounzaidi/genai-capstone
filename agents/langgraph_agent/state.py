"""State management for the LangGraph agent."""
from typing import TypedDict, List, Optional


class AgentState(TypedDict):
    """State structure for the LangGraph grooming business agent."""
    user_id: str
    username: str
    messages: List[dict]
    lead_created: bool
    current_step: str
    collected_info: dict
    service_selected: Optional[str]
    appointment_details: Optional[dict]

