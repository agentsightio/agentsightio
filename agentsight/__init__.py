"""AgentSight Python SDK.

The tracking surface is OpenTelemetry-based and lives at the top level::

    import agentsight

    agentsight.init()

    with agentsight.conversation("wa-3859"):
        with agentsight.turn():
            agentsight.user_message(text)
            ...                          # tokens, cost and tool calls captured
            agentsight.agent_message(reply)

Reading and managing what was tracked is a separate surface, in
:mod:`agentsight.api`::

    from agentsight.api import AgentSight

    ags = AgentSight()
    for conversation in ags.conversations.list(has_feedback=True):
        ...

Importing this package does nothing but define names — it opens no
connections, reads no configuration and never raises, whether or not an API
key is set.
"""

try:
    # Kept from 0.0.x, where it happened as a side effect of importing the
    # logging module that the deleted clients pulled in. Made explicit here
    # so it is a decision rather than an accident: a local AGENTSIGHT_API_KEY
    # in a .env file keeps working exactly as it did.
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # python-dotenv is a dev extra, not a runtime dependency
    pass

from agentsight.api import AgentSight
from agentsight.exceptions import (
    AgentSightError,
    APIError,
    AuthenticationError,
    ConfigurationError,
    InvalidApiKeyError,
    MethodNotAllowedError,
    MissingApiKeyError,
    NetworkError,
    NotFoundError,
    PermissionDeniedError,
    ServerError,
    SubscriptionInactiveError,
    UploadError,
    ValidationError,
)
from agentsight.sdk import (
    abandon_turn,
    agent_message,
    button,
    conversation,
    end_turn,
    flush,
    init,
    is_enabled,
    open_conversation,
    record_attachments,
    register_price,
    shutdown,
    task,
    tool,
    turn,
    update_metadata,
    upload_attachments,
    user_message,
    wrap,
)

__all__ = [
    # lifecycle
    "init",
    "flush",
    "shutdown",
    "is_enabled",
    # scopes
    "conversation",
    "turn",
    # lifetime — for work that outlives the block that started it
    "wrap",
    "end_turn",
    "abandon_turn",
    # messages — no rules: any number, any order, either sender
    "user_message",
    "agent_message",
    # work
    "tool",
    "task",
    # explicit, because nothing in the call stack can observe them
    "open_conversation",
    "button",
    "record_attachments",
    # enriching a conversation after the scope that opened it was built
    "update_metadata",
    # the data plane: moves bytes, blocks, and raises — see sdk/uploads.py
    "upload_attachments",
    # cost of a model the bundled price table has never heard of
    "register_price",
    # reading and managing what was tracked — agentsight.api
    "AgentSight",
    # errors
    "AgentSightError",
    "ConfigurationError",
    "MissingApiKeyError",
    "InvalidApiKeyError",
    "APIError",
    "AuthenticationError",
    "SubscriptionInactiveError",
    "PermissionDeniedError",
    "NotFoundError",
    "ValidationError",
    "MethodNotAllowedError",
    "ServerError",
    "NetworkError",
    "UploadError",
]
