"""LangGraph workflow definition."""
from langgraph.graph import StateGraph, END
from agents.langgraph_agent.state import AgentState
from agents.langgraph_agent.nodes import AgentNodes
from services.google_sheets_service import GoogleSheetsService


def create_agent_graph(sheets_service: GoogleSheetsService):
    """Create the LangGraph workflow for the grooming business agent.
    
    Args:
        sheets_service: Google Sheets service instance
        
    Returns:
        Compiled LangGraph graph
    """
    nodes = AgentNodes(sheets_service)
    
    # Create the graph
    workflow = StateGraph(AgentState)
    
    # Add nodes
    workflow.add_node("create_lead", nodes.create_lead_node)
    workflow.add_node("process_message", nodes.process_message_node)
    workflow.add_node("qualify_lead", nodes.qualify_lead_node)
    
    # Define the flow
    workflow.set_entry_point("create_lead")
    workflow.add_edge("create_lead", "process_message")
    workflow.add_edge("process_message", "qualify_lead")
    workflow.add_edge("qualify_lead", END)
    
    # Compile the graph
    app = workflow.compile()
    return app

