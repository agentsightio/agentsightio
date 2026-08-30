"""Reading and filing tickets — the agent's workflow items."""

from typing import Any, Dict, List, Optional, Union

from agentsight.api import _params
from agentsight.api._pagination import Page, PageIterator
from agentsight.api.resources._base import Resource
from agentsight.exceptions import ValidationError

_UPDATABLE = ("title", "status", "priority", "tags")


class Tickets(Resource):
    """``ags.tickets`` — full CRUD on ``/api/tickets/``.

    Tickets are the workflow items a team tracks against an agent: bugs and
    tasks, optionally anchored to the conversation they are about. Until 016
    they were a dashboard-only surface; a key now gets the whole lifecycle,
    which is what lets an agent file its own ticket when a guardrail trips
    instead of escalating into a transcript nobody reads.

    Reads need a *read* key, writes a *write* key. Everything is scoped to
    the one agent the key is bound to — another agent's ticket id answers
    404, indistinguishable from an id that does not exist.

    **Writes are attributed to the key, not to a person.** A ticket or
    comment created here is authored as the API key's *name* (the label you
    gave it at creation; the agent's name if that is blank), and comments
    are recorded with the role ``"agent"`` so the dashboard can always tell
    machine-filed entries from human ones. Every write also notifies the
    whole team, the key's owner included — file tickets deliberately, not on
    every failed turn.

    **No write here is idempotent.** There is no dedupe key: a retried
    ``create`` files a second ticket and a retried ``add_comment`` posts a
    second comment. If you file tickets from automation, guard the call
    yourself (e.g. list first, or track what you filed).
    """

    # -- reading -----------------------------------------------------------

    def list(self, **filters: Any) -> PageIterator:
        """Tickets on this agent, newest first.

        Filters: ``conversation`` (pk), ``conversation_id`` (string),
        ``created_at_after``, ``created_at_before``, ``has_conversation``,
        ``has_feedback``, ``ordering``, ``priority``, ``search`` (title),
        ``status``, ``tags``, ``updated_at_after``, ``updated_at_before``.

        ``status`` accepts a list and ORs it —
        ``status=["open", "in_progress"]``. ``tags`` is comma-separated and
        matches tickets carrying any of the named tags. Every row carries its
        full ``comments`` thread; there is no summary depth on this route.
        """
        return PageIterator(self._fetch, self._filters(filters))

    def page(self, number: int = 1, **filters: Any) -> Page:
        """One page of tickets, same filters as :meth:`list`."""
        return PageIterator(self._fetch, self._filters(filters)).page(number)

    def get(self, ticket_id: int) -> Dict[str, Any]:
        """One ticket: title, status, priority, tags, environment, the
        nested ``conversation``/``feedback`` summaries and the full
        ``comments`` thread."""
        return self._request("GET", f"/api/tickets/{int(ticket_id)}/")

    def comments(self, ticket_id: int) -> PageIterator:
        """The ticket's discussion thread, oldest first.

        The same thread every ticket payload already embeds as ``comments``
        — use this paginated route only for very long threads.
        """
        path = f"/api/tickets/{int(ticket_id)}/comments/"
        return PageIterator(
            lambda query: self._request("GET", path, params=query), {}
        )

    # -- writing -----------------------------------------------------------

    def create(
        self,
        title: str,
        *,
        status: Optional[str] = None,
        priority: Optional[str] = None,
        tags: Optional[List[str]] = None,
        environment: Optional[str] = None,
        conversation: Optional[Union[int, str]] = None,
        feedback_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """File a ticket. *Write role.* **Not idempotent** — a retry files a
        second ticket; see the class docstring before calling this from
        automation.

        ``conversation`` anchors the ticket to the conversation it is about
        and takes either the business ``conversation_id`` string or the
        integer pk (strings cost one resolving request the first time; on
        the wire this route wants the pk). ``feedback_id`` records the
        feedback that prompted the ticket; product feedback is rejected, and
        a ticket created from conversation feedback inherits that feedback's
        conversation unless you anchor it explicitly.

        ``status`` defaults to ``open``, ``environment`` (a slug —
        ``ags.environments()`` lists them) to the agent's production
        environment. ``environment`` is write-once: it records where the
        problem was observed and cannot be changed later.

        The ticket is authored as the key's name and the whole team is
        notified.
        """
        if not title or not str(title).strip():
            raise ValidationError("title is required")
        payload: Dict[str, Any] = {"title": str(title).strip()}
        if status is not None:
            payload["status"] = _params.check_choice(
                status, _params.TICKET_STATUSES, what="status"
            )
        if priority is not None:
            payload["priority"] = _params.check_choice(
                priority, _params.TICKET_PRIORITIES, what="priority"
            )
        if tags is not None:
            payload["tags"] = list(tags)
        if environment is not None:
            payload["environment"] = environment
        if conversation is not None:
            # The write field is named conversation_id but wants the DB pk —
            # the serializer keeps `conversation` for its nested read-only
            # summary. The resolver papers over the asymmetry with the
            # feedback route, where conversation_id is the business string.
            payload["conversation_id"] = self._client._resolve(conversation)
        if feedback_id is not None:
            payload["feedback_id"] = int(feedback_id)
        return self._request("POST", "/api/tickets/", json=payload)

    def update(self, ticket_id: int, **fields: Any) -> Dict[str, Any]:
        """Change a ticket's ``title``, ``status``, ``priority`` or ``tags``.
        *Write role.*

        ``environment`` is write-once server-side and deliberately not
        updatable here; re-anchoring (``conversation``/``feedback``) stays a
        dashboard act.
        """
        unknown = sorted(set(fields) - set(_UPDATABLE))
        if unknown:
            raise ValidationError(
                f"cannot update: {', '.join(unknown)}. "
                f"Updatable fields: {', '.join(_UPDATABLE)}"
            )
        payload = {k: v for k, v in fields.items() if v is not None}
        if "status" in payload:
            payload["status"] = _params.check_choice(
                payload["status"], _params.TICKET_STATUSES, what="status"
            )
        if "priority" in payload:
            payload["priority"] = _params.check_choice(
                payload["priority"], _params.TICKET_PRIORITIES, what="priority"
            )
        if not payload:
            raise ValidationError("update() needs at least one field to change")
        return self._request(
            "PATCH", f"/api/tickets/{int(ticket_id)}/", json=payload
        )

    def delete(self, ticket_id: int) -> Dict[str, Any]:
        """Remove a ticket and its thread. *Write role.* Prefer closing
        (``update(id, status="closed")``) — a deleted ticket takes the
        discussion with it."""
        return self._request("DELETE", f"/api/tickets/{int(ticket_id)}/")

    def add_comment(self, ticket_id: int, body: str) -> Dict[str, Any]:
        """Post to the ticket's discussion thread. *Write role.* **Not
        idempotent** — a retry posts a second comment.

        The comment is recorded with the role ``"agent"`` and authored as
        the key's name, whatever else is sent — there is deliberately no
        ``role`` parameter. The team is notified.
        """
        if not body or not str(body).strip():
            raise ValidationError("body is required")
        return self._request(
            "POST",
            f"/api/tickets/{int(ticket_id)}/comments/",
            json={"body": str(body)},
        )

    # -- internals ---------------------------------------------------------

    def _filters(self, filters: Dict[str, Any]) -> Dict[str, Any]:
        if "status" in filters and isinstance(filters["status"], str):
            _params.check_choice(
                filters["status"], _params.TICKET_STATUSES, what="status"
            )
        if "priority" in filters:
            _params.check_choice(
                filters["priority"], _params.TICKET_PRIORITIES, what="priority"
            )
        return _params.build(filters, _params.TICKET_FILTERS, what="ticket")

    def _fetch(self, query: Dict[str, Any]) -> Any:
        return self._request("GET", "/api/tickets/", params=query)
