"""Reading button events."""

from typing import Any, List, Optional

from agentsight.api import _params
from agentsight.api._pagination import PageIterator
from agentsight.api.resources._base import Resource


class Buttons(Resource):
    """``ags.buttons`` — what your users clicked.

    Read-only. Button events are recorded by ``agentsight.button()`` on the
    tracking side; this reads them back and aggregates them.
    """

    def list(self, **filters: Any) -> PageIterator:
        """Individual button events."""
        params = _params.build(filters, _params.BUTTON_FILTERS, what="button")
        return PageIterator(
            lambda query: self._request("GET", "/api/buttons/", params=query), params
        )

    def stats(self, event: Optional[str] = None) -> List[Any]:
        """Click totals, most-clicked first.

        Each entry is ``{button_event, value, label, count}``. Pass ``event``
        to narrow to one kind of button. Returns a plain list — this endpoint
        is not paginated.
        """
        params = {"event": event} if event else None
        return self._request("GET", "/api/buttons/stats/", params=params)
