"""Agent nodes for LangGraph workflow."""
import json
import logging
import re
import traceback
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage, AIMessage
from agents.langgraph_agent.state import AgentState
from services.google_sheets_service import (
    GoogleSheetsService,
    SERVICE_ID_KEY,
    SERVICE_TITLE_KEY,
    SERVICES_HEADERS,
)
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
                    logger.info(f"Successfully updated lead for {state['username']} (partial or full qualification)")
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
                    has_name_and_phone = bool(
                        qualification_info.get("name") and qualification_info.get("phone")
                    )
                    return {
                        "lead_qualified": has_name_and_phone or state.get("lead_qualified", False),
                        "current_step": "qualified" if has_name_and_phone else state.get("current_step", "conversation"),
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
- city: The customer's city (optional)

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

Extract whatever information is present. If the customer has given their name, phone, city, or any pet details, return a JSON object with those fields (use null for missing). If the conversation contains no such information, return the string "null".
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
            city = qualification_info.get("city")
            pet_name = qualification_info.get("pet_name")
            pet_breed = qualification_info.get("pet_breed")
            pet_weight = qualification_info.get("pet_weight")
            pet_age = qualification_info.get("pet_age")
            pet_coat = qualification_info.get("pet_coat")
            species = qualification_info.get("species")

            has_any = any([
                name and str(name).strip(),
                phone and str(phone).strip(),
                city and str(city).strip(),
                pet_name and str(pet_name).strip(),
                pet_breed and str(pet_breed).strip(),
                pet_weight and str(pet_weight).strip(),
                pet_age and str(pet_age).strip(),
                pet_coat and str(pet_coat).strip(),
                species and str(species).strip(),
            ])
            if not has_any:
                return None

            return {
                "name": name,
                "phone": phone,
                "city": city,
                "pet_name": pet_name,
                "pet_breed": pet_breed,
                "pet_weight": pet_weight,
                "pet_age": pet_age,
                "pet_coat": pet_coat,
                "species": species,
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
   c) Only when the customer says yes they want to book, you MUST list the AVAILABLE TIME SLOTS (from the slot list below) and say these slots are available and ask which slot they prefer. Do NOT book until the customer has chosen a specific slot (e.g. "slot 1", "Tuesday at 9 AM").
   d) Only after the customer has chosen a specific slot (by number or date/time), confirm: "I've booked you for [date/time]. See you then!"
5. If the customer asks for or requests a service that is NOT in our list: Apologize and say "I'm sorry, we don't offer that service. We only have these services: [list them]. You can book from these only."
6. When the customer asks generic/info questions (hours, location, address, contact, phone, email), answer using the BRAND INFO section below. Never make up this information.
7. UPDATE BOOKING: If the customer already has a booking and asks to change or update it (e.g. change the service), list the AVAILABLE SERVICES and ask which service they want. After they choose a new service, confirm that the booking has been updated to that service.

IMPORTANT: You must collect the following information to qualify a lead:
- Customer's full name
- Customer's phone number
- Pet's breed
- Pet's weight
- Pet's age
- Pet's coat type

When greeting a new customer for the first time, use this exact greeting format: "Hello there! Welcome to Pawsitive Grooming! I'm an assistant here, and I'm happy to help you today. To get started, could I please get your full name?" 

CRITICAL: Never use placeholder text, brackets, or any template variables like [Your Name/Assistant Name], [Name], or similar. Always use complete, natural sentences. If you need to refer to yourself, say "I'm an assistant" or "I'm here to help" - never use placeholders.

