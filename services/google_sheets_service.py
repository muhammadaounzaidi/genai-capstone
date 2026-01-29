"""Google Sheets service for managing leads, pets, services, and bookings."""
import json
import logging
import os
import traceback
from datetime import datetime
from typing import Dict, Optional
import gspread
from google.oauth2.service_account import Credentials

logger = logging.getLogger(__name__)


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
    
    def create_lead(self, user_id: str, username: str, message: str) -> Dict:
        """Create a new lead record in the Leads sheet.
        
        Args:
            user_id: Discord user ID
            username: Discord username
            message: Initial message from user
            
        Returns:
            Dictionary with lead information
        """
        # Check if lead already exists
        if self.lead_exists(user_id):
            logger.info(f"Lead already exists for user_id {user_id}, skipping creation")
            try:
                spreadsheet = self.client.open_by_key(self.sheets_id)
                leads_sheet = spreadsheet.worksheet("Leads")
                cells = leads_sheet.findall(user_id)
                if cells:
                    # Return existing lead data
                    row = cells[0].row
                    headers = leads_sheet.row_values(1)
                    row_values = leads_sheet.row_values(row)
                    lead_data = dict(zip(headers, row_values))
                    return lead_data
            except gspread.exceptions.APIError as e:
                error_msg = self._extract_api_error_message(e)
                logger.error(f"Google Sheets API error retrieving existing lead for user_id {user_id}: {error_msg}")
                self._log_permission_help()
                raise
            except PermissionError as e:
                error_msg = str(e) if str(e) else f"PermissionError: {type(e).__name__}"
                logger.error(f"Permission error retrieving existing lead for user_id {user_id}: {error_msg}")
                self._log_permission_help()
                raise
        
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
        
        try:
            leads_sheet = spreadsheet.worksheet("Leads")
        except gspread.exceptions.WorksheetNotFound:
            logger.info("Leads worksheet not found, creating it")
            leads_sheet = spreadsheet.add_worksheet(title="Leads", rows=1000, cols=15)
            headers = [
                "user_id", "username", "status", "initial_message", "timestamp",
                "name", "phone", "pet_breed", "pet_weight", "pet_age", "pet_coat"
            ]
            leads_sheet.append_row(headers)
        
        self._ensure_qualification_headers(leads_sheet)
        
        timestamp = datetime.now().isoformat()
        lead_data = {
            "user_id": user_id,
            "username": username,
            "status": "initiated",
            "initial_message": message,
            "timestamp": timestamp,
        }
        
        headers = leads_sheet.row_values(1)
        row = []
        for header in headers:
            if header == "user_id":
                # Store user_id as string to ensure consistent searching
                row.append(str(lead_data["user_id"]))
            elif header == "username":
                row.append(lead_data["username"])
            elif header == "status":
                row.append(lead_data["status"])
            elif header == "initial_message":
                row.append(lead_data["initial_message"])
            elif header == "timestamp":
                row.append(lead_data["timestamp"])
            else:
                row.append("")
        
        leads_sheet.append_row(row)
        logger.info(f"Created lead for user {username} (ID: {user_id})")
        return lead_data
    
    def lead_exists(self, user_id: str) -> bool:
        """Check if a lead exists for the given user_id.
        
        Args:
            user_id: Discord user ID
            
        Returns:
            True if lead exists, False otherwise
        """
        try:
            spreadsheet = self.client.open_by_key(self.sheets_id)
            leads_sheet = spreadsheet.worksheet("Leads")
            cells = leads_sheet.findall(user_id)
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
        spreadsheet = self.client.open_by_key(self.sheets_id)
        leads_sheet = spreadsheet.worksheet("Leads")
        
        cells = leads_sheet.findall(user_id)
        if not cells:
            logger.warning(f"Lead not found for user_id: {user_id}")
            return False
        
        for cell in cells:
            row = cell.row
            leads_sheet.update_cell(row, 3, status)
        
        logger.info(f"Updated lead status for user {user_id} to {status}")
        return True
    
    def qualify_lead(
        self,
        user_id: str,
        name: Optional[str] = None,
        phone: Optional[str] = None,
        pet_breed: Optional[str] = None,
        pet_weight: Optional[str] = None,
        pet_age: Optional[str] = None,
        pet_coat: Optional[str] = None,
    ) -> bool:
        """Update lead with qualification details and set status to qualified.
        
        Args:
            user_id: Discord user ID
            name: User's name
            phone: User's phone number
            pet_breed: Pet's breed
            pet_weight: Pet's weight
            pet_age: Pet's age
            pet_coat: Pet's coat type
            
        Returns:
            True if successful, False otherwise
        """
        try:
            spreadsheet = self.client.open_by_key(self.sheets_id)
        except gspread.exceptions.APIError as e:
            error_msg = self._extract_api_error_message(e)
            logger.error(f"Google Sheets API error qualifying lead for user_id {user_id}: {error_msg}")
            self._log_permission_help()
            return False
        except PermissionError as e:
            error_msg = str(e) if str(e) else f"PermissionError: {type(e).__name__}"
            logger.error(f"Permission error qualifying lead for user_id {user_id}: {error_msg}")
            self._log_permission_help()
            return False
        
        try:
            leads_sheet = spreadsheet.worksheet("Leads")
        except gspread.exceptions.WorksheetNotFound:
            logger.error(f"Leads worksheet not found for user_id: {user_id}")
            return False
        
        self._ensure_qualification_headers(leads_sheet)
        
        headers = leads_sheet.row_values(1)
        if not headers:
            logger.error("Leads sheet has no headers")
            return False
        
        # Find the lead by user_id
        cells = leads_sheet.findall(str(user_id))
        if not cells:
            # Fallback: manual search in user_id column
            if "user_id" in headers:
                user_id_col = headers.index("user_id") + 1
                all_values = leads_sheet.col_values(user_id_col)
                for row_num, cell_value in enumerate(all_values, start=1):
                    if row_num == 1:
                        continue
                    if str(cell_value).strip() == str(user_id).strip():
                        from gspread.cell import Cell
                        cells = [Cell(row_num, user_id_col, str(user_id))]
                        break
        
        if not cells:
            logger.warning(f"Lead not found for user_id: {user_id}")
            return False
        
        cell = cells[0]
        row = cell.row
        
        # Build updates
        updates = []
        if name is not None and "name" in headers:
            updates.append((row, headers.index("name") + 1, name))
        if phone is not None and "phone" in headers:
            updates.append((row, headers.index("phone") + 1, phone))
        if pet_breed is not None and "pet_breed" in headers:
            updates.append((row, headers.index("pet_breed") + 1, pet_breed))
        if pet_weight is not None and "pet_weight" in headers:
            updates.append((row, headers.index("pet_weight") + 1, pet_weight))
        if pet_age is not None and "pet_age" in headers:
            updates.append((row, headers.index("pet_age") + 1, pet_age))
        if pet_coat is not None and "pet_coat" in headers:
            updates.append((row, headers.index("pet_coat") + 1, pet_coat))
        if "status" in headers:
            updates.append((row, headers.index("status") + 1, "qualified"))
        
        if not updates:
            logger.warning(f"No updates to apply for user_id: {user_id}")
            return False
        
        # Update cells
        try:
            for update_row, update_col, update_value in updates:
                leads_sheet.update_cell(update_row, update_col, update_value)
            logger.info(f"Successfully qualified lead for user_id: {user_id}")
            return True
        except Exception as e:
            logger.error(f"Error updating lead for user_id {user_id}: {e}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            return False
    
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
        
        Returns:
            List of dicts with keys: name, duration, price (or as per sheet headers).
            Empty list if sheet not found or on error.
        """
        try:
            spreadsheet = self.client.open_by_key(self.sheets_id)
            services_sheet = spreadsheet.worksheet("Services")
        except gspread.exceptions.WorksheetNotFound:
            logger.warning("Services worksheet not found")
            return []
        except Exception as e:
            logger.error(f"Error opening Services sheet: {e}")
            return []
        
        try:
            records = services_sheet.get_all_records()
            if not records:
                return []
            return list(records)
        except Exception as e:
            logger.error(f"Error reading Services sheet: {e}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            return []
    
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
    
    def _ensure_qualification_headers(self, leads_sheet) -> None:
        """Ensure the Leads sheet has all required headers for qualification.
        
        Args:
            leads_sheet: The Leads worksheet object
        """
        headers = leads_sheet.row_values(1)
        required_headers = [
            "user_id", "username", "status", "initial_message", "timestamp",
            "name", "phone", "pet_breed", "pet_weight", "pet_age", "pet_coat"
        ]
        
        missing_headers = [h for h in required_headers if h not in headers]
        if missing_headers:
            for header in missing_headers:
                col_index = len(headers) + 1
                leads_sheet.update_cell(1, col_index, header)
                headers.append(header)
            logger.info(f"Added missing headers: {missing_headers}")

