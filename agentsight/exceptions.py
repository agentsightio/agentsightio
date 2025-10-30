class NoApiKeyException(Exception):
    def __init__(
        self,
        message="Could not initialize AgentSight client - API Key is missing."
        + "\n\t    Find your API key at https://app.agentsight.io/settings",
    ):
        super().__init__(message)


class InvalidApiKeyException(Exception):
    def __init__(self, api_key, app_url):
        message = f"API Key is invalid: {api_key}.\n\t    Find your API key at {app_url}/settings"
        super().__init__(message)


class ApiServerException(Exception):
    def __init__(self, message):
        super().__init__(message)


class AgentSightClientNotInitializedException(RuntimeError):
    def __init__(self, message="AgentSight client must be initialized before using this feature"):
        super().__init__(message)


class AgentSightApiJwtExpiredException(Exception):
    def __init__(self, message="JWT token has expired"):
        super().__init__(message)


class ConversationTrackingException(Exception):
    """Base exception for conversation tracking errors."""
    def __init__(self, message):
        super().__init__(message)


class InvalidConversationDataException(ConversationTrackingException):
    """Exception for invalid conversation data."""
    def __init__(self, message="Invalid conversation data provided"):
        super().__init__(message)

class InvalidAnswerDataException(ConversationTrackingException):
    """Exception for invalid conversation data."""
    def __init__(self, message="Invalid answer data provided"):
        super().__init__(message)

class InvalidQuestionDataException(ConversationTrackingException):
    """Exception for invalid conversation data."""
    def __init__(self, message="Invalid question data provided"):
        super().__init__(message)

class MissingConversationIdException(Exception):
    """Raised when conversation_id is missing or empty."""
    def __init__(self, message: str = "Conversation ID is required and cannot be empty"):
        super().__init__(message)

class NoDataToSendException(Exception):
    """Raised when attempting to send data but no data is tracked."""
    def __init__(self, message: str = "No tracked data found for conversation."):
        super().__init__(message)

class ConversationApiException(ConversationTrackingException):
    """Exception for conversation API errors."""
    def __init__(self, message, status_code=None, response_data=None):
        super().__init__(message)
        self.status_code = status_code
        self.response_data = response_data


class ConversationNetworkException(ConversationTrackingException):
    """Exception for conversation tracking network errors."""
    def __init__(self, message):
        super().__init__(message)


class InvalidAttachmentException(Exception):
    """Exception raised when attachment data is invalid or too large."""
    
    def __init__(self, message: str = "Invalid attachment data provided"):
        self.message = message
        super().__init__(self.message)