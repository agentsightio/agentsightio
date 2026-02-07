"""Enums for AgentSight configuration and types."""

from enum import Enum
from typing import Optional


class LogLevel(str, Enum):
    """Logging levels for AgentSight.
    
    Inherits from str so it can be used directly with logging module
    and serialized to JSON easily.
    """
    CRITICAL = "CRITICAL"
    ERROR = "ERROR"
    WARNING = "WARNING"
    INFO = "INFO"
    DEBUG = "DEBUG"
    
    @classmethod
    def from_string(cls, level: str) -> "LogLevel":
        """Create LogLevel from string, with fallback to INFO."""
        if isinstance(level, cls):
            return level
        
        level_upper = level.upper() if level else "INFO"
        
        try:
            return cls(level_upper)
        except ValueError:
            # Invalid level, return INFO as default
            return cls.INFO
    
class AgentType(Enum):
    """Types of agents that can be tracked."""
    
    CHATBOT = "chatbot"
    AGENT = "agent"
    VOICE = "voice"
    CUSTOM = "custom"

class AttachmentMode(Enum):
    BASE64 = "base64"
    FORM_DATA = "form_data"

class Sender(str, Enum):
    USER = "end_user"
    AGENT = "agent"
    SYSTEM = "system"

class Environment(Enum):
    PRODUCTION = "production"
    DEVELOPMENT = "development"

    @classmethod
    def from_env(cls, value: Optional[str]) -> Optional["Environment"]:
        if not value:
            return None
        try:
            return cls(value)
        except ValueError:
            valid = ", ".join([v.value for v in cls])
            raise ValueError(f"Invalid environment type '{value}'. Expected one of: {valid}")

class TokenHandlerType(Enum):
    LLAMAINDEX = "llamaindex"
    LANGCHAIN = "langchain"

    @classmethod
    def from_env(cls, value: Optional[str]) -> Optional["TokenHandlerType"]:
        if not value:
            return None
        try:
            return cls(value)
        except ValueError:
            valid = ", ".join([v.value for v in cls])
            raise ValueError(f"Invalid token handler type '{value}'. Expected one of: {valid}")
        
class Sentiment(str, Enum):
    """Sentiment values for conversation feedback."""
    POSITIVE = "positive"
    NEUTRAL = "neutral"
    NEGATIVE = "negative"
