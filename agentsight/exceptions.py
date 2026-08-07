from typing import Any, Optional


class NoApiKeyException(Exception):
    """Exception for missing API key."""

    def __init__(
        self,
        message="Could not initialize AgentSight client - API Key is missing."
        + "\n\t    Find your API key at https://app.agentsight.io/settings",
    ):
        super().__init__(message)


class InvalidApiKeyException(Exception):
    """Exception for invalid API key."""

    def __init__(self, api_key, app_url):
        message = f"API Key is invalid: {api_key}.\n\t    Find your API key at {app_url}/settings"
        super().__init__(message)


class ConversationTrackingException(Exception):
    """Base exception for conversation tracking errors."""

    def __init__(self, message):
        super().__init__(message)


class InvalidConversationDataException(ConversationTrackingException):
    """Exception for invalid conversation data."""

    def __init__(self, message="Invalid conversation data provided"):
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


class NotFoundException(ConversationApiException):
    """Exception raised when a resource is not found (404)."""

    def __init__(self, message: str = "Resource not found"):
        super().__init__(message, status_code=404)


class UnauthorizedException(ConversationApiException):
    """Exception raised when authentication fails (401)."""

    def __init__(self, message: str = "Unauthorized - invalid or missing API key"):
        super().__init__(message, status_code=401)


class ForbiddenException(ConversationApiException):
    """Exception raised when access is forbidden (403)."""

    def __init__(self, message: str = "Forbidden - not authorized to access this resource"):
        super().__init__(message, status_code=403)


class UploadError(Exception):
    """The backend refused an upload, or the network failed getting there.

    Raised by ``agentsight.upload_attachments`` — the one call allowed to
    raise, because it moves customer data rather than telemetry.
    """

    def __init__(
        self,
        message: str,
        status_code: Optional[int] = None,
        response: Any = None,
    ):
        super().__init__(message)
        self.status_code = status_code
        self.response = response


class ToolFailure(Exception):
    """LangChain has already turned the tool's exception into a string.

    ``end_tool_span`` records an exception rather than a message, so what
    reaches it has to be one. This carries the text the framework kept and
    invents nothing else.
    """
