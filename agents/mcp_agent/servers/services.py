"""MCP server for services: list services, brand config, resolve service by name (SRP)."""
import logging
from typing import Any, Dict

from fastmcp import FastMCP

from agents.mcp_agent.servers.tool_utils import run_tool
from services.google_sheets_service import GoogleSheetsService

logger = logging.getLogger(__name__)


def create_services_mcp_server(sheets_service: GoogleSheetsService) -> FastMCP:
    """Create FastMCP server with services endpoints."""
    mcp = FastMCP(name="grooming-services", description="Services and brand info for Pawsitive Grooming")

    @mcp.tool(
        name="services_get_services",
        description="Get the list of available grooming services with id, title, description, price, duration. Use this to show services to the customer.",
    )
    def services_get_services() -> Dict[str, Any]:
        """Return all services from the Services sheet."""
        return run_tool(
            lambda: {"services": sheets_service.get_services()},
            {"services": []},
            logger,
            "Error getting services",
        )

    @mcp.tool(
        name="services_get_brand_config",
        description="Get brand info: hours, location, address, contact, phone, email. Use this to answer questions about business hours or location.",
    )
    def services_get_brand_config() -> Dict[str, Any]:
        """Return brand configuration (hours, location, contact)."""
        return run_tool(
            lambda: {"brand_config": sheets_service.get_brand_config()},
            {"brand_config": {}},
            logger,
            "Error getting brand config",
        )

    @mcp.tool(
        name="services_get_service_by_name_or_id",
        description="Find a service by name or id (e.g. user said 'Basic Grooming' or 'SVC001'). Returns the service record and service_id for booking.",
    )
    def services_get_service_by_name_or_id(user_input: str) -> Dict[str, Any]:
        """Find service matching user input (name or ID)."""
        def _get():
            pair = sheets_service.get_service_with_id(user_input)
            if not pair:
                return {"found": False, "service_id": None, "service": None}
            service_id, record = pair
            return {"found": True, "service_id": service_id, "service": record}

        return run_tool(
            _get,
            {"found": False, "service_id": None, "service": None},
            logger,
            f"Error getting service by name/id '{user_input}'",
        )

    return mcp
