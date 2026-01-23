"""Configuration management for the grooming business agent."""
import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    """Centralized configuration class following SRP."""
    
    GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
    DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
    GOOGLE_SHEETS_ID = os.getenv("GOOGLE_SHEETS_ID")
    GOOGLE_CALENDAR_ID = os.getenv("GOOGLE_CALENDAR_ID")
    
    @classmethod
    def validate(cls) -> bool:
        """Validate that all required configuration is present."""
        required_vars = [
            cls.GOOGLE_API_KEY,
            cls.DISCORD_BOT_TOKEN,
            cls.GOOGLE_SHEETS_ID,
        ]
        return all(var for var in required_vars)

