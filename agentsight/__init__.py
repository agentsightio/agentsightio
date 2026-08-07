"""AgentSight Python SDK.

The tracking surface is OpenTelemetry-based and lives at the top level::

    import agentsight

    agentsight.init()

    with agentsight.conversation("wa-3859"):
        with agentsight.turn():
            agentsight.user_message(text)
            ...                          # tokens, cost and tool calls captured
            agentsight.agent_message(reply)

Alongside it, the data-plane clients for fetching and managing what was
tracked: ``agentsight_api`` (read) and ``conversation_manager`` (manage).
"""

from agentsight.client.api_client import AgentSightAPI, agentsight_api
from agentsight.client.conversation_manager_client import (
    ConversationManager,
    conversation_manager,
)
from agentsight.sdk import (
    UploadError,
    abandon_turn,
    agent_message,
    attachments,
    button,
    conversation,
    end_turn,
    flush,
    init,
    is_enabled,
    open_conversation,
    register_price,
    shutdown,
    task,
    tool,
    turn,
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
    "attachments",
    # the data plane: moves bytes, blocks, and raises — see sdk/uploads.py
    "upload_attachments",
    "UploadError",
    # cost of a model the bundled price table has never heard of
    "register_price",
    # data-plane clients
    "AgentSightAPI",
    "agentsight_api",
    "ConversationManager",
    "conversation_manager",
]
