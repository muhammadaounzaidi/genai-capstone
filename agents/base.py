"""Base agent interface for different implementations."""
from abc import ABC, abstractmethod
from typing import Dict, Any


class BaseAgent(ABC):
    """Abstract base class for agent implementations following SRP."""
    
    @abstractmethod
    async def process_message(
        self,
        user_id: str,
        username: str,
        message: str,
        conversation_history: list = None
    ) -> Dict[str, Any]:
        """Process a user message and return a response.
        
        Args:
            user_id: Unique identifier for the user
            username: Username of the user
            message: The message content from the user
            conversation_history: Optional list of previous messages
            
        Returns:
            Dictionary containing response and any additional state information
        """
        pass
    
    @abstractmethod
    def create_lead(self, user_id: str, username: str, message: str) -> Dict[str, Any]:
        """Create a new lead record.
        
        Args:
            user_id: Unique identifier for the user
            username: Username of the user
            message: Initial message from the user
            
        Returns:
            Dictionary containing lead information
        """
        pass

