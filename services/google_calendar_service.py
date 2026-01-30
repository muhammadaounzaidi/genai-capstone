"""Google Calendar service for checking availability and creating events."""
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Tuple
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

logger = logging.getLogger(__name__)

# Default slot duration in minutes; business hours 9–17
DEFAULT_SLOT_MINUTES = 60
DEFAULT_START_HOUR = 9
DEFAULT_END_HOUR = 17


class GoogleCalendarService:
    """Service for Google Calendar: list available slots and create events."""

    def __init__(self, calendar_id: str):
        """Initialize with calendar ID (e.g. from GOOGLE_CALENDAR_ID)."""
        self.calendar_id = calendar_id
        self._service = None
        self._initialize_service()

    def _initialize_service(self) -> None:
        """Build Calendar API service with service account credentials."""
        creds_file = os.getenv("GOOGLE_CREDENTIALS_FILE")
        if creds_file and os.path.exists(creds_file):
            scopes = [
                "https://www.googleapis.com/auth/calendar",
                "https://www.googleapis.com/auth/calendar.events",
            ]
            creds = Credentials.from_service_account_file(creds_file, scopes=scopes)
            self._service = build("calendar", "v3", credentials=creds)
            logger.info("Initialized Google Calendar client with service account")
            return

        service_account_info = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
        if service_account_info:
            scopes = [
                "https://www.googleapis.com/auth/calendar",
                "https://www.googleapis.com/auth/calendar.events",
            ]
            info = json.loads(service_account_info)
            creds = Credentials.from_service_account_info(info, scopes=scopes)
            self._service = build("calendar", "v3", credentials=creds)
            logger.info("Initialized Google Calendar client from env")
            return

        logger.warning(
            "No Google credentials found for Calendar. Set GOOGLE_CREDENTIALS_FILE or GOOGLE_SERVICE_ACCOUNT_JSON."
        )

    def list_available_slots(
        self,
        from_date: Optional[datetime] = None,
        to_date: Optional[datetime] = None,
        days_ahead: int = 7,
        slot_minutes: int = DEFAULT_SLOT_MINUTES,
        start_hour: int = DEFAULT_START_HOUR,
        end_hour: int = DEFAULT_END_HOUR,
    ) -> List[Tuple[datetime, datetime]]:
        """Return list of (start, end) datetime slots that are free.

        Slots are within business hours (start_hour–end_hour) in UTC, slot_minutes long.
        """
        if not self._service or not self.calendar_id:
            return []

        utc = timezone.utc
        now = (from_date or datetime.now(utc))
        if now.tzinfo is None:
            now = now.replace(tzinfo=utc)
        if to_date:
            end_limit = to_date
        else:
            end_limit = now + timedelta(days=days_ahead)
        if end_limit.tzinfo is None:
            end_limit = end_limit.replace(tzinfo=utc)

        time_min = now.replace(hour=start_hour, minute=0, second=0, microsecond=0)
        if time_min < now or time_min.hour >= end_hour:
            time_min = (now + timedelta(days=1)).replace(
                hour=start_hour, minute=0, second=0, microsecond=0
            )
        time_max = end_limit.replace(hour=end_hour, minute=0, second=0, microsecond=0)

        try:
            body = {
                "timeMin": time_min.isoformat().replace("+00:00", "Z"),
                "timeMax": time_max.isoformat().replace("+00:00", "Z"),
                "items": [{"id": self.calendar_id}],
            }
            result = self._service.freebusy().query(body=body).execute()
            busy_list = result.get("calendars", {}).get(self.calendar_id, {}).get("busy", [])
        except HttpError as e:
            logger.error(f"Calendar freebusy error: {e}")
            return []

        def parse_iso(s: str) -> datetime:
            s = s.replace("Z", "+00:00")
            return datetime.fromisoformat(s)

        busy_ranges = [(parse_iso(b["start"]), parse_iso(b["end"])) for b in busy_list]
        delta = timedelta(minutes=slot_minutes)
        slots = []
        current = time_min
        while current + delta <= time_max and len(slots) < 20:
            slot_end = current + delta
            if current.hour >= end_hour:
                current = (current + timedelta(days=1)).replace(
                    hour=start_hour, minute=0, second=0, microsecond=0
                )
                continue
            overlaps = any(
                current < b_end and slot_end > b_start
                for b_start, b_end in busy_ranges
            )
            if not overlaps and current >= now:
                slots.append((current, slot_end))
            current = slot_end
            if current.hour >= end_hour or current.hour < start_hour:
                current = (current + timedelta(days=1)).replace(
                    hour=start_hour, minute=0, second=0, microsecond=0
                )

        return slots

    def create_event(
        self,
        summary: str,
        start: datetime,
        end: datetime,
        description: Optional[str] = None,
    ) -> Optional[str]:
        """Create a calendar event. Returns event id or None."""
        if not self._service or not self.calendar_id:
            return None

        start_iso = start.isoformat().replace("+00:00", "Z") if start.tzinfo else start.isoformat() + "Z"
        end_iso = end.isoformat().replace("+00:00", "Z") if end.tzinfo else end.isoformat() + "Z"
        body = {
            "summary": summary,
            "start": {"dateTime": start_iso, "timeZone": "UTC"},
            "end": {"dateTime": end_iso, "timeZone": "UTC"},
        }
        if description:
            body["description"] = description

        try:
            event = self._service.events().insert(calendarId=self.calendar_id, body=body).execute()
            return event.get("id")
        except HttpError as e:
            logger.error(f"Calendar create event error: {e}")
            status = getattr(getattr(e, "resp", None), "status", 0)
            if status == 404:
                self._log_calendar_404_help()
            return None

    def _log_calendar_404_help(self) -> None:
        """Log how to fix 404 (calendar not found / not shared with service account)."""
        try:
            creds_file = os.getenv("GOOGLE_CREDENTIALS_FILE")
            if creds_file and os.path.exists(creds_file):
                with open(creds_file, "r") as f:
                    data = json.load(f)
                    email = data.get("client_email", "")
            else:
                raw = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
                email = json.loads(raw).get("client_email", "") if raw else ""
        except Exception:
            email = "(see client_email in your service account JSON)"
        logger.error(
            "Calendar 404: The calendar '%s' was not found or the service account has no access. "
            "Share the calendar with this email as 'Make changes to events': %s. "
            "Or create a new calendar in Google Calendar, share it with that email, and set GOOGLE_CALENDAR_ID to that calendar's ID (e.g. xxx@group.calendar.google.com).",
            self.calendar_id,
            email,
        )
