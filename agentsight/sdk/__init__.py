"""The OpenTelemetry-based tracking surface.

Every name here is re-exported by the top-level ``agentsight`` package, which
is the intended import path — ``from agentsight.sdk import ...`` works but is
an implementation detail.

See ``design/otel-migration.md`` for the design and ``design/demo.py`` for
worked examples.
"""

from agentsight.exceptions import UploadError
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
from agentsight.sdk.uploads import upload_attachments

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
]
