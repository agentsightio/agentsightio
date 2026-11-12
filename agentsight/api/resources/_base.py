"""Shared plumbing for the resource namespaces."""

from typing import TYPE_CHECKING, Any

from agentsight.api._client import _refuse_unencodable

if TYPE_CHECKING:  # pragma: no cover
    from agentsight.api._client import AgentSight


_ENTITY_FILTERS = ("data_entity", "data_entity_unassigned")


class Resource:
    """One group of endpoints, bound to the client that reaches them."""

    def __init__(self, client: "AgentSight"):
        self._client = client

    def _request(self, method: str, path: str, **kwargs) -> Any:
        params = kwargs.get("params")
        if params and any(name in params for name in _ENTITY_FILTERS):
            # A value that cannot be sent is refused first: the question below
            # is itself a request, and that refusal says nothing was sent.
            _refuse_unencodable(path, kwargs)
            # A backend that predates data entities ignores these and answers
            # with every row, so it is asked before the request is sent. Here,
            # because every list, page, count and rollup ends in this method,
            # and only once something is actually being fetched.
            self._client._require_data_entities()
        return self._client._request(method, path, **kwargs)
