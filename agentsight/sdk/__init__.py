"""AgentSight 1.0 SDK — the complete public surface.

In 1.0 these names are promoted to the top-level ``agentsight`` package. While
the 0.0.x clients still exist they live here, so the two do not collide::

    from agentsight.sdk import init, conversation, turn, user_message, agent_message

See ``design/otel-migration.md`` for the design and ``design/demo.py`` for
worked examples.
"""

from agentsight.sdk.api import (
    abandon_turn,
    agent_message,
    attachments,
    button,
    conversation,
    end_turn,
    open_conversation,
    user_message,
    wrap,
)
from agentsight.sdk.core import flush, init, is_enabled, shutdown
from agentsight.sdk.decorators import task, tool
from agentsight.sdk.instrumentation import register_price
from agentsight.sdk.scopes import turn

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
    # cost of a model the bundled price table has never heard of
    "register_price",
]
