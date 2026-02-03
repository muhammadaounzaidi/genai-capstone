"""MCP server for lead operations: create, qualify, status, get lead id (SRP)."""
import logging
from typing import Any, Dict, Optional

from fastmcp import FastMCP

from agents.mcp_agent.servers.tool_utils import run_tool
from services.google_sheets_service import GoogleSheetsService

logger = logging.getLogger(__name__)


def create_lead_mcp_server(sheets_service: GoogleSheetsService) -> FastMCP:
    """Create FastMCP server with lead endpoints."""
    mcp = FastMCP(name="grooming-lead", instructions="Lead management for Pawsitive Grooming")

    @mcp.tool(
        name="lead_create_lead",
        description="Create a new lead when the user sends their first message. Call this on the first message from a user before responding.",
    )
    def lead_create_lead(user_id: str, username: str, message: str) -> Dict[str, Any]:
        """Create a new lead record in the Leads sheet."""
        return run_tool(
            lambda: sheets_service.create_lead(user_id=user_id, username=username, message=message),
            {"success": False},
            logger,
            f"Error creating lead for user_id {user_id}",
        )

    @mcp.tool(
        name="lead_qualify_lead",
        description="Update lead with customer name, phone, city and pet details. Call when the user has provided any of these.",
    )
    def lead_qualify_lead(
        user_id: str,
        name: Optional[str] = None,
        phone: Optional[str] = None,
        city: Optional[str] = None,
        pet_breed: Optional[str] = None,
        pet_weight: Optional[str] = None,
        pet_age: Optional[str] = None,
        pet_coat: Optional[str] = None,
        pet_name: Optional[str] = None,
        species: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Qualify the lead with customer and pet information."""
        return run_tool(
            lambda: {"success": sheets_service.qualify_lead(
                user_id=user_id,
                name=name,
                phone=phone,
                city=city,
                pet_breed=pet_breed,
                pet_weight=pet_weight,
                pet_age=pet_age,
                pet_coat=pet_coat,
                pet_name=pet_name,
                species=species,
            )},
            {"success": False},
            logger,
            f"Error qualifying lead for user_id {user_id}",
        )

    @mcp.tool(
        name="lead_update_lead_status",
        description="Update the status of an existing lead (e.g. to 'booked' after appointment is created).",
    )
    def lead_update_lead_status(user_id: str, status: str) -> Dict[str, Any]:
        """Update lead status."""
        return run_tool(
            lambda: {"success": sheets_service.update_lead_status(user_id=user_id, status=status)},
            {"success": False},
            logger,
            f"Error updating lead status for user_id {user_id}",
        )

    @mcp.tool(
        name="lead_get_lead_id",
        description="Get the lead_id for a user. Use this when you need to create an appointment or update an appointment.",
    )
    def lead_get_lead_id(user_id: str) -> Dict[str, Any]:
        """Get lead_id for the most recent lead of this user."""
        return run_tool(
            lambda: {"lead_id": sheets_service.get_lead_id_for_user(user_id)},
            {"lead_id": None},
            logger,
            f"Error getting lead_id for user_id {user_id}",
        )

    @mcp.tool(
        name="lead_exists",
        description="Check if a lead already exists for this user (by discord user id).",
    )
    def lead_exists(user_id: str) -> Dict[str, Any]:
        """Check if lead exists for user."""
        return run_tool(
            lambda: {"exists": sheets_service.lead_exists(user_id)},
            {"exists": False},
            logger,
            f"Error checking lead exists for user_id {user_id}",
        )

    return mcp
