"""Reading and submitting feedback."""

from typing import Any, Dict, Optional, Union

from agentsight.api import _params
from agentsight.api._pagination import Page, PageIterator
from agentsight.api.resources._base import Resource
from agentsight.exceptions import ValidationError

_UPDATABLE = ("sentiment", "comment")


class Feedbacks(Resource):
    """``ags.feedbacks`` — the unified feedback surface.

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
        ``env``), ``has_comment``, ``kind``, ``ordering``, ``search``,
        ``sentiment``, ``user``.

        Tickets are not filterable here — see :meth:`get`.
        """
        return PageIterator(self._fetch, self._filters(filters))

    def page(self, number: int = 1, **filters: Any) -> Page:
        """One page, with the aggregate count the envelope carries.

        ``Page.extra["counts"]`` holds ``{"all": N}`` — how many rows match the
        filters, which is the same number as ``Page.count`` and is kept only
        because the envelope publishes it.

        Earlier versions of this client documented ticket aggregates here too
        (``tickets``, ``open_tickets``, and the per-status tallies). Those are
        internal workflow state and are no longer sent to an API key.
        """
        return PageIterator(self._fetch, self._filters(filters)).page(number)

    def get(self, feedback_id: int) -> Dict[str, Any]:
        """One feedback row.

        No ``ticket`` key: tickets are internal workflow state and are not
        exposed on the API-key plane, so the field is absent rather than null
        on every payload here — list, retrieve and the echo from a create.
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
    return _params.check_sentiment(sentiment)
