"""Turning Python keyword arguments into query strings the backend accepts.

Small, but it is where three recurring wire details live: Django reads booleans
as the lowercase strings ``true``/``false``, datetimes have to be ISO-8601, and
a filter that was not passed must be absent rather than sent as ``None``.
"""

from datetime import date, datetime
from typing import Any, Dict, Iterable, Optional

from agentsight.exceptions import ValidationError

SENTIMENTS = ("positive", "neutral", "negative")

#: Filters ``GET /api/conversations/`` understands. Anything else is refused
#: locally rather than silently ignored by the backend, because a filter that
#: does not apply returns *more* rows than the caller asked for, and a typo
#: that widens a result set is worse than one that errors.
CONVERSATION_FILTERS = frozenset(
    {
        "action_name",
        "conversation_id",
        "customer_id",
        "customer_id__icontains",
        "customer_ip_address",
        "device",
        "env",
        "environment",
        "feedback_sentiment",
        "has_feedback",
        "has_messages",
        "include_deleted",
        "is_marked",
        "language",
        "message_contains",
        "metadata",
        "metadata_key",
        "metadata_value",
        "name",
        "ordering",
        "search",
        "started_at_after",
        "started_at_before",
    }
)

FEEDBACK_FILTERS = frozenset(
    {
        "agent",
        "category",
        "comment_contains",
        "conversation",
        "conversation_id",
        "created_at_after",
        "created_at_before",
        "env",
        "environment",
        "has_comment",
        "has_ticket",
        "kind",
        "ordering",
        "search",
        "sentiment",
        "ticket_status",
        "user",
    }
)

ACTION_FILTERS = frozenset({"agent", "name", "ordering", "search"})

BUTTON_FILTERS = frozenset({"agent", "button_event", "conversation", "ordering", "value"})


def format_value(value: Any) -> Any:
    """One filter value, in the form the backend parses."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, (list, tuple, set)):
        # django-filter's multi-value fields repeat the key; requests does
        # that for a list, so preserve the sequence rather than joining it.
        return [format_value(item) for item in value]
    return value


def build(
    filters: Dict[str, Any],
    allowed: Iterable[str],
    *,
    what: str,
) -> Dict[str, Any]:
    """Validate filter names, drop the unset ones, format the rest."""
    allowed = frozenset(allowed)
    unknown = sorted(set(filters) - allowed)
    if unknown:
        raise ValidationError(
            f"unknown {what} filter(s): {', '.join(unknown)}. "
            f"Supported: {', '.join(sorted(allowed))}"
        )

    params: Dict[str, Any] = {}
    for key, value in filters.items():
        if value is None:
            continue
        # `environment` and `env` are the same backend filter; send one name.
        params["env" if key == "environment" else key] = format_value(value)
    return params


def check_sentiment(sentiment: Optional[str]) -> Optional[str]:
    if sentiment is None:
        return None
    if sentiment not in SENTIMENTS:
        raise ValidationError(
            f"sentiment must be one of {', '.join(SENTIMENTS)}, got {sentiment!r}"
        )
    return sentiment
