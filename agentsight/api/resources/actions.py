"""Action definitions and their logs."""

from typing import Any, Dict, List, Optional

from agentsight.api import _params
from agentsight.api._pagination import PageIterator
from agentsight.api.resources._base import Resource
from agentsight.exceptions import ValidationError

_UPDATABLE = ("name", "description", "display_name")


class Actions(Resource):
    """``ags.actions`` — the tools and steps your agent performs.

    An ``Action`` is a definition, not an event. The tracking SDK creates one
    implicitly the first time it sees a tool by that name, but it can only
    supply the name — ``display_name`` and ``description``, which decide how
    the action reads in the dashboard, can only be set here.

    Individual invocations are action *logs*, written by the tracking SDK.
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

    def create(
        self,
        name: str,
        *,
        display_name: Optional[str] = None,
        description: Optional[str] = None,
        agent: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Define an action. *Write role.*

        ``agent`` is optional and defaults to the one your API key is bound
        to; passing a different one is refused server-side.
        """
        if not name or not isinstance(name, str) or not name.strip():
            raise ValidationError("name must be a non-empty string")
        payload: Dict[str, Any] = {"name": name.strip()}
        if display_name is not None:
            payload["display_name"] = display_name
        if description is not None:
            payload["description"] = description
        if agent is not None:
            payload["agent"] = int(agent)
        return self._request("POST", "/api/actions/", json=payload)

    def update(self, action_id: int, **fields: Any) -> Dict[str, Any]:
        """Change an action's ``name``, ``display_name`` or ``description``.
        *Write role.*"""
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

    def delete(self, action_id: int) -> Dict[str, Any]:
        """Remove an action definition. *Write role.*"""
        return self._request("DELETE", f"/api/actions/{int(action_id)}/")
