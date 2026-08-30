"""Turning Python keyword arguments into query strings the backend accepts.

Small, but it is where three recurring wire details live: Django reads booleans
as the lowercase strings ``true``/``false``, datetimes have to be ISO-8601, and
a filter that was not passed must be absent rather than sent as ``None``.
"""

from datetime import date, datetime
from typing import Any, Dict, Iterable, Mapping, Optional

from agentsight.exceptions import ValidationError

SENTIMENTS = ("positive", "neutral", "negative")

#: ``environment`` and ``env`` are the same filter on the conversation and
#: feedback routes, and only one name may go on the wire.
#:
#: This is **not** universal, which is why it is a parameter of :func:`build`
#: rather than a rule inside it. ``/api/token-usage/`` names its filter
#: ``environment`` and does not answer to ``env`` — sending the wrong one there
#: is silently ignored, which returns *more* rows than the caller asked for,
#: the exact failure this module exists to prevent.
ENV_ALIAS = {"environment": "env"}

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
        "has_action",
        "has_feedback",
        "has_messages",
        "include_deleted",
        # Filters AND includes: narrows to conversations with at least one
        # ticket, and each returned row then carries its tickets at full
        # depth. See Conversations.list for the caveat callers get wrong.
        "include_tickets",
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
        # The gate to the ticket surface of this route: narrows to feedback
        # rows that carry a ticket, and opens the nested ``ticket`` (at full
        # depth, discussion thread included), the per-status ``counts``, and
        # the two ticket filters below. Without it those filters answer 400
        # and payloads carry no ticket data. Same name and coupling as the
        # conversations twin; see Feedbacks.list.
        "include_tickets",
        "has_ticket",
        "kind",
        "ordering",
        "search",
        "sentiment",
        # Accepts a list — ``ticket_status=["open", "in_progress"]`` ORs, sent
        # as repeated keys.
        "ticket_status",
        "user",
    }
)

#: ``/api/tickets/`` — the workflow items filed against this agent.
#:
#: No ``agent`` (same reasoning as ACTION_FILTERS below) and no
#: ``environment``: the route has no environment filter — a ticket records the
#: environment it was created in, but the backend does not filter on it.
#: ``conversation`` is the integer pk and ``conversation_id`` the business
#: string, the same split the feedback route makes.
TICKET_FILTERS = frozenset(
    {
        "conversation",
        "conversation_id",
        "created_at_after",
        "created_at_before",
        "has_conversation",
        "has_feedback",
        "ordering",
        "priority",
        "search",
        # Accepts a list — ``status=["open", "in_progress"]`` ORs, sent as
        # repeated keys.
        "status",
        # Comma-separated: ``tags="checkout,billing"`` matches tickets
        # carrying ANY of the named tags.
        "tags",
        "updated_at_after",
        "updated_at_before",
    }
)

#: The ticket lifecycle, as the dashboard's board columns order it.
TICKET_STATUSES = ("backlog", "open", "in_progress", "in_review", "done", "closed")
TICKET_PRIORITIES = ("low", "medium", "high")

#: Note the absence of ``agent``: an API key is bound to exactly one agent and
#: the scoping is applied before any filter runs, so the parameter could only
#: ever be a no-op or a contradiction. The same is true on ``/api/buttons/``,
#: which this client no longer reads.
ACTION_FILTERS = frozenset(
    {
        "display_name",
        "name",
        "name__icontains",
        "ordering",
        "search",
    }
)

#: ``/api/token-usage/`` — what spend cost, one row per (turn, model).
#:
#: ``environment`` here accepts any slug the agent owns, unlike the fixed
#: ``production|development|prod|dev`` choice list the conversation and feedback
#: routes still enforce. That asymmetry is deliberate on the backend's side;
#: do not "fix" this set to match the others.
USAGE_FILTERS = frozenset(
    {
        "conversation",
        "conversation_id",
        "cost_source",
        "environment",
        "incomplete",
        "model",
        "ordering",
        "started_at_after",
        "started_at_before",
        "turn_id",
    }
)

#: ``/api/spans/`` — the raw span archive.
#:
#: Small on purpose. The route's filters are built around the three indexes the
#: span table has, so what is offered is what the database can serve; there is
#: no substring match on ``name`` and no way to filter inside ``attributes``.
#: ``environment`` follows the token-usage spelling, not the ``env`` alias.
#:
#: No ``kind`` allowlist here on purpose either: the backend stores whatever
#: kind an SDK sends rather than rejecting unknown ones, so a fixed tuple in
#: this release would refuse data a newer release legitimately produces.
SPAN_FILTERS = frozenset(
    {
        "conversation",
        "conversation_id",
        "environment",
        "kind",
        "name",
        "ordering",
        "parent_span_id",
        "span_id",
        "started_at_after",
        "started_at_before",
        "status",
        "trace_id",
    }
)

#: How spend was priced, as reported on every usage row.
COST_SOURCES = ("backend", "reported", "unpriced")

USAGE_GROUP_BY = ("model", "conversation", "day")
USAGE_CURRENCIES = ("usd", "eur")


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
    rename: Optional[Mapping[str, str]] = None,
) -> Dict[str, Any]:
    """Validate filter names, drop the unset ones, format the rest.

    ``rename`` maps a caller-facing filter name onto the name the route
    actually answers to, and defaults to :data:`ENV_ALIAS`. Pass ``{}`` for a
    route that wants the caller-facing spelling verbatim.
    """
    allowed = frozenset(allowed)
    unknown = sorted(set(filters) - allowed)
    if unknown:
        raise ValidationError(
            f"unknown {what} filter(s): {', '.join(unknown)}. "
            f"Supported: {', '.join(sorted(allowed))}"
        )

    rename = ENV_ALIAS if rename is None else rename
    params: Dict[str, Any] = {}
    for key, value in filters.items():
        if value is None:
            continue
        params[rename.get(key, key)] = format_value(value)
    return params


def check_choice(
    value: Optional[str], choices: Iterable[str], *, what: str
) -> Optional[str]:
    """One of a fixed set, or a local error naming the set.

    Same reasoning as the filter names above: a value the backend does not
    recognise is either a 400 round trip or, worse, silently ignored.
    """
    if value is None:
        return None
    choices = tuple(choices)
    if value not in choices:
        raise ValidationError(
            f"{what} must be one of {', '.join(choices)}, got {value!r}"
        )
    return value


def check_sentiment(sentiment: Optional[str]) -> Optional[str]:
    return check_choice(sentiment, SENTIMENTS, what="sentiment")
