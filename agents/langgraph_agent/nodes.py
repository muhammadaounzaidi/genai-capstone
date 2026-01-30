"""Agent nodes for LangGraph workflow."""
import json
import logging
import re
import traceback
from typing import Any, Dict, List, Optional
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage, AIMessage
from agents.langgraph_agent.state import AgentState
from services.google_sheets_service import GoogleSheetsService
from config import Config

logger = logging.getLogger(__name__)


class AgentNodes:
    """Agent node - each node has a single responsibility."""
    
    def __init__(
        self,
        sheets_service: GoogleSheetsService,
        calendar_service: Optional[Any] = None,
    ):
        """Initialize agent nodes with dependencies.
        
        Args:
            sheets_service: Google Sheets service instance
            calendar_service: Optional Google Calendar service for booking
        """
        self.sheets_service = sheets_service
        self.calendar_service = calendar_service
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
        
        # Skip if we already created a lead this conversation
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
            
            system_prompt = self._get_system_prompt(state)
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
        from the conversation and updates the lead status to 'qualified'. When lead is already
        qualified but pet info was provided in a later message, adds the pet to the Pets sheet.

        Args:
            state: Current agent state

        Returns:
            Updated state with lead_qualified flag and optionally pet_added
        """
        if not state.get("lead_created", False):
            logger.warning(f"Lead not created yet for user {state['user_id']}, skipping qualification")
            return {"lead_qualified": False}

        if state.get("lead_qualified", False) and state.get("pet_added", False):
            logger.info(f"Lead already qualified with pet for user {state['user_id']}")
            return {"lead_qualified": True, "pet_added": True}
        
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
                    city=qualification_info.get("city"),
                    pet_breed=qualification_info.get("pet_breed"),
                    pet_weight=qualification_info.get("pet_weight"),
                    pet_age=qualification_info.get("pet_age"),
                    pet_coat=qualification_info.get("pet_coat"),
                    pet_name=qualification_info.get("pet_name"),
                    species=qualification_info.get("species"),
                )
                
                if success:
                    logger.info(f"Successfully qualified lead for {state['username']}")
                    collected_info = state.get("collected_info", {})
                    collected_info.update(qualification_info)
                    has_pet_info = any([
                        qualification_info.get("pet_name"),
                        qualification_info.get("pet_breed"),
                        qualification_info.get("pet_weight"),
                        qualification_info.get("pet_age"),
                        qualification_info.get("pet_coat"),
                        qualification_info.get("species"),
                    ])
                    return {
                        "lead_qualified": True,
                        "current_step": "qualified",
                        "collected_info": collected_info,
                        "pet_added": has_pet_info or state.get("pet_added", False),
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
- phone: The customer's phone number (include full number as given, e.g. 00112233)

Pet Information (you MUST include these in the JSON whenever the customer has mentioned them):
- pet_name: The pet's name (e.g. Johnny, Max)
- pet_breed: The pet's breed (e.g., Golden Retriever, Persian Cat)
- pet_weight: The pet's weight (e.g., 25 lbs, 10 kg, 25 pounds)
- pet_age: The pet's age (e.g., 3 years, 18 months)
- pet_coat: The pet's coat type (e.g., short, long, curly, double coat)

Conversation:
{conversation_text}

CRITICAL: You must return ONLY a valid JSON object. Do not include any markdown formatting, code blocks, or explanatory text. Return ONLY the JSON object itself.

Use null for any missing information. Example format:
{{
    "name": "John Doe",
    "phone": "555-1234",
    "pet_name": "Johnny",
    "pet_breed": "Golden Retriever",
    "pet_weight": "25 lbs",
    "pet_age": "3 years",
    "pet_coat": "long"
}}

If you cannot extract at least the user's name and phone, return the string "null" (not a JSON null value).
Whenever the customer has mentioned their pet (breed, age, weight, coat, or name), include every one of those in the JSON; do not omit pet_breed, pet_weight, pet_age, or pet_coat if they appear in the conversation."""
        
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
                "pet_name": qualification_info.get("pet_name"),
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
    
    def _get_system_prompt(self, state: Optional[AgentState] = None) -> str:
        """Get the system prompt for the agent, including services and optional available slots."""
        base = """You are a friendly and professional assistant for Pawsitive Grooming, a pet grooming business. 
Your role is to:
1. Greet customers warmly with a friendly greeting like: "Hello there! Welcome to Pawsitive Grooming! I'm happy to help you today."
2. Qualify leads by collecting:
   - Customer's name and phone number
   - Pet details: breed, weight, age, and coat type
3. When the customer asks for services, a list of services, or prices, you MUST list every service from the AVAILABLE SERVICES section below (name, price, duration). Never say you don't have the list.
4. BOOKING FLOW - follow this order strictly:
   a) Once you have collected all required info (name, phone, pet details), immediately LIST the AVAILABLE SERVICES and ask "Which service would you like?" Do NOT ask about booking an appointment at this point.
   b) Only after the customer has selected/confirmed a service, ask "Would you like to book an appointment?" Do NOT offer time slots yet.
   c) Only when the customer says yes they want to book, offer the AVAILABLE TIME SLOTS and ask which slot they prefer.
   d) Once they choose a slot, confirm: "I've booked you for [date/time]. See you then!"
5. If the customer asks for or requests a service that is NOT in our list: Apologize and say "I'm sorry, we don't offer that service. We only have these services: [list them]. You can book from these only."

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
Keep responses concise and friendly. After collecting pet details, list services and ask which service they want. Do NOT ask "would you like to hear about services or book" - go straight to listing services."""

        services_text = self._format_services_for_prompt()
        if services_text:
            base += "\n\nAVAILABLE SERVICES (full information — when the customer asks for services or a list, show all details for each):\n\n" + services_text

        if (
            state
            and state.get("lead_qualified")
            and not state.get("appointment_booked")
            and state.get("invalid_service_requested")
            and state.get("requested_service_name")
        ):
            base += f"\n\nThe customer requested '{state.get('requested_service_name')}' which we do NOT offer. Apologize and say we only have the services listed above. They can book from those only."

        if (
            state
            and state.get("lead_qualified")
            and not state.get("appointment_booked")
            and state.get("service_selected")
            and self._user_wants_to_book(state.get("messages", []))
        ):
            slots_text = self._format_available_slots_for_prompt()
            if slots_text:
                base += "\n\nAVAILABLE TIME SLOTS (offer these now and ask which slot they prefer):\n" + slots_text
        elif (
            state
            and state.get("lead_qualified")
            and not state.get("appointment_booked")
            and state.get("service_selected")
        ):
            base += "\n\nThe customer has selected a service but not yet said they want to book. Ask 'Would you like to book an appointment?' Do NOT show time slots until they say yes."

        return base

    def _format_services_for_prompt(self) -> str:
        """Fetch services from the Services sheet and include all columns in the prompt."""
        services = self.sheets_service.get_services()
        if not services:
            return ""
        blocks = []
        for idx, record in enumerate(services, start=1):
            if not isinstance(record, dict):
                continue
            # Include every non-empty column so the agent can show all information
            parts = [f"Service {idx}:"]
            for key, value in record.items():
                key_str = str(key).strip()
                if not key_str:
                    continue
                val = value
                if val is None:
                    val = ""
                val_str = str(val).strip()
                if val_str:
                    parts.append(f"  {key_str}: {val_str}")
            if len(parts) > 1:
                blocks.append("\n".join(parts))
        return "\n\n".join(blocks) if blocks else ""

    def select_service_node(self, state: AgentState) -> Dict:
        """Extract and validate service selection from user message when booking.
        
        Sets service_selected when user chooses a valid service, or
        invalid_service_requested when they ask for a service we don't offer.
        """
        if not state.get("lead_qualified"):
            return {}
        if state.get("appointment_booked"):
            return {}
        if state.get("service_selected"):
            return {}
        messages = state.get("messages", [])
        if not messages:
            return {}
        last_user_content = ""
        for msg in reversed(messages):
            if msg.get("role") == "user":
                last_user_content = msg.get("content", "")
                break
        if not last_user_content.strip():
            return {}
        services = self.sheets_service.get_services()
        if not services:
            return {}
        service_names = []
        for record in services:
            if isinstance(record, dict):
                for key in ("title", "Service Name", "name", "Name", "service_name", "Service"):
                    key_lower = {str(k).strip().lower(): k for k in record.keys()}
                    if key.lower() in key_lower:
                        val = record.get(key_lower[key.lower()])
                        if val and str(val).strip():
                            service_names.append(str(val).strip())
                            break
        if not service_names:
            return {}
        extraction_prompt = f"""From this user message, extract ONLY the service name they are requesting, if any.

Available services: {', '.join(service_names)}

User message: "{last_user_content}"

If the user is clearly selecting or asking for one of the listed services (or a close match like "basic" for "Basic Grooming"), return that service name exactly as listed.
If the user is asking for a service NOT in our list, return the exact phrase they used for the service they want.
If the user is NOT asking for or selecting a service (e.g. general chat, asking for slots, saying hello), return: NONE

Return only the service name or NONE, nothing else."""
        try:
            response = self.llm.invoke([HumanMessage(content=extraction_prompt)])
            extracted = (response.content or "").strip().upper()
            if not extracted or extracted == "NONE":
                return {"invalid_service_requested": False, "requested_service_name": None}
            service_record = self.sheets_service.get_service_by_name_or_id(
                response.content.strip() if response.content else ""
            )
            if service_record:
                services_list = self.sheets_service.get_services()
                name_keys = ("title", "service name", "name", "service_name", "service")
                record_name = None
                for key_lower, key_orig in {
                    str(k).strip().lower(): k for k in service_record.keys()
                }.items():
                    if key_lower in name_keys:
                        record_name = str(service_record.get(key_orig, "")).strip()
                        break
                idx = 0
                for i, r in enumerate(services_list):
                    if not isinstance(r, dict):
                        continue
                    for k_l, k_o in {str(k).strip().lower(): k for k in r.keys()}.items():
                        if k_l in name_keys and str(r.get(k_o, "")).strip() == record_name:
                            idx = i
                            break
                service_id = self.sheets_service.get_service_id_from_record(
                    service_record, idx
                )
                logger.info(f"User selected service {service_id} for {state['username']}")
                return {
                    "service_selected": service_id,
                    "invalid_service_requested": False,
                    "requested_service_name": None,
                }
            logger.info(f"User requested invalid service: {response.content.strip()}")
            return {
                "invalid_service_requested": True,
                "requested_service_name": response.content.strip(),
            }
        except Exception as e:
            logger.error(f"Error in select_service_node: {e}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            return {}

    def _user_wants_to_book(self, messages: list) -> bool:
        """Check if the last user message indicates they want to book an appointment."""
        booking_phrases = (
            "book", "schedule", "yes", "yeah", "sure", "please", "i'd like",
            "i would like", "let's book", "lets book", "appointment",
        )
        for msg in reversed(messages):
            if msg.get("role") == "user":
                content = (msg.get("content") or "").strip().lower()
                return any(phrase in content for phrase in booking_phrases)
        return False

    def _format_available_slots_for_prompt(self) -> str:
        """Fetch available slots from Calendar and format for the system prompt."""
        if not self.calendar_service:
            return ""
        slots = self.calendar_service.list_available_slots()
        if not slots:
            return "No slots available in the next 7 days."
        lines = []
        for start, end in slots:
            lines.append(f"- {start.strftime('%A %Y-%m-%d %H:%M')} to {end.strftime('%H:%M')} UTC")
        return "\n".join(lines)

    def book_appointment_node(self, state: AgentState) -> Dict:
        """If user chose a slot, book it: Calendar event, Appointments sheet, set lead status = booked."""
        if not state.get("lead_qualified"):
            return {}
        if state.get("appointment_booked"):
            return {}
        if not state.get("service_selected"):
            return {}
        if not self.calendar_service:
            return {}
        messages = state.get("messages", [])
        if not messages:
            return {}
        user_id = state.get("user_id")
        # Get most recent lead_id for this user
        try:
            spreadsheet = self.sheets_service.client.open_by_key(self.sheets_service.sheets_id)
            leads_sheet = spreadsheet.worksheet("Leads")
            headers = leads_sheet.row_values(1)
            cells = leads_sheet.findall(str(user_id))
            if not cells:
                discord_col = None
                for idx, h in enumerate(headers):
                    if h and str(h).strip().lower() == "discord_user_id":
                        discord_col = idx + 1
                        break
                if discord_col:
                    from gspread.cell import Cell
                    all_vals = leads_sheet.col_values(discord_col)
                    cells = [
                        Cell(row_num, discord_col, str(user_id))
                        for row_num, val in enumerate(all_vals, start=1)
                        if row_num > 1 and str(val).strip() == str(user_id).strip()
                    ]
            if not cells:
                return {}
            row_num = max(cell.row for cell in cells)
            row_vals = leads_sheet.row_values(row_num)
            padded = row_vals + [""] * (len(headers) - len(row_vals))
            lead_row = dict(zip(headers, padded))
            lead_id = lead_row.get("lead_id")
            if not lead_id:
                return {}
        except Exception as e:
            logger.error(f"Error getting lead for booking: {e}")
            return {}
        slots = self.calendar_service.list_available_slots()
        if not slots:
            return {}
        # Parse last user message for chosen slot (date/time)
        last_user_content = ""
        for m in reversed(messages):
            if m.get("role") == "user":
                last_user_content = m.get("content", "")
                break
        chosen_slot = self._extract_chosen_slot_from_message(last_user_content, slots)
        if not chosen_slot:
            return {}
        start_dt, end_dt = chosen_slot
        summary = f"Pawsitive Grooming - {state.get('username', 'Customer')}"
        event_id = self.calendar_service.create_event(summary, start_dt, end_dt)
        start_iso = start_dt.isoformat().replace("+00:00", "Z")
        end_iso = end_dt.isoformat().replace("+00:00", "Z")
        service_id = state.get("service_selected", "SVC001")
        self.sheets_service.create_appointment(
            lead_id=lead_id,
            start_iso=start_iso,
            end_iso=end_iso,
            service_id=service_id,
            calendar_event_id=event_id or "",
        )
        self.sheets_service.update_lead_status(user_id, "booked")
        confirmation = f"I've booked your appointment for {start_dt.strftime('%A, %B %d at %H:%M')} UTC. See you then!"
        new_messages = list(messages)
        if new_messages and new_messages[-1].get("role") == "assistant":
            new_messages[-1] = {"role": "assistant", "content": confirmation}
        else:
            new_messages.append({"role": "assistant", "content": confirmation})
        return {
            "messages": new_messages,
            "appointment_booked": True,
        }

    def _extract_chosen_slot_from_message(self, message: str, slots: List) -> Optional[tuple]:
        """Use LLM to extract which slot the user chose from their message. Returns (start_dt, end_dt) or None."""
        if not message or not slots:
            return None
        slots_desc = "\n".join(
            f"{i+1}. {start.strftime('%A %Y-%m-%d %H:%M')} to {end.strftime('%H:%M')} UTC"
            for i, (start, end) in enumerate(slots)
        )
        prompt = f"""The user chose an appointment time. Their message: "{message}"

Available slots (each line is one slot):
{slots_desc}

Return ONLY the number (1 to {len(slots)}) of the slot they chose, or 0 if unclear. One digit only."""
        try:
            response = self.llm.invoke([HumanMessage(content=prompt)])
            text = (response.content or "").strip()
            num = int(re.search(r"[0-9]+", text).group(0)) if re.search(r"[0-9]+", text) else 0
            if 1 <= num <= len(slots):
                return slots[num - 1]
        except Exception as e:
            logger.error(f"Error extracting chosen slot: {e}")
        return None
