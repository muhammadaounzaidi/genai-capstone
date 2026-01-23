"""Google Sheets service for managing leads, pets, services, and bookings."""
import json
import logging
import os
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
        spreadsheet = self.client.open_by_key(self.sheets_id)
        
        try:
            leads_sheet = spreadsheet.worksheet("Leads")
        except gspread.exceptions.WorksheetNotFound:
            logger.info("Leads worksheet not found, creating it")
            leads_sheet = spreadsheet.add_worksheet(title="Leads", rows=1000, cols=10)
            leads_sheet.append_row(["user_id", "username", "status", "initial_message", "timestamp"])
        
        timestamp = datetime.now().isoformat()
        lead_data = {
            "user_id": user_id,
            "username": username,
            "status": "initiated",
            "initial_message": message,
            "timestamp": timestamp,
        }
        
        row = [
            lead_data["user_id"],
            lead_data["username"],
            lead_data["status"],
            lead_data["initial_message"],
            lead_data["timestamp"],
        ]
        
        existing_headers = leads_sheet.row_values(1) if leads_sheet.row_values(1) else []
        if not existing_headers:
            leads_sheet.append_row(["user_id", "username", "status", "initial_message", "timestamp"])
        
        leads_sheet.append_row(row)
        logger.info(f"Created lead for user {username} (ID: {user_id})")
        return lead_data
    
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

