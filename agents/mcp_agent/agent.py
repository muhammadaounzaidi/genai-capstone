"""Pydantic AI agent using MCP tools for grooming business (same behavior as LangGraph)."""
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from pydantic_ai import Agent, RunContext
from pydantic_ai.toolsets.fastmcp import FastMCPToolset

from agents.base import BaseAgent
from agents.mcp_agent.prompts import SYSTEM_PROMPT
from agents.mcp_agent.servers import (
    create_booking_mcp_server,
    create_lead_mcp_server,
    create_services_mcp_server,
)
from agents.mcp_agent.state_builder import build_state_from_sheets, format_collected_info
from config import Config
from services.google_calendar_service import GoogleCalendarService
from services.google_sheets_service import GoogleSheetsService

logger = logging.getLogger(__name__)


@dataclass
class AgentDeps:
    """Dependencies for the grooming agent (user and conversation state)."""
    user_id: str
    username: str
    collected_info: Dict[str, Any] = field(default_factory=dict)
    lead_qualified: bool = False
    appointment_booked: bool = False
    service_selected: Optional[str] = None


def create_grooming_agent(
    sheets_service: GoogleSheetsService,
    calendar_service: Optional[GoogleCalendarService],
) -> Agent[AgentDeps, str]:
    """Create Pydantic AI agent with lead, services, and booking MCP tools."""
    lead_mcp = create_lead_mcp_server(sheets_service)
    services_mcp = create_services_mcp_server(sheets_service)
    booking_mcp = create_booking_mcp_server(sheets_service, calendar_service)

    lead_toolset = FastMCPToolset(lead_mcp)
    services_toolset = FastMCPToolset(services_mcp)
    booking_toolset = FastMCPToolset(booking_mcp)

    model = "google-gla:gemini-2.5-flash"
    if not Config.GOOGLE_API_KEY:
        logger.warning("GOOGLE_API_KEY not set; agent may fail at runtime")

    agent = Agent[AgentDeps, str](
        model=model,
        deps_type=AgentDeps,
        output_type=str,
        system_prompt=SYSTEM_PROMPT,
        toolsets=[lead_toolset, services_toolset, booking_toolset],
    )

    @agent.instructions
    def inject_user_and_state(ctx: RunContext[AgentDeps]) -> str:
        """Inject current user id, username and collected info so the model uses them in tool calls."""
        deps = ctx.deps
        parts = [
            f"The current user's user_id is: {deps.user_id}. The username is: {deps.username}.",
            "When you call lead_create_lead, lead_qualify_lead, lead_update_lead_status, lead_get_lead_id, or lead_exists, always pass this user_id (and username for lead_create_lead).",
        ]
        collected_text = format_collected_info(deps.collected_info)
        if collected_text:
            parts.append(collected_text)
        if deps.lead_qualified and deps.appointment_booked:
            parts.append("The customer already has a booking. If they ask to change the service, use booking_update_appointment_service.")
        return "\n\n".join(parts)

    return agent


class MCPAgent(BaseAgent):
    """Agent implementation using Pydantic AI and multiple MCP servers (lead, services, booking)."""

    def __init__(
        self,
        sheets_service: GoogleSheetsService,
        calendar_service: Optional[GoogleCalendarService] = None,
    ):
        """Initialize the MCP agent.

        Args:
            sheets_service: Google Sheets service instance.
            calendar_service: Optional Google Calendar service for booking.
        """
        self.sheets_service = sheets_service
        self.calendar_service = calendar_service
        self._agent = create_grooming_agent(sheets_service, calendar_service)

    async def process_message(
        self,
        user_id: str,
        username: str,
        message: str,
        conversation_history: Optional[list] = None,
        last_state: Optional[dict] = None,
    ) -> Dict[str, Any]:
        """Process a user message using Pydantic AI and MCP tools.

        Args:
            user_id: Unique identifier for the user.
            username: Username of the user.
            message: The message content from the user.
            conversation_history: Optional list of previous messages (unused; we use last_state message_history).
            last_state: Optional state from previous invocation (must include pydantic_message_history for continuity).

        Returns:
            Dictionary containing response, state, and lead_created.
        """
        prev = last_state or {}
        try:
            message_history = prev.get("pydantic_message_history")
            is_first_message = not message_history and (not conversation_history or len(conversation_history) == 0)

            if is_first_message:
                try:
                    self.sheets_service.create_lead(
                        user_id=user_id,
                        username=username,
                        message=message,
                    )
                    logger.info(f"Created lead for {username} (first message)")
                except Exception as error:
                    logger.error(f"Error creating lead for user {user_id}: {error}")

            deps = AgentDeps(
                user_id=user_id,
                username=username,
                collected_info=prev.get("collected_info", {}),
                lead_qualified=prev.get("lead_qualified", False),
                appointment_booked=prev.get("appointment_booked", False),
                service_selected=prev.get("service_selected"),
            )

            result = await self._agent.run(
                message,
                deps=deps,
                message_history=message_history,
            )

            response_text = result.output if result.output is not None else "I'm here to help!"
            new_state = build_state_from_sheets(self.sheets_service, user_id, username, prev)
            new_state["pydantic_message_history"] = result.all_messages()
            new_state["last_interaction_at"] = time.time()
            new_state["reminder_sent"] = prev.get("reminder_sent", False)

            return {
                "response": response_text,
                "state": new_state,
                "lead_created": new_state.get("lead_created", True),
            }
        except Exception as error:
            logger.error(f"Error processing message with MCP agent: {error}")
            return {
                "response": "I apologize, but I encountered an error. Please try again.",
                "state": prev if prev else {},
                "lead_created": False,
            }

    def create_lead(self, user_id: str, username: str, message: str) -> Dict[str, Any]:
        """Create a new lead record.

        Args:
            user_id: Unique identifier for the user.
            username: Username of the user.
            message: Initial message from the user.

        Returns:
            Dictionary containing lead information.
        """
        return self.sheets_service.create_lead(
            user_id=user_id,
            username=username,
            message=message,
        )
