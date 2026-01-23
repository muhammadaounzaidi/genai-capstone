"""Agent nodes for LangGraph workflow."""
import logging
from typing import Dict
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage, AIMessage
from agents.langgraph_agent.state import AgentState
from services.google_sheets_service import GoogleSheetsService
from config import Config

logger = logging.getLogger(__name__)


class AgentNodes:
    """Agent nodes following SRP - each node has a single responsibility."""
    
    def __init__(self, sheets_service: GoogleSheetsService):
        """Initialize agent nodes with dependencies.
        
        Args:
            sheets_service: Google Sheets service instance
        """
        self.sheets_service = sheets_service
        self.llm = ChatGoogleGenerativeAI(
            model="gemini-pro",
            google_api_key=Config.GOOGLE_API_KEY,
            temperature=0.7,
        )
    
    def create_lead_node(self, state: AgentState) -> Dict:
        """Create a new lead when user sends first message.
        
        Args:
            state: Current agent state
            
        Returns:
            Updated state with lead_created flag
        """
        if state.get("lead_created", False):
            logger.info(f"Lead already created for user {state['user_id']}")
            return {"lead_created": True}
        
        try:
            messages = state.get("messages", [])
            if not messages:
                logger.warning("No messages in state to create lead")
                return {"lead_created": False}
            
            # Get the first user message
            first_message = messages[0].get("content", "") if messages else ""
            
            # Create lead in Google Sheets
            lead_data = self.sheets_service.create_lead(
                user_id=state["user_id"],
                username=state["username"],
                message=first_message,
            )
            
            logger.info(f"Successfully created lead for {state['username']}")
            return {
                "lead_created": True,
                "current_step": "greeting",
            }
            
        except Exception as e:
            logger.error(f"Error creating lead: {e}")
            return {"lead_created": False}
    
    def process_message_node(self, state: AgentState) -> Dict:
        """Process user message and generate response.
        
        Args:
            state: Current agent state
            
        Returns:
            Updated state with AI response
        """
        try:
            messages = state.get("messages", [])
            if not messages:
                return {}
            
            # Convert messages to LangChain format
            langchain_messages = []
            for msg in messages:
                if msg.get("role") == "user":
                    langchain_messages.append(HumanMessage(content=msg.get("content", "")))
                elif msg.get("role") == "assistant":
                    langchain_messages.append(AIMessage(content=msg.get("content", "")))
            
            # Add system context
            system_prompt = self._get_system_prompt()
            langchain_messages.insert(0, HumanMessage(content=system_prompt))
            
            # Get response from LLM
            response = self.llm.invoke(langchain_messages)
            
            # Add assistant response to messages
            new_messages = messages + [{
                "role": "assistant",
                "content": response.content,
            }]
            
            return {
                "messages": new_messages,
            }
            
        except Exception as e:
            logger.error(f"Error processing message: {e}")
            return {
                "messages": state.get("messages", []) + [{
                    "role": "assistant",
                    "content": "I apologize, but I encountered an error. Please try again.",
                }],
            }
    
    def _get_system_prompt(self) -> str:
        """Get the system prompt for the agent."""
        return """You are a friendly and professional assistant for a pet grooming business. 
Your role is to:
1. Greet customers warmly
2. Collect information about their pets (name, breed, size, special needs)
3. Provide information about available services and prices
4. Help book appointments

Be conversational, helpful, and professional. Ask one question at a time to avoid overwhelming the customer.
Keep responses concise and friendly."""

