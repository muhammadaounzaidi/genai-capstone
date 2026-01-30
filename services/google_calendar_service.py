"""Google Calendar service for checking availability and creating events."""
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Tuple
from zoneinfo import ZoneInfo

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

logger = logging.getLogger(__name__)

# Booking hours: Mon-Sat 9:00-18:00, timezone Asia/Karachi
DEFAULT_SLOT_MINUTES = 60
DEFAULT_START_HOUR = 9
DEFAULT_END_HOUR = 18
DEFAULT_TIMEZONE = "Asia/Karachi"


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
        tz_name: str = DEFAULT_TIMEZONE,
    ) -> List[Tuple[datetime, datetime]]:
        """Return list of (start, end) datetime slots that are free.

        Slots are Mon-Sat, start_hour–end_hour in the given timezone (default Asia/Karachi).
        Returns datetimes in UTC for calendar API compatibility.
        """
        if not self._service or not self.calendar_id:
            return []

        tz = ZoneInfo(tz_name)
        utc = timezone.utc
        now_utc = from_date or datetime.now(utc)
        if now_utc.tzinfo is None:
            now_utc = now_utc.replace(tzinfo=utc)
        now_local = now_utc.astimezone(tz)
        if to_date:
            end_limit_utc = to_date if to_date.tzinfo else to_date.replace(tzinfo=utc)
        else:
            end_limit_utc = now_utc + timedelta(days=days_ahead)
        end_limit_local = end_limit_utc.astimezone(tz)

        def next_business_day(dt: datetime) -> datetime:
            """Next Mon-Sat at start_hour in local time."""
            while dt.weekday() == 6:
                dt = dt + timedelta(days=1)
            return dt.replace(hour=start_hour, minute=0, second=0, microsecond=0)

        current_local = now_local.replace(hour=start_hour, minute=0, second=0, microsecond=0)
        if current_local < now_local or current_local.hour >= end_hour:
            current_local = next_business_day(now_local + timedelta(days=1))
        if current_local.weekday() == 6:
            current_local = next_business_day(current_local + timedelta(days=1))

        try:
            time_min_utc = current_local.astimezone(utc)
            time_max_local = end_limit_local.replace(hour=end_hour, minute=0, second=0, microsecond=0)
            if time_max_local < current_local:
                time_max_local = (current_local + timedelta(days=days_ahead)).replace(
                    hour=end_hour, minute=0, second=0, microsecond=0
                )
            time_max_utc = time_max_local.astimezone(utc)
            body = {
                "timeMin": time_min_utc.isoformat().replace("+00:00", "Z"),
                "timeMax": time_max_utc.isoformat().replace("+00:00", "Z"),
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
        max_slots = 20
        iterations = 0
        max_iterations = 500
        while len(slots) < max_slots and iterations < max_iterations:
            iterations += 1
            if current_local.weekday() == 6:
                current_local = next_business_day(current_local + timedelta(days=1))
                continue
            if current_local.hour >= end_hour:
                current_local = next_business_day(current_local + timedelta(days=1))
                continue
            if current_local > end_limit_local:
                break
            slot_end_local = current_local + delta
            if slot_end_local.hour > end_hour or (slot_end_local.hour == end_hour and slot_end_local.minute > 0):
                current_local = next_business_day(current_local + timedelta(days=1))
                continue
            current_utc = current_local.astimezone(utc)
            slot_end_utc = slot_end_local.astimezone(utc)
            if current_utc >= now_utc:
                overlaps = any(
                    current_utc < b_end and slot_end_utc > b_start
                    for b_start, b_end in busy_ranges
                )
                if not overlaps:
                    slots.append((current_utc, slot_end_utc))
            current_local = slot_end_local

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
