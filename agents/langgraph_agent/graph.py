"""LangGraph workflow definition."""
from langgraph.graph import StateGraph, END
from agents.langgraph_agent.state import AgentState
from agents.langgraph_agent.nodes import AgentNodes
from services.google_sheets_service import GoogleSheetsService


def create_agent_graph(sheets_service: GoogleSheetsService, calendar_service=None):
    """Create the LangGraph workflow for the grooming business agent.
    
    Args:
        sheets_service: Google Sheets service instance
        calendar_service: Optional Google Calendar service for booking
        
    Returns:
        Compiled LangGraph graph
    """
    nodes = AgentNodes(sheets_service, calendar_service)
    
    workflow = StateGraph(AgentState)
    
    workflow.add_node("create_lead", nodes.create_lead_node)
    workflow.add_node("process_message", nodes.process_message_node)
    workflow.add_node("sync_to_sheets", nodes.sync_to_sheets_node)
    
    workflow.set_entry_point("create_lead")
    workflow.add_edge("create_lead", "process_message")
    workflow.add_edge("process_message", "sync_to_sheets")
    workflow.add_edge("sync_to_sheets", END)
    
    return workflow.compile()

