"""Action definitions and their logs."""

from typing import Any, Dict, List

from agentsight.api import _params
from agentsight.api._pagination import PageIterator
from agentsight.api.resources._base import Resource
from agentsight.exceptions import ValidationError

_UPDATABLE = ("name", "description", "display_name")


class Actions(Resource):
    """``ags.actions`` — the tools and steps your agent performs.

    An ``Action`` is a definition, not an event, and **the tracking SDK is the
    only thing that creates one**: ingest upserts it by name the first time a
    ``@tool`` or ``@task`` span carries it. There is deliberately no
    ``create()`` here, and no ``delete()`` — an action exists because your
    agent performed it, and a second way to conjure or destroy that row would
    mean two sets of semantics for how the same table reaches the dashboards.

    What this namespace is for is the half tracking cannot supply.
    ``display_name`` and ``description`` decide how an action reads in the
    dashboard, and a span carries neither — so :meth:`update` is how they get
    set, once the action has been seen at least once.

    Individual invocations are action *logs*, also written by the tracking SDK.
    :meth:`logs` reads them back.
    """

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

        The action has to exist, which means your agent has to have performed
        it at least once — see the class docstring for why that is the only
        way one comes into being.
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
