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
    # Validate configuration
    if not Config.validate():
        logger.error("Missing required configuration. Please check your .env file.")
        logger.error("Required: GOOGLE_API_KEY, DISCORD_BOT_TOKEN, GOOGLE_SHEETS_ID")
        sys.exit(1)
    
    # Create and run bot
    bot = GroomingBot()
    try:
        bot.run(Config.DISCORD_BOT_TOKEN)
    except Exception as e:
        logger.error(f"Failed to start bot: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()

