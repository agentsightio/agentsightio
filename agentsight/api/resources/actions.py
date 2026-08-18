"""Action definitions and their logs."""

from typing import Any, Dict, List, Optional

from agentsight.api import _params
from agentsight.api._pagination import PageIterator
from agentsight.api.resources._base import Resource
from agentsight.exceptions import ValidationError

_UPDATABLE = ("name", "description", "display_name")


class Actions(Resource):
    """``ags.actions`` — the tools and steps your agent performs.

    An ``Action`` is a definition, not an event — ``search_orders`` the
    capability, rather than the eleven times it ran this morning.

    There are two ways one comes into being, and they converge. Tracking makes
    them as it goes: the first ``@tool`` or ``@task`` span carrying a name
    upserts that action by name. Or you declare one ahead of time with
    :meth:`create`, so a capability shows up in the dashboard before — or
    without — it has ever run. A declared action is then **adopted** by the
    first span that uses its name, not duplicated beside it, because tracking
    looks the row up by name rather than creating a second one.

    So a name belongs to one action per agent, and :meth:`create` refuses a
    name this agent already has. Two *different* agents holding an action
    called ``lookup_order`` is the normal case and is fine.

    There is deliberately no ``delete()``. Every recorded invocation hangs off
    the definition, so removing one would take that history with it; the route
    behind it refuses too. Rename or relabel with :meth:`update` instead.

    ``display_name`` and ``description`` decide how an action reads in the
    dashboard, and **a span carries neither** — so :meth:`update` is the only
    way to set them on an action tracking created.

    Individual invocations are action *logs*, written by the tracking SDK.
    :meth:`logs` reads them back.
    """

    def create(
        self,
        name: str,
        *,
        display_name: Optional[str] = None,
        description: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Declare an action before anything has performed it. *Write role.*

        ``name`` is the name spans are matched on, so use the one your ``@tool``
        or ``@task`` will carry — that is what makes the first real invocation
        attach to this row instead of creating a second one beside it.

        ``display_name`` defaults to ``name``, exactly as it does when tracking
        creates the action itself.

        Raises :class:`~agentsight.exceptions.ValidationError` if this agent
        already has an action with that name — the one error worth planning
        for. It is not returned as the existing row: you asked to create
        something, and quietly handing back a different row's id is how a
        caller ends up updating an action it never meant to touch. Use
        :meth:`list` with ``name=`` if you need to find out which one it is.
        """
        if not name or not isinstance(name, str) or not name.strip():
            raise ValidationError("name must be a non-empty string")
        payload: Dict[str, Any] = {"name": name.strip()}
        if display_name is not None:
            payload["display_name"] = display_name
        if description is not None:
            payload["description"] = description
        return self._request("POST", "/api/actions/", json=payload)

    def list(self, **filters: Any) -> PageIterator:
        """Every action defined for this agent."""
        params = _params.build(filters, _params.ACTION_FILTERS, what="action")
        return PageIterator(
            lambda query: self._request("GET", "/api/actions/", params=query), params
        )

    def get(self, action_id: int) -> Dict[str, Any]:
        """One action definition."""
        return self._request("GET", f"/api/actions/{int(action_id)}/")

    def logs(self, action_id: int) -> List[Any]:
        """Every recorded invocation of this action.

        Returns a plain list — this endpoint is not paginated.
        """
        return self._request("GET", f"/api/actions/{int(action_id)}/logs/")

    def update(self, action_id: int, **fields: Any) -> Dict[str, Any]:
        """Change an action's ``name``, ``display_name`` or ``description``.
        *Write role.*

        The action has to exist — either because your agent performed it, or
        because you declared it with :meth:`create`.

        Renaming raises :class:`~agentsight.exceptions.ValidationError` if this
        agent already has an action under the new name, for the same reason
        :meth:`create` does. Renaming to a name nothing uses is allowed and
        rarely what you want: ``name`` is what spans are matched on, so the next
        span carrying the old one starts a second action beside this. Change
        ``display_name`` instead — that is what it is for.
        """
        unknown = sorted(set(fields) - set(_UPDATABLE))
        if unknown:
            raise ValidationError(
                f"cannot update: {', '.join(unknown)}. "
                f"Updatable fields: {', '.join(_UPDATABLE)}"
            )
        payload = {k: v for k, v in fields.items() if v is not None}
        if not payload:
            raise ValidationError("update() needs at least one field to change")
        return self._request("PATCH", f"/api/actions/{int(action_id)}/", json=payload)
