"""The data-plane client: what you hold to read and manage tracked data."""

import logging
import threading
from collections import OrderedDict
from typing import Any, Dict, List, Optional, Union

from agentsight import _settings
from agentsight._transport import Transport
from agentsight.exceptions import (
    InvalidApiKeyError,
    MissingApiKeyError,
    NotFoundError,
    ValidationError,
)

logger = logging.getLogger("agentsight")

#: Business id → primary key. Bounded because a long-lived process walking a
#: large agent would otherwise grow it without limit; 1024 is far more than
#: any realistic working set and costs a few tens of KB.
_MAX_CACHED_IDS = 1024

ConversationRef = Union[int, str]


class AgentSight:
    """Read and manage what the tracking SDK recorded.

    Construct one per API key::

        from agentsight.api import AgentSight

        ags = AgentSight()                      # reads AGENTSIGHT_API_KEY
        staging = AgentSight(api_key="ags_...")  # or as many as you need

    Every method that identifies a conversation accepts either the business
    ``conversation_id`` you passed to ``agentsight.conversation(...)`` or the
    backend's integer primary key. Strings are resolved once and remembered.

    This client only reads and manages. It cannot create conversations,
    messages, buttons, action logs or attachments — those belong to the
    tracking SDK, and having two ways to write the same row would mean two
    sets of semantics for how it projects into the dashboards.

    There is deliberately no ``buttons`` namespace. ``agentsight.button()``
    records clicks to the span archive, but nothing currently projects them
    into a table this client could read, so a ``buttons.list()`` here would
    return an empty page for every caller and look like "no clicks" rather
    than "not surfaced yet". See :func:`agentsight.button`.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        *,
        endpoint: Optional[str] = None,
        timeout: float = Transport.DEFAULT_TIMEOUT,
        max_retries: int = Transport.DEFAULT_MAX_RETRIES,
    ):
        resolved = _settings.resolve_api_key(api_key)
        if not resolved:
            raise MissingApiKeyError()
        if not _settings.is_valid_api_key(resolved):
            raise InvalidApiKeyError(resolved)

        self.endpoint = _settings.resolve_endpoint(endpoint)
        self._transport = Transport(
            resolved, self.endpoint, timeout=timeout, max_retries=max_retries
        )

        self._ids: "OrderedDict[str, int]" = OrderedDict()
        self._ids_lock = threading.Lock()

        # Imported here rather than at module scope: the resources import this
        # module for its type, and doing it at the top would be a cycle.
        from agentsight.api.resources.actions import Actions
        from agentsight.api.resources.conversations import Conversations
        from agentsight.api.resources.feedbacks import Feedbacks
        from agentsight.api.resources.usage import Usage

        self.conversations = Conversations(self)
        self.feedbacks = Feedbacks(self)
        self.actions = Actions(self)
        self.usage = Usage(self)

        self._identity: Optional[Dict[str, Any]] = None
        self._identity_lock = threading.Lock()

    # -- lifecycle ---------------------------------------------------------

    def close(self) -> None:
        """Release the pooled connections."""
        self._transport.close()

    def __enter__(self) -> "AgentSight":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    def __repr__(self) -> str:
        return f"<AgentSight endpoint={self.endpoint!r}>"

    # -- requests ----------------------------------------------------------

    def _request(self, method: str, path: str, **kwargs) -> Any:
        return self._transport.request(method, path, **kwargs)

    # -- identity ----------------------------------------------------------

    def me(self, *, refresh: bool = False) -> Dict[str, Any]:
        """Who this key is: agent, role and the environments it may write to.

        ``{"agent_id": 12, "agent_name": "Support bot", "role": "read",
        "environments": ["production", "development"]}``

        This is the preflight the SDK had no way to perform. It answers three
        questions that previously had only indirect answers: the agent's
        numeric pk (which :meth:`Feedbacks.create_for_agent` needs, and which
        was otherwise discoverable only as a side effect of listing
        conversations), the key's role (previously learned by attempting a
        write and catching the 403), and the environment slugs ingest will
        accept — which the tracking side otherwise assumes.

        Cached, because none of it changes for the life of a key. Pass
        ``refresh=True`` after adding an environment server-side.

        API keys only. A JWT session gets 403 here by design and should use
        the dashboard's own route instead.
        """
        with self._identity_lock:
            if self._identity is None or refresh:
                self._identity = self._request("GET", "/api/me/")
            return self._identity

    def environments(self, *, refresh: bool = False) -> List[str]:
        """The environment slugs this agent has.

        Every agent is seeded with ``production`` and ``development``, and
        until environment CRUD exists that is all any agent has — but asking
        is what lets a slug added server-side reach an SDK that shipped before
        it existed, which hard-coding the pair cannot do.
        """
        environments = self.me(refresh=refresh).get("environments") or []
        return [str(slug) for slug in environments]

    # -- conversation id resolution ---------------------------------------

    def _resolve(self, conversation: ConversationRef) -> int:
        """A conversation reference as a primary key.

        Integers pass straight through. Strings are looked up through the list
        filter rather than ``/api/conversations/lookup/``, for two reasons that
        outlast the original one. (That original reason — ``lookup`` returned
        403 to a read-role key — was a backend bug, and it has since been
        fixed.)

        First, the list filter carries ``include_deleted``, so a soft-deleted
        conversation still resolves and can be inspected or restored; a
        dedicated lookup that omits it would make exactly the conversations
        someone is trying to recover the ones they cannot name. Second, this
        path works against every deployment, including those predating the
        permission fix, and it costs the same single request.
        """
        if isinstance(conversation, bool):  # bool is an int; nobody means this
            raise ValidationError(f"invalid conversation reference: {conversation!r}")
        if isinstance(conversation, int):
            return conversation
        if not isinstance(conversation, str) or not conversation.strip():
            raise ValidationError(
                f"conversation must be an id string or an integer pk, got "
                f"{type(conversation).__name__}"
            )

        conversation_id = conversation.strip()
        cached = self._cached_pk(conversation_id)
        if cached is not None:
            return cached

        body = self._request(
            "GET",
            "/api/conversations/",
            params={
                "conversation_id": conversation_id,
                "full": "false",
                "page_size": 1,
                # So a soft-deleted conversation can still be renamed,
                # inspected or restored rather than looking like it never was.
                "include_deleted": "true",
            },
        )
        results = body.get("results") if isinstance(body, dict) else body
        if not results:
            raise NotFoundError(
                f"no conversation with conversation_id {conversation_id!r}. "
                "Conversations are created by the tracking SDK, not this client.",
                status_code=404,
                detail=f"conversation_id={conversation_id!r} not found",
            )
        if len(results) > 1:
            logger.warning(
                "conversation_id %r matched %s conversations; using the first",
                conversation_id,
                len(results),
            )

        record = results[0]
        pk = record.get("id")
        if pk is None:
            raise NotFoundError(
                f"conversation {conversation_id!r} came back without an id",
                response=record,
            )
        self.remember(record)
        return pk

    def remember(self, record: Any) -> None:
        """Cache the id mapping carried by a conversation payload.

        Every conversation the API returns already names both its ``id`` and
        its ``conversation_id``, so listing conversations and then managing
        some of them costs no lookups at all.
        """
        if not isinstance(record, dict):
            return
        conversation_id = record.get("conversation_id")
        pk = record.get("id")
        if isinstance(conversation_id, str) and isinstance(pk, int):
            with self._ids_lock:
                self._ids[conversation_id] = pk
                self._ids.move_to_end(conversation_id)
                while len(self._ids) > _MAX_CACHED_IDS:
                    self._ids.popitem(last=False)

    def forget(self, conversation: ConversationRef) -> None:
        """Drop a cached mapping — after a delete, the pk may not come back."""
        with self._ids_lock:
            if isinstance(conversation, str):
                self._ids.pop(conversation, None)
                return
            stale = [key for key, pk in self._ids.items() if pk == conversation]
            for key in stale:
                del self._ids[key]

    def _cached_pk(self, conversation_id: str) -> Optional[int]:
        with self._ids_lock:
            pk = self._ids.get(conversation_id)
            if pk is not None:
                self._ids.move_to_end(conversation_id)
            return pk

    def _cache_snapshot(self) -> Dict[str, int]:
        """A copy of the id cache. For tests and debugging."""
        with self._ids_lock:
            return dict(self._ids)
