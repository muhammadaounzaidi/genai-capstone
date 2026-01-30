"""Discord bot handler for the grooming business agent."""
import logging
import time
import discord
from discord.ext import commands, tasks
from agents.base import BaseAgent
from agents.langgraph_agent import LangGraphAgent
from services.google_sheets_service import GoogleSheetsService
from services.google_calendar_service import GoogleCalendarService
from config import Config

logger = logging.getLogger(__name__)

REMINDER_STALL_SECONDS = 60
REMINDER_MESSAGE = (
    "Hi! Just checking in - I noticed we didn't finish booking your appointment. "
    "Would you like to continue? I'm happy to help you schedule a grooming session for your pet!"
)


class GroomingBot(commands.Bot):
    """Discord bot for grooming business following SRP."""
    
    def __init__(self, agent_type: str = "langgraph"):
        """Initialize the Discord bot.
        
        Args:
            agent_type: Type of agent to use ("langgraph" or "mcp" in future)
        """
        intents = discord.Intents.default()
        # message_content is a privileged intent required for reading message content in DMs
        # This must be enabled in the Discord Developer Portal:
        # https://discord.com/developers/applications/
        intents.message_content = True
        
        super().__init__(command_prefix="!", intents=intents)
        
        self.sheets_service = GoogleSheetsService(
            sheets_id=Config.GOOGLE_SHEETS_ID,
            api_key=Config.GOOGLE_API_KEY,
        )
        self.calendar_service = None
        if Config.GOOGLE_CALENDAR_ID:
            self.calendar_service = GoogleCalendarService(calendar_id=Config.GOOGLE_CALENDAR_ID)
        
        self.agent: BaseAgent = self._create_agent(agent_type)
        
        self.conversations: dict[str, list] = {}
        self.last_state_by_user: dict[str, dict] = {}
        self.discord_user_cache: dict[str, int] = {}
    
    def _create_agent(self, agent_type: str) -> BaseAgent:
        """Create an agent instance based on the specified type.
        
        Args:
            agent_type: Type of agent to create
            
        Returns:
            Agent instance implementing BaseAgent
        """
        if agent_type == "langgraph":
            return LangGraphAgent(self.sheets_service, self.calendar_service)
        elif agent_type == "mcp":
            # Future: return MCPAgent(self.sheets_service)
            raise NotImplementedError("MCP agent not yet implemented")
        else:
            raise ValueError(f"Unknown agent type: {agent_type}")
    
    async def on_ready(self):
        """Called when bot is ready."""
        logger.info(f"{self.user} has connected to Discord!")
        if not self.check_stalled_leads.is_running():
            self.check_stalled_leads.start()
    
    async def on_message(self, message: discord.Message):
        """Handle incoming messages."""
        # Ignore messages from the bot itself
        if message.author == self.user:
            return
        
        # Only respond to DMs or mentions
        if isinstance(message.channel, discord.DMChannel) or self.user.mentioned_in(message):
            try:
                user_id = str(message.author.id)
                conversation_history = self.conversations.get(user_id, [])
                last_state = self.last_state_by_user.get(user_id)
                
                result = await self.agent.process_message(
                    user_id=user_id,
                    username=message.author.name,
                    message=message.content,
                    conversation_history=conversation_history,
                    last_state=last_state,
                )
                
                response = result.get("response", "I'm here to help!")
                if result.get("state"):
                    self.last_state_by_user[user_id] = result["state"]
                
                self.discord_user_cache[user_id] = message.author.id
                
                conversation_history.append({"role": "user", "content": message.content})
                conversation_history.append({"role": "assistant", "content": response})
                self.conversations[user_id] = conversation_history
                
                await message.channel.send(response)
            except Exception as e:
                logger.error(f"Error processing message: {e}")
                await message.channel.send(
                    "I apologize, but I encountered an error processing your message. "
                    "Please try again later."
                )
        
        # Process commands
        await self.process_commands(message)

    @tasks.loop(minutes=1)
    async def check_stalled_leads(self):
        """Background task: check for stalled leads and send reminders."""
        now = time.time()
        for user_id, state in list(self.last_state_by_user.items()):
            if state.get("appointment_booked"):
                continue
            if state.get("reminder_sent"):
                continue
            if not (state.get("lead_created") or state.get("lead_qualified")):
                continue
            last_interaction = state.get("last_interaction_at")
            if not last_interaction:
                continue
            if now - last_interaction < REMINDER_STALL_SECONDS:
                continue
            discord_id = self.discord_user_cache.get(user_id)
            if not discord_id:
                continue
            try:
                user = await self.fetch_user(discord_id)
                if user:
                    await user.send(REMINDER_MESSAGE)
                    state["reminder_sent"] = True
                    self.last_state_by_user[user_id] = state
                    logger.info(f"Sent reminder to stalled lead {user_id}")
            except discord.Forbidden:
                logger.warning(f"Cannot send DM to user {user_id} (DMs disabled)")
            except Exception as e:
                logger.error(f"Error sending reminder to {user_id}: {e}")

    @check_stalled_leads.before_loop
    async def before_check_stalled_leads(self):
        """Wait until the bot is ready before starting the loop."""
        await self.wait_until_ready()