Be conversational, helpful, and professional. The customer may provide name, phone, pet details, or all of these in a single message. Always use the INFORMATION ALREADY COLLECTED section below: if we already have something (e.g. name and phone), acknowledge it and do NOT ask again; only ask for what is still missing (e.g. pet details) or move to listing services if everything is collected.
Keep responses concise and friendly. After collecting pet details, list services and ask which service they want. Do NOT ask "would you like to hear about services or book" - go straight to listing services."""

        collected_info = state.get("collected_info", {}) if state else {}
        messages = state.get("messages", []) if state else []
        if messages:
            extracted = self._extract_qualification_info(messages)
            if extracted:
                merged = dict(collected_info)
                merged.update(extracted)
                collected_info = merged
        if collected_info:
            lines = ["INFORMATION ALREADY COLLECTED (do not ask again; acknowledge and only ask for what is missing):"]
            if collected_info.get("name"):
                lines.append(f"- Name: {collected_info.get('name')}")
            if collected_info.get("phone"):
                lines.append(f"- Phone: {collected_info.get('phone')}")
            if collected_info.get("city"):
                lines.append(f"- City: {collected_info.get('city')}")
            pet_parts = []
            if collected_info.get("pet_name"):
                pet_parts.append(f"name: {collected_info['pet_name']}")
            if collected_info.get("species"):
                pet_parts.append(collected_info["species"])
            if collected_info.get("pet_breed"):
                pet_parts.append(f"breed: {collected_info['pet_breed']}")
            if collected_info.get("pet_weight"):
                pet_parts.append(f"weight: {collected_info['pet_weight']}")
            if collected_info.get("pet_age"):
                pet_parts.append(f"age: {collected_info['pet_age']}")
            if collected_info.get("pet_coat"):
                pet_parts.append(f"coat: {collected_info['pet_coat']}")
            if pet_parts:
                lines.append("- Pet: " + ", ".join(pet_parts))
            base += "\n\n" + "\n".join(lines)

        brand_text = self._format_brand_config_for_prompt()
        if brand_text:
            base += "\n\nBRAND INFO (use this to answer questions about hours, location, contact):\n\n" + brand_text

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

        # When service is selected and not yet booked, always provide slots so the LLM can list them
        # when the customer says they want to book (flow decided by LLM from conversation).
        if (
            state
            and state.get("lead_qualified")
            and not state.get("appointment_booked")
            and state.get("service_selected")
        ):
            slots_text = self._format_available_slots_for_prompt()
            if slots_text:
                tz = ZoneInfo("Asia/Karachi")
                now_local = datetime.now(timezone.utc).astimezone(tz)
                today_str = now_local.strftime("%A, %B %d, %Y")
                base += (
                    f"\n\nTODAY'S DATE: {today_str}. Use this date context. "
                    "When the customer says they want to book, you MUST list the AVAILABLE TIME SLOTS below and ask which slot they prefer. "
                    "When they have not yet said they want to book, ask 'Would you like to book an appointment?' and do NOT show time slots yet. "
                    "List ONLY the following slots EXACTLY as written, with the same numbers and full date/time. "
                    "Do NOT make up dates or times. Do NOT confirm a booking until the customer has chosen a specific slot (by number or date/time).\n\n"
                    "AVAILABLE TIME SLOTS:\n"
                    + slots_text
                )
            else:
                base += "\n\nThe customer has selected a service. Ask 'Would you like to book an appointment?' (No slots available to show yet.)"

        # When the customer already has a booking, they can ask to change the service.
        if (
            state
            and state.get("lead_qualified")
            and state.get("appointment_booked")
            and state.get("service_selected")
        ):
            current_service_name = self._get_service_name_by_id(state.get("service_selected"))
            base += (
                "\n\nThe customer has an existing booking. Current service: "
                + (current_service_name or state.get("service_selected", ""))
                + ". "
                "If they ask to change or update their booking (e.g. change the service), list the AVAILABLE SERVICES above and ask which service they want. "
                "After they choose a new service, confirm that the booking has been updated to that service."
            )

        return base

    def _get_service_name_by_id(self, service_id: Optional[str]) -> Optional[str]:
        """Return the display name for a service_id from the Services sheet (SERVICE_TITLE_KEY)."""
        if not service_id:
            return None
        services = self.sheets_service.get_services()
        if not services:
            return None
        name_keys = (SERVICE_TITLE_KEY, "Service Name", "name", "Name", "service_name", "Service")
        for index, record in enumerate(services):
            if not isinstance(record, dict):
                continue
            sid = self.sheets_service.get_service_id_from_record(record, index)
            if str(sid).strip() == str(service_id).strip():
                keys_lower = {str(k).strip().lower(): k for k in record.keys()}
                for key_lower in name_keys:
                    if key_lower in keys_lower:
                        val = record.get(keys_lower[key_lower])
                        if val is not None and str(val).strip():
                            return str(val).strip()
                return None
        return None

    def _format_brand_config_for_prompt(self) -> str:
        """Fetch brand config (hours, location, contact) from BrandConfig sheet for the prompt."""
        config = self.sheets_service.get_brand_config()
        if not config:
            return ""
        lines = []
        key_labels = {
            "brand_name": "Business Name",
            "welcome_copy": "Welcome Message",
            "hours": "Hours",
            "business_hours": "Hours",
            "opening_hours": "Hours",
            "location": "Location",
            "address": "Address",
            "timezone": "Timezone",
            "contact": "Contact",
            "phone": "Phone",
            "phone_number": "Phone",
            "email": "Email",
        }
        skip_keys = ("brand_id", "upsells_json", "objection_snippets_json")
        for key, value in config.items():
            if key in skip_keys or not value:
                continue
            label = key_labels.get(key, key.replace("_", " ").title())
            val_str = str(value).strip()
            if val_str:
                lines.append(f"- {label}: {val_str}")
        return "\n".join(lines) if lines else ""

    def _format_services_for_prompt(self) -> str:
        """Fetch services from the Services sheet and include columns per SERVICES_HEADERS."""
        services = self.sheets_service.get_services()
        if not services:
            return ""
        blocks = []
        for idx, record in enumerate(services, start=1):
            if not isinstance(record, dict):
                continue
            parts = [f"Service {idx}:"]
            for key in SERVICES_HEADERS:
                if key not in record:
                    continue
                val = record.get(key)
                if val is None:
                    val = ""
                val_str = str(val).strip()
                if val_str:
                    parts.append(f"  {key}: {val_str}")
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
            if not isinstance(record, dict):
                continue
            val = record.get(SERVICE_TITLE_KEY)
            if val and str(val).strip():
                service_names.append(str(val).strip())
                continue
            for key in ("Service Name", "name", "Name", "service_name", "Service"):
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
                name_keys = (SERVICE_TITLE_KEY, "service name", "name", "service_name", "service")
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

    def _format_single_slot(self, start_utc, end_utc, tz: ZoneInfo) -> str:
        """Format one slot as: Day, Date — Start time to End time (Timezone)."""
        start_local = start_utc.astimezone(tz)
        end_local = end_utc.astimezone(tz)
        day_date = start_local.strftime("%A, %B %d, %Y")
        start_time = start_local.strftime("%I:%M %p").lstrip("0")
        end_time = end_local.strftime("%I:%M %p").lstrip("0")
        tz_name = str(tz)
        return f"{day_date} — {start_time} to {end_time} ({tz_name})"

    def _format_available_slots_for_prompt(self) -> str:
        """Fetch available slots from Calendar and format for the system prompt.
        Displays upcoming slots with day, date, time, and timezone (Asia/Karachi).
        """
        if not self.calendar_service:
            return ""
        slots = self.calendar_service.list_available_slots()
        if not slots:
            return "No slots available in the next 7 days."
        tz = ZoneInfo("Asia/Karachi")
        header = "Upcoming available slots (all times in Asia/Karachi):"
        lines = [header, ""]
        for index, (start_utc, end_utc) in enumerate(slots, start=1):
            lines.append(f"  {index}. {self._format_single_slot(start_utc, end_utc, tz)}")
        return "\n".join(lines)

    def sync_to_sheets_node(self, state: AgentState) -> Dict:
        """Run qualify_lead, select_service, book_appointment, and update_booking in sequence
        so any user update (name, phone, pet, service, slot, or change of service) is reflected.
        """
        merged: Dict = {}
        for node_fn in (
            self.qualify_lead_node,
            self.select_service_node,
            self.book_appointment_node,
            self.update_booking_node,
        ):
            try:
                result = node_fn(state)
                if result:
                    state = {**state, **result}
                    merged.update(result)
            except Exception as e:
                logger.error(f"Error in sync_to_sheets step {node_fn.__name__}: {e}")
                logger.error(f"Traceback: {traceback.format_exc()}")
        return merged

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
        last_user_content = ""
        for m in reversed(messages):
            if m.get("role") == "user":
                last_user_content = m.get("content", "")
                break
        # Only book when the user has chosen a specific slot (LLM extraction; returns None if no slot chosen).
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
        tz = ZoneInfo("Asia/Karachi")
        start_local = start_dt.astimezone(tz)
        day_date = start_local.strftime("%A, %B %d, %Y")
        time_str = start_local.strftime("%I:%M %p").lstrip("0")
        confirmation = f"I've booked your appointment for {day_date} at {time_str} ({tz}). See you then!"
        new_messages = list(messages)
        if new_messages and new_messages[-1].get("role") == "assistant":
            new_messages[-1] = {"role": "assistant", "content": confirmation}
        else:
            new_messages.append({"role": "assistant", "content": confirmation})
        return {
            "messages": new_messages,
            "appointment_booked": True,
        }

    def update_booking_node(self, state: AgentState) -> Dict:
        """When the user has a booking and asks to change the service, extract new service
        and update the appointment in Sheets (service_id). Updates state and confirms to user.
        """
        if not state.get("lead_qualified") or not state.get("appointment_booked"):
            return {}
        if not state.get("service_selected"):
            return {}
        messages = state.get("messages", [])
        if not messages:
            return {}
        last_user_content = ""
        for msg in reversed(messages):
            if msg.get("role") == "user":
                last_user_content = (msg.get("content") or "").strip()
                break
        if not last_user_content:
            return {}
        # Detect if user wants to change/update their booking or is selecting a new service.
        try:
            intent_prompt = (
                "The user already has a booking. Does the user want to change/update their booking "
                "(e.g. said 'change service', 'update my booking') OR are they selecting a new "
                "service for their booking (e.g. naming a service like 'Basic Groom', 'the first one')? "
                "Reply ONLY 'YES' if they want to change the booking or are choosing a new service. "
                "Reply ONLY 'NO' if they are just chatting or not referring to changing the booking.\n\n"
                f'User message: "{last_user_content}"'
            )
            intent_response = self.llm.invoke([HumanMessage(content=intent_prompt)])
            intent_text = (intent_response.content or "").strip().upper()
            if "YES" not in intent_text:
                return {}
        except Exception as e:
            logger.error(f"Error detecting update-booking intent: {e}")
            return {}
        # Extract which new service they want (same logic as select_service_node).
        new_service_id = self._extract_new_service_from_message(last_user_content, state)
        if not new_service_id or new_service_id == state.get("service_selected"):
            return {}
        user_id = state.get("user_id")
        lead_id = self._get_lead_id_for_user(user_id)
        if not lead_id:
            return {}
        success = self.sheets_service.update_appointment_service(lead_id, new_service_id)
        if not success:
            return {}
        new_service_name = self._get_service_name_by_id(new_service_id) or new_service_id
        confirmation = (
            f"I've updated your booking to {new_service_name}. "
            "Your appointment time stays the same. See you then!"
        )
        new_messages = list(messages)
        if new_messages and new_messages[-1].get("role") == "assistant":
            new_messages[-1] = {"role": "assistant", "content": confirmation}
        else:
            new_messages.append({"role": "assistant", "content": confirmation})
        return {
            "messages": new_messages,
            "service_selected": new_service_id,
        }

    def _get_lead_id_for_user(self, user_id: str) -> Optional[str]:
        """Return the lead_id for the most recent lead row matching user_id."""
        try:
            spreadsheet = self.sheets_service.client.open_by_key(self.sheets_service.sheets_id)
            leads_sheet = spreadsheet.worksheet("Leads")
            headers = leads_sheet.row_values(1)
            cells = leads_sheet.findall(str(user_id))
            if not cells:
                discord_col = None
                for idx, header in enumerate(headers):
                    if header and str(header).strip().lower() == "discord_user_id":
                        discord_col = idx + 1
                        break
                if not discord_col:
                    return None
                from gspread.cell import Cell
                all_vals = leads_sheet.col_values(discord_col)
                cells = [
                    Cell(row_num, discord_col, str(user_id))
                    for row_num, val in enumerate(all_vals, start=1)
                    if row_num > 1 and str(val).strip() == str(user_id).strip()
                ]
            if not cells:
                return None
            row_num = max(cell.row for cell in cells)
            row_vals = leads_sheet.row_values(row_num)
            padded = row_vals + [""] * (len(headers) - len(row_vals))
            lead_row = dict(zip(headers, padded))
            return lead_row.get("lead_id")
        except Exception as e:
            logger.error(f"Error getting lead_id for user {user_id}: {e}")
            return None

    def _extract_new_service_from_message(self, message: str, state: AgentState) -> Optional[str]:
        """Extract a new service selection from the user message (for update-booking flow).
        Returns service_id or None.
        """
        services = self.sheets_service.get_services()
        if not services:
            return None
        service_names = []
        for record in services:
            if not isinstance(record, dict):
                continue
            val = record.get(SERVICE_TITLE_KEY)
            if val and str(val).strip():
                service_names.append(str(val).strip())
                continue
            keys_lower = {str(k).strip().lower(): k for k in record.keys()}
            for key in ("Service Name", "name", "Name", "service_name", "Service"):
                if key.lower() in keys_lower:
                    val = record.get(keys_lower[key.lower()])
                    if val and str(val).strip():
                        service_names.append(str(val).strip())
                        break
        if not service_names:
            return None
        extraction_prompt = (
            f"From this user message, extract ONLY the service name they are requesting, if any.\n\n"
            f"Available services: {', '.join(service_names)}\n\n"
            f'User message: "{message}"\n\n'
            "If the user is selecting or asking for one of the listed services (or a close match), "
            "return that service name exactly as listed. "
            "If they are NOT selecting a service, return: NONE\n\n"
            "Return only the service name or NONE, nothing else."
        )
        try:
            response = self.llm.invoke([HumanMessage(content=extraction_prompt)])
            extracted = (response.content or "").strip().upper()
            if not extracted or extracted == "NONE":
                return None
            service_record = self.sheets_service.get_service_by_name_or_id(
                response.content.strip() if response.content else ""
            )
            if not service_record:
                return None
            services_list = self.sheets_service.get_services()
            name_keys = (SERVICE_TITLE_KEY, "service name", "name", "service_name", "service")
            record_name = None
            for key_lower, key_orig in {
                str(k).strip().lower(): k for k in service_record.keys()
            }.items():
                if key_lower in name_keys:
                    record_name = str(service_record.get(key_orig, "")).strip()
                    break
            idx = 0
            for i, rec in enumerate(services_list):
                if not isinstance(rec, dict):
                    continue
                for k_l, k_o in {str(k).strip().lower(): k for k in rec.keys()}.items():
                    if k_l in name_keys and str(rec.get(k_o, "")).strip() == record_name:
                        idx = i
                        break
            return self.sheets_service.get_service_id_from_record(service_record, idx)
        except Exception as e:
            logger.error(f"Error extracting new service from message: {e}")
            return None

    def _extract_chosen_slot_from_message(self, message: str, slots: List) -> Optional[tuple]:
        """Use LLM to extract which slot the user chose from their message. Returns (start_dt, end_dt) or None."""
        if not message or not slots:
            return None
        tz = ZoneInfo("Asia/Karachi")
        slots_desc = "\n".join(
            f"{i+1}. {self._format_single_slot(start, end, tz)}"
            for i, (start, end) in enumerate(slots)
        )
        prompt = f"""The user is replying about an appointment. Their message: "{message}"

Available slots (each line is one slot, same order as shown to the user):
{slots_desc}

Return ONLY the number (1 to {len(slots)}) of the slot they chose, or 0 if they did not choose a specific slot.
If the user only said they want to book (e.g. "yes", "sure", "please", "ok") but did NOT pick a slot number or date/time, return 0.
One digit only."""
        try:
            response = self.llm.invoke([HumanMessage(content=prompt)])
            text = (response.content or "").strip()
            num = int(re.search(r"[0-9]+", text).group(0)) if re.search(r"[0-9]+", text) else 0
            if 1 <= num <= len(slots):
                return slots[num - 1]
        except Exception as e:
            logger.error(f"Error extracting chosen slot: {e}")
        return None
