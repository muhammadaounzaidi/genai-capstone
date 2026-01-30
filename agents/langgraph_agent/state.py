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
    lead_qualified: bool
    pet_added: bool
    service_selected: Optional[str]
    invalid_service_requested: bool
    requested_service_name: Optional[str]
    appointment_details: Optional[dict]
    appointment_booked: bool
    available_slots: Optional[List]

