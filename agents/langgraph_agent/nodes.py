"""Agent nodes for LangGraph workflow."""
import json
import logging
import re
import traceback
from typing import Dict, Optional
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
            model="gemini-2.5-flash",
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
        user_id = state.get("user_id")
        
        # Check if lead already exists in database
        if self.sheets_service.lead_exists(user_id):
            logger.info(f"Lead already exists for user {user_id}")
            return {"lead_created": True}
        
        # Also check state flag (for cases where state is already set)
        if state.get("lead_created", False):
            logger.info(f"Lead already created (from state) for user {user_id}")
            return {"lead_created": True}
        
        messages = state.get("messages", [])
        if not messages:
            logger.warning("No messages in state to create lead")
            return {"lead_created": False}
        
        try:
            first_message = messages[0].get("content", "") if messages else ""
            self.sheets_service.create_lead(
                user_id=user_id,
                username=state["username"],
                message=first_message,
            )
            logger.info(f"Successfully created lead for {state['username']}")
            return {"lead_created": True, "current_step": "greeting"}
        except Exception as e:
            logger.error(f"Error creating lead for user {user_id}: {e}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            return {"lead_created": False}
    
    def process_message_node(self, state: AgentState) -> Dict:
        """Process user message and generate response.
        
        Args:
            state: Current agent state
            
        Returns:
            Updated state with AI response
        """
        messages = state.get("messages", [])
        if not messages:
            return {}
        
        try:
            langchain_messages = []
            for msg in messages:
                if msg.get("role") == "user":
                    langchain_messages.append(HumanMessage(content=msg.get("content", "")))
                elif msg.get("role") == "assistant":
                    langchain_messages.append(AIMessage(content=msg.get("content", "")))
            
            system_prompt = self._get_system_prompt()
            langchain_messages.insert(0, HumanMessage(content=system_prompt))
            
            response = self.llm.invoke(langchain_messages)
            
            return {
                "messages": messages + [{
                    "role": "assistant",
                    "content": response.content,
                }],
            }
        except Exception as e:
            logger.error(f"Error processing message: {e}")
            return {
                "messages": messages + [{
                    "role": "assistant",
                    "content": "I apologize, but I encountered an error. Please try again.",
                }],
            }
    
    def qualify_lead_node(self, state: AgentState) -> Dict:
        """Qualify the lead by collecting user and pet details.
        
        This node extracts user details (name, phone) and pet details (breed, weight, age, coat)
        from the conversation and updates the lead status to 'qualified'.
        
        Args:
            state: Current agent state
            
        Returns:
            Updated state with lead_qualified flag
        """
        if state.get("lead_qualified", False):
            logger.info(f"Lead already qualified for user {state['user_id']}")
            return {"lead_qualified": True}
        
        if not state.get("lead_created", False):
            logger.warning(f"Lead not created yet for user {state['user_id']}, skipping qualification")
            return {"lead_qualified": False}
        
        messages = state.get("messages", [])
        if not messages:
            logger.warning("No messages in state to qualify lead")
            return {"lead_qualified": False}
        
        try:
            qualification_info = self._extract_qualification_info(messages)
            
            if qualification_info:
                success = self.sheets_service.qualify_lead(
                    user_id=state["user_id"],
                    name=qualification_info.get("name"),
                    phone=qualification_info.get("phone"),
                    pet_breed=qualification_info.get("pet_breed"),
                    pet_weight=qualification_info.get("pet_weight"),
                    pet_age=qualification_info.get("pet_age"),
                    pet_coat=qualification_info.get("pet_coat"),
                )
                
                if success:
                    logger.info(f"Successfully qualified lead for {state['username']}")
                    collected_info = state.get("collected_info", {})
                    collected_info.update(qualification_info)
                    return {
                        "lead_qualified": True,
                        "current_step": "qualified",
                        "collected_info": collected_info,
                    }
                else:
                    logger.error(f"Failed to update lead qualification for {state['username']}")
                    return {"lead_qualified": False}
            else:
                logger.info(f"Insufficient information to qualify lead for {state['username']}")
                return {"lead_qualified": False}
        except Exception as e:
            error_msg = str(e) if str(e) else f"{type(e).__name__}: No error message available"
            logger.error(f"Error qualifying lead for user {state.get('user_id', 'unknown')}: {error_msg}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            return {"lead_qualified": False}
    
    def _extract_qualification_info(self, messages: list) -> Optional[Dict]:
        """Extract qualification information from conversation messages.
        
        Args:
            messages: List of conversation messages
            
        Returns:
            Dictionary with extracted information or None if insufficient
        """
        conversation_text = "\n".join([
            f"{msg.get('role', 'unknown')}: {msg.get('content', '')}"
            for msg in messages
        ])
        
        extraction_prompt = f"""Extract the following information from this conversation about a pet grooming lead:

User Information:
- name: The customer's name
- phone: The customer's phone number

Pet Information:
- pet_breed: The pet's breed (e.g., Golden Retriever, Persian Cat)
- pet_weight: The pet's weight (e.g., 25 lbs, 10 kg)
- pet_age: The pet's age (e.g., 3 years, 18 months)
- pet_coat: The pet's coat type (e.g., short, long, curly, double coat)

Conversation:
{conversation_text}

CRITICAL: You must return ONLY a valid JSON object. Do not include any markdown formatting, code blocks, or explanatory text. Return ONLY the JSON object itself.

Use null for any missing information. Example format:
{{
    "name": "John Doe",
    "phone": "555-1234",
    "pet_breed": "Golden Retriever",
    "pet_weight": "25 lbs",
    "pet_age": "3 years",
    "pet_coat": "long"
}}

If you cannot extract at least the user's name and phone, return the string "null" (not a JSON null value)."""
        
        try:
            response = self.llm.invoke([HumanMessage(content=extraction_prompt)])
            response_text = response.content.strip()
            
            if response_text.lower() == "null" or not response_text:
                return None
            
            # Clean the response - remove markdown code blocks if present
            response_text = self._clean_json_response(response_text)
            qualification_info = json.loads(response_text)
            
            if not isinstance(qualification_info, dict):
                return None
            
            name = qualification_info.get("name")
            phone = qualification_info.get("phone")
            
            if not name or not phone:
                return None
            
            return {
                "name": name,
                "phone": phone,
                "pet_breed": qualification_info.get("pet_breed"),
                "pet_weight": qualification_info.get("pet_weight"),
                "pet_age": qualification_info.get("pet_age"),
                "pet_coat": qualification_info.get("pet_coat"),
            }
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse qualification info JSON: {e}")
            logger.error(f"Response text was: {response_text[:500] if 'response_text' in locals() else 'N/A'}")
            return None
        except Exception as e:
            logger.error(f"Error extracting qualification info: {e}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            return None
    
    def _clean_json_response(self, text: str) -> str:
        """Clean JSON response by removing markdown code blocks and extra text.
        
        Args:
            text: Raw response text from LLM
            
        Returns:
            Cleaned JSON string
        """
        # Remove markdown code blocks (handle both ```json and ```)
        text = re.sub(r'```json\s*', '', text, flags=re.IGNORECASE)
        text = re.sub(r'```\s*', '', text)
        
        # Remove any leading/trailing whitespace
        text = text.strip()
        
        # Find JSON object in the text (handle nested objects)
        # Try to find the outermost JSON object
        json_match = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', text, re.DOTALL)
        if json_match:
            return json_match.group(0)
        
        # If no JSON object found, try to find if it's just "null" string
        if text.lower().strip() == "null":
            return "null"
        
        # Return cleaned text as fallback
        return text.strip()
    
    def _get_system_prompt(self) -> str:
        """Get the system prompt for the agent."""
        return """You are a friendly and professional assistant for Pawsitive Grooming, a pet grooming business. 
Your role is to:
1. Greet customers warmly with a friendly greeting like: "Hello there! Welcome to Pawsitive Grooming! I'm happy to help you today."
2. Qualify leads by collecting:
   - Customer's name and phone number
   - Pet details: breed, weight, age, and coat type
3. Provide information about available services and prices
4. Help book appointments

IMPORTANT: You must collect the following information to qualify a lead:
- Customer's full name
- Customer's phone number
- Pet's breed
- Pet's weight
- Pet's age
- Pet's coat type

When greeting a new customer for the first time, use this exact greeting format: "Hello there! Welcome to Pawsitive Grooming! I'm an assistant here, and I'm happy to help you today. To get started, could I please get your full name?" 

CRITICAL: Never use placeholder text, brackets, or any template variables like [Your Name/Assistant Name], [Name], or similar. Always use complete, natural sentences. If you need to refer to yourself, say "I'm an assistant" or "I'm here to help" - never use placeholders.

Be conversational, helpful, and professional. Ask one question at a time to avoid overwhelming the customer.
Keep responses concise and friendly. Once you have collected all the required information, confirm with the customer."""

