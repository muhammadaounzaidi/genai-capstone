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
    workflow.add_node("select_service", nodes.select_service_node)
    workflow.add_node("process_message", nodes.process_message_node)
    workflow.add_node("qualify_lead", nodes.qualify_lead_node)
    workflow.add_node("book_appointment", nodes.book_appointment_node)
    
    workflow.set_entry_point("create_lead")
    workflow.add_edge("create_lead", "select_service")
    workflow.add_edge("select_service", "process_message")
    workflow.add_edge("process_message", "qualify_lead")
    workflow.add_edge("qualify_lead", "book_appointment")
    workflow.add_edge("book_appointment", END)
    
    return workflow.compile()

