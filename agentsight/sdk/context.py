"""Ambient conversation and turn state.

Both live in :class:`contextvars.ContextVar`, which is what makes the scopes
correct under asyncio and threads without the caller threading anything
through: a web server handling two users concurrently gets two independent
scopes, and an ``await`` in the middle of a turn does not lose it.

This is the reason the conversation id is not a process global, as it
effectively was in 0.0.x (``config.conversation_id``).
"""

from contextvars import ContextVar
from typing import TYPE_CHECKING, Any, Dict, Optional

if TYPE_CHECKING:  # pragma: no cover
    from agentsight.sdk.scopes import ConversationScope, TurnScope

_conversation_var: ContextVar[Optional["ConversationScope"]] = ContextVar(
    "agentsight_conversation", default=None
)
_turn_var: ContextVar[Optional["TurnScope"]] = ContextVar(
    "agentsight_turn", default=None
)
_model_hint_var: ContextVar[Optional[str]] = ContextVar(
    "agentsight_model_hint", default=None
)


def current_conversation() -> Optional["ConversationScope"]:
    return _conversation_var.get()


def current_turn() -> Optional["TurnScope"]:
    return _turn_var.get()


def set_conversation(scope: Optional["ConversationScope"]):
    return _conversation_var.set(scope)


def reset_conversation(token) -> None:
    try:
        _conversation_var.reset(token)
    except ValueError:
        # Reset from a different context than the set — can happen when a
        # scope is entered and exited across task boundaries. Falling back to
        # a plain clear is better than raising into user code.
        _conversation_var.set(None)


def set_turn(scope: Optional["TurnScope"]):
    return _turn_var.set(scope)


def reset_turn(token) -> None:
    try:
        _turn_var.reset(token)
    except ValueError:
        _turn_var.set(None)


def current_model_hint() -> Optional[str]:
    """The model name declared by the innermost ``agentsight.model_hint(...)``.

    A fallback, never an override: consumed only when a call resolves no model
    of its own — see :func:`record_llm_call`. Integrations that record after
    their block may have exited (streams record when they drain) snapshot this
    at call start instead of reading it here at record time.
    """
    return _model_hint_var.get()


def set_model_hint(value: Optional[str]):
    return _model_hint_var.set(value)


def reset_model_hint(token) -> None:
    try:
        _model_hint_var.reset(token)
    except ValueError:
        _model_hint_var.set(None)


def tracking_enabled() -> bool:
    """False when there is no scope, or the scope was opened ``enabled=False``.

    The second case exists for traffic the application knows is not real —
    ``webtasy`` has both a ``save=False`` flag and a testing mode.
    """
    scope = current_conversation()
    return scope is not None and scope.enabled


def conversation_attributes() -> Dict[str, Any]:
    """Attributes every span inherits from the active conversation.

    Stamped onto each span rather than sent once, because a conversation has
    no single owning span: it outlives any one process, so there is nothing to
    attach it to. The exporter groups by these to rebuild the Conversation row.
    """
    scope = current_conversation()
    return dict(scope.attributes) if scope else {}
