"""LangGraph agent implementation wrapper."""
import logging
from typing import Dict, Any
from agents.base import BaseAgent
from agents.langgraph_agent.graph import create_agent_graph
from agents.langgraph_agent.state import AgentState
from services.google_sheets_service import GoogleSheetsService

logger = logging.getLogger(__name__)


class LangGraphAgent(BaseAgent):
    """LangGraph-based agent implementation following SRP."""
    
    def __init__(self, sheets_service: GoogleSheetsService):
        """Initialize the LangGraph agent.
        
        Args:
            sheets_service: Google Sheets service instance
        """
        self.sheets_service = sheets_service
        self.graph = create_agent_graph(sheets_service)
    
    async def process_message(
        self,
        user_id: str,
        username: str,
        message: str,
        conversation_history: list = None
    ) -> Dict[str, Any]:
        """Process a user message using LangGraph.
        
        Args:
            user_id: Unique identifier for the user
            username: Username of the user
            message: The message content from the user
            conversation_history: Optional list of previous messages
            
        Returns:
            Dictionary containing response and state information
        """
        try:
            # Build messages list
            messages = conversation_history if conversation_history else []
            messages.append({
                "role": "user",
                "content": message,
            })
            
            # Check if this is the first message (lead needs to be created)
            is_first_message = len(messages) == 1
            
            # Create initial state
            state: AgentState = {
                "user_id": user_id,
                "username": username,
                "messages": messages,
                "lead_created": not is_first_message,  # Lead already created if not first message
                "current_step": "initiated" if is_first_message else "conversation",
                "collected_info": {},
                "service_selected": None,
                "appointment_details": None,
            }
            
            # Run the agent graph
            result = await self.graph.ainvoke(state)
            
            # Extract response
            response_messages = result.get("messages", [])
            last_message = response_messages[-1] if response_messages else None
            
            return {
                "response": last_message.get("content", "I'm here to help!") if last_message else "I'm here to help!",
                "state": result,
                "lead_created": result.get("lead_created", False),
            }
            
        except Exception as e:
            logger.error(f"Error processing message with LangGraph agent: {e}")
            return {
                "response": "I apologize, but I encountered an error. Please try again.",
                "state": {},
                "lead_created": False,
            }
    
    def create_lead(self, user_id: str, username: str, message: str) -> Dict[str, Any]:
        """Create a new lead record.
        
        Args:
            user_id: Unique identifier for the user
            username: Username of the user
            message: Initial message from the user
            
        Returns:
            Dictionary containing lead information
        """
        try:
            return self.sheets_service.create_lead(
                user_id=user_id,
                username=username,
                message=message,
            )
        except Exception as e:
            logger.error(f"Error creating lead: {e}")
            raise

