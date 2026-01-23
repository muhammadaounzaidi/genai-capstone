"""Discord bot handler for the grooming business agent."""
import logging
import discord
from discord.ext import commands
from agents.base import BaseAgent
from agents.langgraph_agent import LangGraphAgent
from services.google_sheets_service import GoogleSheetsService
from config import Config

logger = logging.getLogger(__name__)


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
        
        # Initialize services
        self.sheets_service = GoogleSheetsService(
            sheets_id=Config.GOOGLE_SHEETS_ID,
            api_key=Config.GOOGLE_API_KEY,
        )
        
        # Initialize agent based on type
        self.agent: BaseAgent = self._create_agent(agent_type)
        
        # Store conversation history per user
        self.conversations: dict[str, list] = {}
    
    def _create_agent(self, agent_type: str) -> BaseAgent:
        """Create an agent instance based on the specified type.
        
        Args:
            agent_type: Type of agent to create
            
        Returns:
            Agent instance implementing BaseAgent
        """
        if agent_type == "langgraph":
            return LangGraphAgent(self.sheets_service)
        elif agent_type == "mcp":
            # Future: return MCPAgent(self.sheets_service)
            raise NotImplementedError("MCP agent not yet implemented")
        else:
            raise ValueError(f"Unknown agent type: {agent_type}")
    
    async def on_ready(self):
        """Called when bot is ready."""
        logger.info(f"{self.user} has connected to Discord!")
    
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
                
                result = await self.agent.process_message(
                    user_id=user_id,
                    username=message.author.name,
                    message=message.content,
                    conversation_history=conversation_history,
                )
                
                response = result.get("response", "I'm here to help!")
                
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

