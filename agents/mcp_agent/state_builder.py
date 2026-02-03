"""Build conversation state from sheets and previous state (SRP: state derivation only)."""
from typing import Any, Dict

from services.google_sheets_service import GoogleSheetsService


def format_collected_info(collected_info: Dict[str, Any]) -> str:
    """Format collected info for agent instructions."""
    if not collected_info:
        return ""
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
        pet_parts.append(str(collected_info["species"]))
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
    return "\n".join(lines)


def build_state_from_sheets(
    sheets_service: GoogleSheetsService,
    user_id: str,
    username: str,
    prev: Dict[str, Any],
) -> Dict[str, Any]:
    """Build state dict from sheets and previous state (for Discord bot compatibility)."""
    lead_created = sheets_service.lead_exists(user_id)
    status = sheets_service.get_lead_status(user_id)
    lead_qualified = status in ("qualified", "booked")
    lead_id = sheets_service.get_lead_id_for_user(user_id)
    appointment = sheets_service.get_appointment_by_lead_id(lead_id) if lead_id else None
    appointment_booked = appointment is not None and (appointment.get("status") == "booked" or True)
    service_selected = appointment.get("service_id") if appointment else prev.get("service_selected")

    return {
        "user_id": user_id,
        "username": username,
        "messages": prev.get("messages", []),
        "lead_created": lead_created,
        "current_step": "qualified" if lead_qualified else ("initiated" if lead_created else "conversation"),
        "collected_info": prev.get("collected_info", {}),
        "lead_qualified": lead_qualified,
        "pet_added": prev.get("pet_added", False),
        "service_selected": service_selected,
        "invalid_service_requested": prev.get("invalid_service_requested", False),
        "requested_service_name": prev.get("requested_service_name"),
        "appointment_details": prev.get("appointment_details"),
        "appointment_booked": appointment_booked,
        "available_slots": prev.get("available_slots"),
    }
