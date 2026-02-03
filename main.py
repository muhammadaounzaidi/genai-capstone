"""Main entry point for the grooming business Discord bot."""
import logging
import sys
from discord_bot import GroomingBot
from config import Config

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
    ],
)

logger = logging.getLogger(__name__)


def main():
    """Main function to start the Discord bot."""
    # Validate basic configuration
    if not Config.validate():
        logger.error("Missing required configuration. Please check your .env file.")
        logger.error("Required: GOOGLE_API_KEY, DISCORD_BOT_TOKEN, GOOGLE_SHEETS_ID")
        sys.exit(1)
    
    # Validate Google Sheets authentication
    is_valid, error_msg = Config.validate_sheets_auth()
    if not is_valid:
        logger.error(error_msg)
        sys.exit(1)
    
    # Create and run bot (set AGENT_TYPE=mcp in .env to use Pydantic AI + MCP instead of LangGraph)
    agent_type = getattr(Config, "AGENT_TYPE", "langgraph") or "langgraph"
    if agent_type not in ("langgraph", "mcp"):
        logger.warning(f"Unknown AGENT_TYPE={agent_type}, using langgraph")
        agent_type = "langgraph"
    bot = GroomingBot(agent_type=agent_type)
    try:
        bot.run(Config.DISCORD_BOT_TOKEN)
    except Exception as e:
        error_message = str(e)
        if "privileged intents" in error_message.lower():
            logger.error("Failed to start bot: Privileged intents are required but not enabled.")
            logger.error("")
            logger.error("To fix this issue:")
            logger.error("1. Go to https://discord.com/developers/applications/")
            logger.error("2. Select your bot application")
            logger.error("3. Navigate to the 'Bot' section in the left sidebar")
            logger.error("4. Scroll down to 'Privileged Gateway Intents'")
            logger.error("5. Enable 'MESSAGE CONTENT INTENT'")
            logger.error("6. Save changes and restart the bot")
            logger.error("")
            logger.error(f"Technical details: {e}")
        else:
            logger.error(f"Failed to start bot: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()

