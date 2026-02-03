"""MCP server for booking: list slots, create event, create/update appointment (SRP)."""
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

from fastmcp import FastMCP

from agents.mcp_agent.servers.tool_utils import run_tool
from services.google_calendar_service import GoogleCalendarService
from services.google_sheets_service import GoogleSheetsService

logger = logging.getLogger(__name__)

DEFAULT_TZ = "Asia/Karachi"


def _format_slots(slot_tuples: List[Tuple[datetime, datetime]], tz_name: str = DEFAULT_TZ) -> List[Dict[str, str]]:
    """Format (start_utc, end_utc) slots to list of {start_iso, end_iso, display}. Single place for slot formatting."""
    tz = ZoneInfo(tz_name)
    out = []
    for start_utc, end_utc in slot_tuples:
        start_local = start_utc.astimezone(tz)
        end_local = end_utc.astimezone(tz)
        day_date = start_local.strftime("%A, %B %d, %Y")
        start_time = start_local.strftime("%I:%M %p").lstrip("0")
        end_time = end_local.strftime("%I:%M %p").lstrip("0")
        display = f"{day_date} — {start_time} to {end_time} ({tz})"
        out.append({
            "start_iso": start_utc.isoformat().replace("+00:00", "Z"),
            "end_iso": end_utc.isoformat().replace("+00:00", "Z"),
            "display": display,
        })
    return out


def _parse_iso(iso_str: str) -> datetime:
    """Parse ISO string to datetime with UTC fallback."""
    s = iso_str.replace("Z", "+00:00")
    dt = datetime.fromisoformat(s)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def create_booking_mcp_server(
    sheets_service: GoogleSheetsService,
    calendar_service: Optional[GoogleCalendarService],
) -> FastMCP:
    """Create FastMCP server with booking endpoints."""
    mcp = FastMCP(name="grooming-booking", description="Appointment booking for Pawsitive Grooming")

    @mcp.tool(
        name="booking_list_available_slots",
        description="List available time slots for the next 7 days (Mon-Sat business hours). Use this when the customer wants to book and you need to show options.",
    )
    def booking_list_available_slots() -> Dict[str, Any]:
        """Return list of available calendar slots."""
        if not calendar_service:
            return {"slots": [], "timezone": DEFAULT_TZ, "error": "Calendar not configured"}
        return run_tool(
            lambda: {"slots": _format_slots(calendar_service.list_available_slots()), "timezone": DEFAULT_TZ},
            {"slots": [], "timezone": DEFAULT_TZ},
            logger,
            "Error listing available slots",
        )

    @mcp.tool(
        name="booking_create_calendar_event",
        description="Create a calendar event for an appointment. Call this when the customer has chosen a specific slot. Returns event_id.",
    )
    def booking_create_calendar_event(
        summary: str,
        start_iso: str,
        end_iso: str,
        description: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create a calendar event."""
        if not calendar_service:
            return {"event_id": None, "error": "Calendar not configured"}
        def _create():
            start_dt = _parse_iso(start_iso)
            end_dt = _parse_iso(end_iso)
            event_id = calendar_service.create_event(summary, start_dt, end_dt, description=description)
            return {"event_id": event_id}
        return run_tool(_create, {"event_id": None}, logger, "Error creating calendar event")

    @mcp.tool(
        name="booking_create_appointment",
        description="Create an appointment record in the Appointments sheet. Call after creating the calendar event. Requires lead_id from lead_get_lead_id.",
    )
    def booking_create_appointment(
        lead_id: str,
        start_iso: str,
        end_iso: str,
        service_id: str = "SVC001",
        calendar_event_id: str = "",
    ) -> Dict[str, Any]:
        """Create appointment row in Appointments sheet."""
        return run_tool(
            lambda: {"appt_id": sheets_service.create_appointment(
                lead_id=lead_id,
                start_iso=start_iso,
                end_iso=end_iso,
                service_id=service_id,
                calendar_event_id=calendar_event_id or "",
            )},
            {"appt_id": None},
            logger,
            f"Error creating appointment for lead {lead_id}",
        )

    @mcp.tool(
        name="booking_update_appointment_service",
        description="Update the service for an existing appointment (e.g. customer wants to change to a different service).",
    )
    def booking_update_appointment_service(lead_id: str, service_id: str) -> Dict[str, Any]:
        """Update appointment's service_id."""
        return run_tool(
            lambda: {"success": sheets_service.update_appointment_service(lead_id=lead_id, service_id=service_id)},
            {"success": False},
            logger,
            f"Error updating appointment service for lead {lead_id}",
        )

    @mcp.tool(
        name="booking_get_appointment_by_lead_id",
        description="Get the most recent appointment for a lead. Use to check if customer already has a booking.",
    )
    def booking_get_appointment_by_lead_id(lead_id: str) -> Dict[str, Any]:
        """Get appointment for lead."""
        return run_tool(
            lambda: {"appointment": sheets_service.get_appointment_by_lead_id(lead_id)},
            {"appointment": None},
            logger,
            f"Error getting appointment for lead {lead_id}",
        )

    return mcp
