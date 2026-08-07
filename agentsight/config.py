import json
import os
from dataclasses import dataclass, field
from typing import Optional, TypedDict, Union

from agentsight import _settings
from agentsight.enums import Environment, LogLevel
from agentsight.exceptions import InvalidApiKeyError
from agentsight.helpers.serialization import AgentSightJSONEncoder

#: Shared with both planes — see :mod:`agentsight._settings`.
API_KEY_PATTERN = _settings.API_KEY_PATTERN

class ConfigDict(TypedDict):
    api_key: Optional[str]
    endpoint: str
    app_url: str
    conversation_id: Optional[str]
    log_level: Union[str, LogLevel]


@dataclass
class Config:
    api_key: Optional[str] = field(
        default_factory=lambda: os.getenv("AGENTSIGHT_API_KEY"),
        metadata={"description": "API key for authentication with AgentSight services"},
    )

    endpoint: str = field(
        default_factory=lambda: os.getenv("AGENTSIGHT_API_ENDPOINT", _settings.DEFAULT_ENDPOINT),
        metadata={"description": "Base URL for the AgentSight API"},
    )

    app_url: str = field(
        default_factory=lambda: os.getenv("AGENTSIGHT_APP_URL", _settings.DEFAULT_APP_URL),
        metadata={"description": "Dashboard URL for the AgentSight application"},
    )

    environment: Optional[Environment] = field(
        default_factory=lambda: os.getenv("AGENTSIGHT_ENVIRONMENT"),
        metadata={"description": "Specifies environment for saving tracking data"},
    )

    conversation_id: Optional[str] = field(
        default_factory=lambda: os.getenv("AGENTSIGHT_CONVERSATION_ID"),
        metadata={"description": "Conversation ID for tracking"},
    )

    log_level: LogLevel = field(
        default_factory=lambda: LogLevel.from_string(os.getenv("AGENTSIGHT_LOG_LEVEL", "INFO")),
        metadata={"description": "Logging level for AgentSight"},
    )

    # agent_type: AgentType = field(
    #     default_factory=lambda: os.getenv("AGENTSIGHT_AGENT_TYPE", "agent"),
    #     metadata={"description": "Logging level for AgentSight"},
    # )

    def __post_init__(self):
        """
        Validate and normalize fields after the object is initialized.
        This method is called automatically by the dataclass constructor.
        """
        if self.api_key:
            if not self.api_key.strip():
                self.api_key = None
            elif not API_KEY_PATTERN.match(self.api_key):
                raise InvalidApiKeyError(self.api_key, self.app_url)

        if isinstance(self.log_level, str):
            self.log_level = LogLevel.from_string(self.log_level)

    def configure(
        self,
        api_key: Optional[str] = None,
        endpoint: Optional[str] = None,
        app_url: Optional[str] = None,
        environment: Optional[Environment|None] = None,
        conversation_id: Optional[str] = None,
        log_level: Optional[Union[str, LogLevel]] = None,
    ):
        """Configure settings from kwargs, then re-run validation."""
        if api_key is not None:
            self.api_key = api_key

        if endpoint is not None:
            self.endpoint = endpoint

        if app_url is not None:
            self.app_url = app_url

        if environment is not None:
            self.environment = environment

        if conversation_id is not None:
            self.conversation_id = conversation_id

        if log_level is not None:
            self.log_level = log_level

        # Re-run all validations and normalizations after updating fields
        self.__post_init__()

    def dict(self) -> ConfigDict:
        """Return a dictionary representation of the config"""
        return {
            "api_key": self.api_key,
            "endpoint": self.endpoint,
            "app_url": self.app_url,
            "environment": self.environment,
            "conversation_id": self.conversation_id,
            "log_level": self.log_level
        }

    def json(self):
        """Return a JSON representation of the config"""
        return json.dumps(self.dict(), cls=AgentSightJSONEncoder)
