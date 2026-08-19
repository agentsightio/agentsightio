"""Shared plumbing for the resource namespaces."""

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover
    from agentsight.api._client import AgentSight


class Resource:
    """One group of endpoints, bound to the client that reaches them."""

    def __init__(self, client: "AgentSight"):
        self._client = client

    def _request(self, method: str, path: str, **kwargs) -> Any:
        return self._client._request(method, path, **kwargs)
