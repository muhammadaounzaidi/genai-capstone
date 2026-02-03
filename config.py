"""Configuration management for the grooming business agent."""
import os
import json
from typing import Tuple
from dotenv import load_dotenv

load_dotenv()


class Config:
    """Centralized configuration class following SRP."""

    GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
    DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
    GOOGLE_SHEETS_ID = os.getenv("GOOGLE_SHEETS_ID")
    GOOGLE_CALENDAR_ID = os.getenv("GOOGLE_CALENDAR_ID")
    GOOGLE_CREDENTIALS_FILE = os.getenv("GOOGLE_CREDENTIALS_FILE")
    GOOGLE_SERVICE_ACCOUNT_JSON = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
    AGENT_TYPE = os.getenv("AGENT_TYPE", "langgraph").strip().lower()
    
    @classmethod
    def validate(cls) -> bool:
        """Validate that all required configuration is present."""
        required_vars = [
            cls.GOOGLE_API_KEY,
            cls.DISCORD_BOT_TOKEN,
            cls.GOOGLE_SHEETS_ID,
        ]
        return all(var for var in required_vars)
    
    @classmethod
    def validate_sheets_auth(cls) -> Tuple[bool, str]:
        """Validate Google Sheets authentication configuration.
        
        Returns:
            Tuple of (is_valid, error_message). If is_valid is True, error_message is empty.
        """
        creds_file = cls.GOOGLE_CREDENTIALS_FILE
        service_account_json = cls.GOOGLE_SERVICE_ACCOUNT_JSON
        
        if creds_file:
            if not os.path.exists(creds_file):
                return False, f"GOOGLE_CREDENTIALS_FILE points to non-existent file: {creds_file}"
            try:
                with open(creds_file, 'r') as file:
                    json.load(file)
                return True, ""
            except json.JSONDecodeError as error:
                return False, f"Invalid JSON in {creds_file}: {error}"
            except Exception as error:
                return False, f"Error reading {creds_file}: {error}"
        elif service_account_json:
            try:
                json.loads(service_account_json)
                return True, ""
            except json.JSONDecodeError as error:
                return False, (
                    f"Invalid JSON in GOOGLE_SERVICE_ACCOUNT_JSON: {error}. "
                    "Tip: Use GOOGLE_CREDENTIALS_FILE with a file path instead."
                )
        else:
            return False, (
                "No Google Sheets authentication method found. "
                "Set either GOOGLE_CREDENTIALS_FILE or GOOGLE_SERVICE_ACCOUNT_JSON."
            )
    