"""Google Sheets service for managing leads, pets, services, and bookings."""
import json
import logging
import os
import random
import string
import traceback
import uuid
from datetime import datetime
from typing import Dict, List, Optional
import gspread
from google.oauth2.service_account import Credentials

logger = logging.getLogger(__name__)

LEADS_HEADERS = [
    "lead_id", "created_at_iso", "source", "discord_user_id",
    "name", "phone", "city", "status"
]
PETS_HEADERS = [
    "lead_id", "pet_id", "pet_name", "species", "breed",
    "weight_kg", "age_years", "coat_condition", "notes"
]
APPOINTMENTS_HEADERS = [
    "appt_id", "lead_id", "service_id", "status",
    "start_iso", "end_iso", "calendar_event_id",
]


class GoogleSheetsService:
    """Service for interacting with Google Sheets following SRP."""
    
    def __init__(self, sheets_id: str, api_key: Optional[str] = None):
        """Initialize Google Sheets service.
        
        Args:
            sheets_id: The Google Sheets document ID
            api_key: Optional API key for authentication
        """
        self.sheets_id = sheets_id
        self.client = None
        self._initialize_client(api_key)
    
    def _initialize_client(self, api_key: Optional[str] = None):
        """Initialize the Google Sheets client.
        
        Note: For write access, service account credentials are required.
        API key alone is not sufficient for write operations.
        """
        creds_file = os.getenv("GOOGLE_CREDENTIALS_FILE")
        if creds_file and os.path.exists(creds_file):
            scopes = ['https://www.googleapis.com/auth/spreadsheets']
            creds = Credentials.from_service_account_file(creds_file, scopes=scopes)
            self.client = gspread.authorize(creds)
            logger.info("Initialized Google Sheets client with service account")
            return
        
        service_account_info = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
        if service_account_info:
            service_account_dict = json.loads(service_account_info)
            scopes = ['https://www.googleapis.com/auth/spreadsheets']
            creds = Credentials.from_service_account_info(service_account_dict, scopes=scopes)
            self.client = gspread.authorize(creds)
            logger.info("Initialized Google Sheets client with service account from env")
            return
        
        error_msg = (
            "No valid authentication method found. "
            "Please set GOOGLE_CREDENTIALS_FILE or GOOGLE_SERVICE_ACCOUNT_JSON. "
            "Service account credentials are required for write access."
        )
        logger.error(error_msg)
        raise ValueError(error_msg)
    
    def _get_or_create_sheet(self, spreadsheet, title: str, headers: List[str]):
        """Get worksheet by title, or create it with the given headers if missing."""
        try:
            return spreadsheet.worksheet(title)
        except gspread.exceptions.WorksheetNotFound:
            logger.info(f"Worksheet '{title}' not found, creating it with headers")
            sheet = spreadsheet.add_worksheet(title=title, rows=1000, cols=len(headers) + 5)
            sheet.append_row(headers)
            return sheet

    def _ensure_leads_and_pets_sheets(self, spreadsheet) -> None:
        """Create Leads, Pets, and Appointments sheets with headers if they do not exist."""
        self._get_or_create_sheet(spreadsheet, "Leads", LEADS_HEADERS)
        self._get_or_create_sheet(spreadsheet, "Pets", PETS_HEADERS)
        self._get_or_create_sheet(spreadsheet, "Appointments", APPOINTMENTS_HEADERS)
    
    def create_lead(self, user_id: str, username: str, message: str) -> Dict:
        """Create a new lead record in the Leads sheet.
        
        Args:
            user_id: Discord user ID
            username: Discord username (for logging; not stored in new schema)
            message: Initial message from user (for logging; not stored in new schema)
            
        Returns:
            Dictionary with lead information (lead_id, created_at_iso, source, discord_user_id, name, phone, city, status)
        """
        try:
            spreadsheet = self.client.open_by_key(self.sheets_id)
        except gspread.exceptions.APIError as e:
            error_msg = self._extract_api_error_message(e)
            logger.error(f"Google Sheets API error creating lead for user_id {user_id}: {error_msg}")
            self._log_permission_help()
            raise
        except PermissionError as e:
            error_msg = str(e) if str(e) else f"PermissionError: {type(e).__name__}"
            logger.error(f"Permission error creating lead for user_id {user_id}: {error_msg}")
            self._log_permission_help()
            raise
        self._ensure_leads_and_pets_sheets(spreadsheet)

        leads_sheet = spreadsheet.worksheet("Leads")
        lead_id = str(uuid.uuid4())
        created_at_iso = datetime.now().isoformat()
        row = [
            lead_id,
            created_at_iso,
            "discord",
            str(user_id),
            "",
            "",
            "",
            "initiated",
        ]
        leads_sheet.append_row(row)
        logger.info(f"Created lead {lead_id} for discord_user_id {user_id}")
        return dict(zip(LEADS_HEADERS, row))
    
    def lead_exists(self, user_id: str) -> bool:
        """Check if a lead exists for the given discord_user_id.
        
        Args:
            user_id: Discord user ID (discord_user_id)
            
        Returns:
            True if lead exists, False otherwise
        """
        try:
            spreadsheet = self.client.open_by_key(self.sheets_id)
            leads_sheet = spreadsheet.worksheet("Leads")
            cells = leads_sheet.findall(str(user_id))
            return len(cells) > 0
        except gspread.exceptions.WorksheetNotFound:
            return False
        except gspread.exceptions.APIError as e:
            error_msg = self._extract_api_error_message(e)
            logger.error(f"Google Sheets API error checking if lead exists for user_id {user_id}: {error_msg}")
            self._log_permission_help()
            return False
        except PermissionError as e:
            error_msg = str(e) if str(e) else f"PermissionError: {type(e).__name__}"
            logger.error(f"Permission error checking if lead exists for user_id {user_id}: {error_msg}")
            self._log_permission_help()
            return False
        except Exception as e:
            error_msg = str(e) if str(e) else f"{type(e).__name__}: No error message available"
            logger.error(f"Error checking if lead exists for user_id {user_id}: {error_msg}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            return False
    
    def update_lead_status(self, user_id: str, status: str) -> bool:
        """Update the status of an existing lead.
        
        Args:
            user_id: Discord user ID
            status: New status value
            
        Returns:
            True if successful, False otherwise
        """
        try:
            spreadsheet = self.client.open_by_key(self.sheets_id)
            leads_sheet = spreadsheet.worksheet("Leads")
        except gspread.exceptions.WorksheetNotFound:
            return False
        headers = leads_sheet.row_values(1)
        if "status" not in headers:
            logger.warning("Leads sheet has no 'status' column")
            return False
        cells = leads_sheet.findall(str(user_id))
        if not cells:
            logger.warning(f"Lead not found for discord_user_id: {user_id}")
            return False
        status_col = headers.index("status") + 1
        for cell in cells:
            leads_sheet.update_cell(cell.row, status_col, status)
        logger.info(f"Updated lead status for discord_user_id {user_id} to {status}")
        return True
    
    def qualify_lead(
        self,
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
    ) -> bool:
        """Update lead with qualification details and add pet to Pets sheet.
        
        Args:
            user_id: Discord user ID
            name: User's name
            phone: User's phone number
            city: User's city (optional)
            pet_breed: Pet's breed
            pet_weight: Pet's weight (stored in weight_kg column as provided)
            pet_age: Pet's age (stored in age_years as provided)
            pet_coat: Pet's coat type (stored in coat_condition)
            pet_name: Pet's name (optional)
            species: Pet species e.g. dog/cat (optional)
            
        Returns:
            True if successful, False otherwise
        """
        try:
            spreadsheet = self.client.open_by_key(self.sheets_id)
        except (gspread.exceptions.APIError, PermissionError) as e:
            logger.error(f"Google Sheets error qualifying lead for user_id {user_id}: {e}")
            self._log_permission_help()
            return False
        
        leads_sheet = self._get_or_create_sheet(spreadsheet, "Leads", LEADS_HEADERS)
        headers = leads_sheet.row_values(1)
        if not headers:
            logger.error("Leads sheet has no headers")
            return False
        
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
                cells = []
                for row_num, val in enumerate(all_vals, start=1):
                    if row_num == 1:
                        continue
                    if str(val).strip() == str(user_id).strip():
                        cells.append(Cell(row_num, discord_col, str(user_id)))
        if not cells:
            logger.warning(f"Lead not found for discord_user_id: {user_id}")
            return False
        
        # Use the most recent lead (highest row number) when user has multiple leads
        row_num = max(cell.row for cell in cells)
        row_vals = leads_sheet.row_values(row_num)
        padded = row_vals + [""] * (len(headers) - len(row_vals))
        lead_row_dict = dict(zip(headers, padded))
        lead_id = lead_row_dict.get("lead_id", "")
        
        # Update Leads row: name, phone, city, status
        updates = []
        if name is not None and "name" in headers:
            updates.append((row_num, headers.index("name") + 1, name))
        if phone is not None and "phone" in headers:
            updates.append((row_num, headers.index("phone") + 1, phone))
        if city is not None and "city" in headers:
            updates.append((row_num, headers.index("city") + 1, city))
        if "status" in headers:
            updates.append((row_num, headers.index("status") + 1, "qualified"))
        for r, c, v in updates:
            leads_sheet.update_cell(r, c, v)
        
        # Add a pet row when we have at least one pet detail
        has_pet_info = any([
            (pet_name or "").strip(),
            (species or "").strip(),
            (pet_breed or "").strip(),
            (pet_weight or "").strip(),
            (pet_age or "").strip(),
            (pet_coat or "").strip(),
        ])
        if has_pet_info and lead_id:
            pets_sheet = self._get_or_create_sheet(spreadsheet, "Pets", PETS_HEADERS)
            pet_id = str(uuid.uuid4())
            pet_row = [
                lead_id,
                pet_id,
                (pet_name or "").strip(),
                (species or "").strip(),
                (pet_breed or "").strip(),
                (pet_weight or "").strip(),
                (pet_age or "").strip(),
                (pet_coat or "").strip(),
                "",
            ]
            pets_sheet.append_row(pet_row)
            logger.info(f"Qualified lead for discord_user_id {user_id}, added pet {pet_id}")
        return True

    def _generate_appt_id(self) -> str:
        """Generate short appointment id like APPT3D8W3Z."""
        chars = string.ascii_uppercase + string.digits
        return "APPT" + "".join(random.choices(chars, k=8))

    def create_appointment(
        self,
        lead_id: str,
        start_iso: str,
        end_iso: str,
        service_id: str = "SVC001",
        calendar_event_id: str = "",
    ) -> Optional[str]:
        """Append a row to the Appointments sheet. Returns appt_id."""
        try:
            spreadsheet = self.client.open_by_key(self.sheets_id)
        except Exception as e:
            logger.error(f"Error opening spreadsheet for appointment: {e}")
            return None
        appointments_sheet = self._get_or_create_sheet(spreadsheet, "Appointments", APPOINTMENTS_HEADERS)
        appt_id = self._generate_appt_id()
        row = [
            appt_id,
            lead_id,
            service_id,
            "booked",
            start_iso,
            end_iso,
            calendar_event_id,
        ]
        appointments_sheet.append_row(row)
        logger.info(f"Created appointment {appt_id} for lead {lead_id}")
        return appt_id
    
    def _extract_api_error_message(self, error: gspread.exceptions.APIError) -> str:
        """Extract detailed error message from APIError.
        
        Args:
            error: The APIError exception
            
        Returns:
            Detailed error message string
        """
        error_str = str(error)
        # Try to extract more details from the error response
        if hasattr(error, 'response') and error.response:
            try:
                # gspread APIError response might be a requests Response object
                if hasattr(error.response, 'json'):
                    error_data = error.response.json()
                    if isinstance(error_data, dict):
                        error_details = error_data.get('error', {})
                        if isinstance(error_details, dict):
                            message = error_details.get('message', '')
                            status = error_details.get('status', '')
                            if message:
                                return f"[{status}] {message}" if status else message
                # Or it might be a string
                elif isinstance(error.response, str):
                    return error.response
            except (AttributeError, ValueError, TypeError):
                pass
        # Return the string representation which usually contains the error message
        return error_str if error_str else f"APIError: {type(error).__name__}"
    
    def get_services(self) -> list:
        """Read services from the Services sheet (name, duration, price).
        
        Tries worksheet "Services" first, then "Service". Returns list of dicts per row.
        """
        try:
            spreadsheet = self.client.open_by_key(self.sheets_id)
        except Exception as e:
            logger.error(f"Error opening spreadsheet for services: {e}")
            return []
        for sheet_name in ("Services", "Service"):
            try:
                services_sheet = spreadsheet.worksheet(sheet_name)
                records = services_sheet.get_all_records()
                if not records:
                    continue
                # Normalize keys (strip spaces) so "Service Name" and "Service  Name" both work
                normalized = []
                for row in records:
                    normalized.append({str(k).strip(): v for k, v in row.items()})
                return normalized
            except gspread.exceptions.WorksheetNotFound:
                continue
            except Exception as e:
                logger.error(f"Error reading sheet '{sheet_name}': {e}")
                continue
        logger.warning("No Services or Service worksheet found with data")
        return []

    def get_service_by_name_or_id(self, user_input: str) -> Optional[Dict]:
        """Find a service matching the user's input (name or ID).
        
        Args:
            user_input: Service name or ID as provided by the user (case-insensitive)
            
        Returns:
            Service record dict with normalized keys, or None if no match
        """
        services = self.get_services()
        if not services:
            return None
        user_input_clean = (user_input or "").strip().lower()
        if not user_input_clean:
            return None
        name_keys = ("title", "service name", "name", "service_name", "service")
        for record in services:
            if not isinstance(record, dict):
                continue
            keys_lower = {str(k).strip().lower(): k for k in record.keys()}
            for key_lower, key_orig in keys_lower.items():
                value = record.get(key_orig)
                if value is None:
                    continue
                val_str = str(value).strip()
                if not val_str:
                    continue
                if val_str.lower() == user_input_clean:
                    return record
            for key_lower, key_orig in keys_lower.items():
                if key_lower in name_keys:
                    value = record.get(key_orig)
                    if value is None:
                        continue
                    val_str = str(value).strip().lower()
                    if user_input_clean in val_str or val_str in user_input_clean:
                        return record
        return None

    def get_service_id_from_record(self, record: Dict, index: int = 0) -> str:
        """Extract service ID from a service record. Falls back to SVC + index if no ID column."""
        if not record:
            return f"SVC{str(index + 1).zfill(3)}"
        keys_lower = {str(k).strip().lower(): k for k in record.keys()}
        for id_key in ("service_id", "service id", "id"):
            if id_key in keys_lower:
                val = record.get(keys_lower[id_key])
                if val is not None and str(val).strip():
                    return str(val).strip()
        return f"SVC{str(index + 1).zfill(3)}"
    
    def _get_service_account_email(self) -> Optional[str]:
        """Get the service account email from credentials.
        
        Returns:
            Service account email or None if not available
        """
        try:
            creds_file = os.getenv("GOOGLE_CREDENTIALS_FILE")
            if creds_file and os.path.exists(creds_file):
                with open(creds_file, 'r') as f:
                    creds_data = json.load(f)
                    return creds_data.get('client_email')
            
            service_account_info = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
            if service_account_info:
                creds_data = json.loads(service_account_info)
                return creds_data.get('client_email')
        except Exception:
            pass
        return None
    
    def _log_permission_help(self) -> None:
        """Log helpful instructions for fixing permission errors."""
        service_account_email = self._get_service_account_email()
        logger.error("")
        logger.error("=" * 60)
        logger.error("GOOGLE SHEETS PERMISSION ERROR")
        logger.error("=" * 60)
        logger.error("The service account does not have permission to access the Google Sheet.")
        logger.error("")
        logger.error("To fix this issue:")
        logger.error("1. Open your Google Sheet in a web browser")
        logger.error("2. Click the 'Share' button (top right)")
        if service_account_email:
            logger.error(f"3. Add this email address as an Editor: {service_account_email}")
        else:
            logger.error("3. Add your service account email (from GOOGLE_CREDENTIALS_FILE or GOOGLE_SERVICE_ACCOUNT_JSON)")
            logger.error("   The email is in the 'client_email' field of your service account JSON")
        logger.error("4. Make sure to give 'Editor' permissions (not just Viewer)")
        logger.error("5. Click 'Send' and wait a few seconds")
        logger.error("6. Restart the bot")
        logger.error("")
        logger.error("=" * 60)
    

