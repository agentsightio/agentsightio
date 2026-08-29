"""Reading and submitting feedback."""

from typing import Any, Dict, Optional, Union

from agentsight.api import _params
from agentsight.api._pagination import Page, PageIterator
from agentsight.api.resources._base import Resource
from agentsight.exceptions import ValidationError

_UPDATABLE = ("sentiment", "comment")


class Feedbacks(Resource):
    """``ags.feedbacks`` — the unified feedback surface.

    **The one place this client records what happened, and deliberately so.**
    Everywhere else the rule holds that observed data has exactly one way in:
    conversations, messages, action logs, buttons, attachments and spans are
    written by the tracking SDK, and the methods that would have duplicated
    that were removed. (:meth:`~agentsight.api.resources.actions.Actions.create`
    is not a counter-example: it declares an action *definition*, which is a
    capability rather than a record of a run, and tracking adopts it.) Feedback
    is the exception because it is not telemetry. Nothing about a run of the
    agent reveals whether a person was happy with it — somebody has to say so,
    and the moment they say it is a user action in the host application, not an
    event the SDK could ever observe. So there is no tracking-plane path for
    feedback, no span kind, and no inference: you call this when your user
    clicks the thumb.

    Feedback comes in three kinds server-side. Two are reachable with an API
    key: ``conversation`` (how a specific conversation went) and ``agent``
    (how the agent is doing overall, optionally scoped to an environment).
    The third, ``product``, is staff-only and has no method here.

    Everything goes through ``/api/feedbacks/``. The older
    ``/api/conversation-feedbacks/`` route that earlier SDK versions posted to
    is deprecated and scheduled for removal, and it silently discarded the
    ``metadata`` field those versions sent — which is why no method here takes
    one.
    """

    # -- reading -----------------------------------------------------------

    def list(self, **filters: Any) -> PageIterator:
        """Feedback matching ``filters``, newest first.

        Filters: ``agent``, ``category``, ``comment_contains``,
        ``conversation`` (pk), ``conversation_id`` (string),
        ``created_at_after``, ``created_at_before``, ``environment`` (or
        ``env``), ``has_comment``, ``has_ticket``, ``include_tickets``,
        ``kind``, ``ordering``, ``search``, ``sentiment``, ``ticket_status``,
        ``user``.

        **``include_tickets=True`` also narrows the result set** — it returns
        only feedback that was promoted to a ticket, and each of those rows
        then carries the nested ``ticket`` at full depth (title, status,
        priority, tags, ``comments_count`` and the ``comments`` thread).
        Adding it merely to see tickets loses every unpromoted row; without
        it, feedback payloads carry no ``ticket`` key at all.

        ``has_ticket`` and ``ticket_status`` work only alongside
        ``include_tickets=True`` — on their own the backend answers 400.
        ``ticket_status`` accepts a list and ORs it:
        ``ticket_status=["open", "in_progress"]``.
        """
        return PageIterator(self._fetch, self._filters(filters))

    def page(self, number: int = 1, **filters: Any) -> Page:
        """One page, with the aggregate counts the envelope carries.

        Without ``include_tickets=True``, ``Page.extra["counts"]`` holds
        ``{"all": N}`` — how many rows match the filters, the same number as
        ``Page.count``. With it, the ticket aggregates arrive alongside:
        ``tickets``, ``open_tickets``, and one tally per ticket status
        (``backlog``, ``open``, ``in_progress``, ``in_review``, ``done``,
        ``closed``). The tallies ignore any ``ticket_status`` filter on
        purpose, so a selected status does not zero the other buckets.
        """
        return PageIterator(self._fetch, self._filters(filters)).page(number)

    def get(self, feedback_id: int) -> Dict[str, Any]:
        """One feedback row.

        Carries the nested ``ticket`` unconditionally — at full depth,
        discussion thread included — or ``null`` when the feedback was never
        promoted. Asking for one row by id is itself the explicit act, so no
        parameter is needed here; only the *list* keeps tickets behind
        ``include_tickets=True``. (The echo from a create still has no
        ``ticket`` key.)
        """
        return self._request("GET", f"/api/feedbacks/{int(feedback_id)}/")

    # -- writing -----------------------------------------------------------

    def create_for_conversation(
        self,
        conversation: Union[int, str],
        sentiment: str,
        comment: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Record how one conversation went. *Write role.*

        ``conversation`` takes either the business ``conversation_id`` string
        or the integer pk; the backend resolves both, so this costs no extra
        round trip. ``sentiment`` is ``positive``, ``neutral`` or ``negative``.
        """
        payload: Dict[str, Any] = {
            "kind": "conversation",
            "sentiment": _require_sentiment(sentiment),
        }
        if isinstance(conversation, str):
            if not conversation.strip():
                raise ValidationError("conversation must not be empty")
            payload["conversation_id"] = conversation.strip()
        elif isinstance(conversation, int) and not isinstance(conversation, bool):
            payload["conversation"] = conversation
        else:
            raise ValidationError(
                "conversation must be an id string or an integer pk, got "
                f"{type(conversation).__name__}"
            )
        if comment:
            payload["comment"] = comment
        return self._request("POST", "/api/feedbacks/", json=payload)

    def create_for_agent(
        self,
        sentiment: str,
        comment: Optional[str] = None,
        *,
        agent: Optional[int] = None,
        environment: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Record how the agent is doing overall. *Write role.*

        ``agentsight.api.AgentSight().feedbacks.create_for_agent("positive")``
        is the whole call: ``agent`` defaults to the one your API key is bound
        to, resolved once through :meth:`AgentSight.me` and then cached. A key
        can only ever write to one agent, so naming it was redundant — and the
        pk used to be discoverable only as a side effect of listing
        conversations. Pass it explicitly only if you already have it.

        ``environment`` is a slug; ``ags.environments()`` lists the ones this
        agent has. It is accepted on this kind only — the backend rejects it on
        conversation feedback, which is why the two kinds have separate
        methods.
        """
        payload: Dict[str, Any] = {
            "kind": "agent",
            "agent": int(agent) if agent is not None else self._client.me()["agent_id"],
            "sentiment": _require_sentiment(sentiment),
        }
        if comment:
            payload["comment"] = comment
        if environment:
            payload["environment"] = environment
        return self._request("POST", "/api/feedbacks/", json=payload)

    def update(self, feedback_id: int, **fields: Any) -> Dict[str, Any]:
        """Change a feedback's ``sentiment`` or ``comment``. *Write role.*"""
        unknown = sorted(set(fields) - set(_UPDATABLE))
        if unknown:
            raise ValidationError(
                f"cannot update: {', '.join(unknown)}. "
                f"Updatable fields: {', '.join(_UPDATABLE)}"
            )
        payload = {k: v for k, v in fields.items() if v is not None}
        if "sentiment" in payload:
            payload["sentiment"] = _require_sentiment(payload["sentiment"])
        if not payload:
            raise ValidationError("update() needs at least one field to change")
        return self._request(
            "PATCH", f"/api/feedbacks/{int(feedback_id)}/", json=payload
        )

    def delete(self, feedback_id: int) -> Dict[str, Any]:
        """Remove a feedback row. *Write role.*"""
        return self._request("DELETE", f"/api/feedbacks/{int(feedback_id)}/")

    # -- internals ---------------------------------------------------------

    def _filters(self, filters: Dict[str, Any]) -> Dict[str, Any]:
        _params.check_sentiment(filters.get("sentiment"))
        return _params.build(filters, _params.FEEDBACK_FILTERS, what="feedback")

    def _fetch(self, query: Dict[str, Any]) -> Any:
        return self._request("GET", "/api/feedbacks/", params=query)


def _require_sentiment(sentiment: Any) -> str:
    if not sentiment:
        raise ValidationError(
            f"sentiment is required and must be one of {', '.join(_params.SENTIMENTS)}"
        )
    checked = _params.check_sentiment(sentiment)
    # check_sentiment returns None only for a None input, ruled out above.
    assert checked is not None
    return checked
