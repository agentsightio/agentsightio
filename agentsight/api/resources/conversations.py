"""Reading and managing conversations."""

import logging
from typing import Any, Dict, Iterable, List, Optional

from agentsight import _metadata
from agentsight.api import _params
from agentsight.api._client import ConversationRef
from agentsight.api._pagination import PageIterator
from agentsight.api.resources._base import Resource
from agentsight.exceptions import ValidationError

logger = logging.getLogger("agentsight")

_MAX_NAME = 255

#: Fields ``PATCH /api/conversations/{pk}/update/`` accepts. ``conversation_id``,
#: ``started_at``, ``agent`` and ``deleted_at`` are immutable server-side.
_UPDATABLE = ("name", "is_marked", "customer_id", "device", "language", "metadata")


class Conversations(Resource):
    """``ags.conversations`` — everything you can do to a tracked conversation.

    Methods marked *write role* need an API key with the ``write`` role; a
    read-only key gets :class:`~agentsight.exceptions.PermissionDeniedError`.
    There is no endpoint that reports a key's own role, so that is how you
    find out.
    """

    # -- reading -----------------------------------------------------------

    def list(self, **filters: Any) -> PageIterator:
        """Conversations matching ``filters``, without their transcripts.

        Note this differs from the raw API: the backend defaults an API key to
        ``?full=true``, meaning every row arrives carrying its whole
        transcript, messages, attachments, action logs and feedbacks. That is
        rarely what you want from a list and can be hundreds of megabytes over
        a busy agent, so this sends ``?full=false``. Use :meth:`list_full` when
        you do want the transcripts.

        Returns a lazy iterator — nothing is fetched until you iterate::

            for conversation in ags.conversations.list(is_marked=True):
                print(conversation["conversation_id"], conversation["name"])

        Call ``.page()`` on the result instead to read ``count`` without
        walking everything.

        Filters mirror the backend's: ``action_name``, ``conversation_id``,
        ``customer_id``, ``customer_id__icontains``, ``customer_ip_address``,
        ``device``, ``environment`` (or ``env``), ``feedback_sentiment``,
        ``has_feedback``, ``has_messages``, ``include_deleted``, ``is_marked``,
        ``language``, ``message_contains``, ``metadata``, ``metadata_key``,
        ``metadata_value``, ``name``, ``ordering``, ``search``,
        ``started_at_after``, ``started_at_before``. Datetimes and booleans are
        converted for you.

        Soft-deleted conversations are excluded unless you pass
        ``include_deleted=True``.
        """
        return self._list(filters, full=False)

    def list_full(self, **filters: Any) -> PageIterator:
        """As :meth:`list`, but each row carries its full transcript.

        The only way to read messages in bulk — there is no message list
        endpoint on this API.
        """
        return self._list(filters, full=True)

    def get(self, conversation: ConversationRef, *, full: bool = True) -> Dict[str, Any]:
        """One conversation, with its messages, attachments and action logs.

        Pass ``full=False`` for the metadata alone.
        """
        pk = self._client._resolve(conversation)
        record = self._request(
            "GET",
            f"/api/conversations/{pk}/",
            params={"full": "true" if full else "false"},
        )
        self._client.remember(record)
        return record

    def attachments(self, conversation: ConversationRef) -> Dict[str, Any]:
        """Every attachment on a conversation, with signed download URLs.

        The ``file_url`` values are signed and **expire after one hour**, so
        fetch them when you need them rather than storing them.
        """
        pk = self._client._resolve(conversation)
        return self._request("GET", f"/api/conversations/{pk}/attachments/")

    def metadata_keys(self) -> List[Any]:
        """Every conversation-metadata key this agent has ever recorded."""
        return self._request("GET", "/api/conversations/metadata-keys/")

    def metadata_values(self, key: str) -> List[Any]:
        """Every value recorded for one conversation-metadata key."""
        if not key:
            raise ValidationError("metadata_values() needs a key")
        return self._request(
            "GET", "/api/conversations/metadata-values/", params={"key": key}
        )

    def message_metadata_keys(self) -> List[Any]:
        """Every message-metadata key this agent has ever recorded."""
        return self._request("GET", "/api/conversations/message-metadata-keys/")

    def resolve(self, conversation: ConversationRef) -> int:
        """The integer primary key for a business ``conversation_id``.

        Every other method does this for you; it is public so the round trip
        is inspectable rather than magic, and so you can prime the cache.
        """
        return self._client._resolve(conversation)

    # -- managing ----------------------------------------------------------

    def rename(self, conversation: ConversationRef, name: str) -> Dict[str, Any]:
        """Set a conversation's display name. *Write role.*"""
        pk = self._client._resolve(conversation)
        return self._request(
            "PATCH",
            f"/api/conversations/{pk}/rename/",
            json={"name": _check_name(name)},
        )

    def mark(self, conversation: ConversationRef, is_marked: bool = True) -> Dict[str, Any]:
        """Flag or unflag a conversation. *Write role.*"""
        pk = self._client._resolve(conversation)
        return self._request(
            "POST",
            f"/api/conversations/{pk}/mark/",
            json={"is_marked": bool(is_marked)},
        )

    def update(self, conversation: ConversationRef, **fields: Any) -> Dict[str, Any]:
        """Change several fields at once. *Write role.*

        Accepts ``name``, ``is_marked``, ``customer_id``, ``device``,
        ``language`` and ``metadata``. The identity fields — ``conversation_id``,
        ``started_at``, ``agent`` — are immutable server-side.
        """
        unknown = sorted(set(fields) - set(_UPDATABLE))
        if unknown:
            raise ValidationError(
                f"cannot update: {', '.join(unknown)}. "
                f"Updatable fields: {', '.join(_UPDATABLE)}"
            )

        payload: Dict[str, Any] = {}
        for key, value in fields.items():
            if value is None:
                continue
            if key == "name":
                payload["name"] = _check_name(value)
            elif key == "is_marked":
                payload["is_marked"] = bool(value)
            elif key == "metadata":
                if not isinstance(value, dict):
                    raise ValidationError("metadata must be a dict")
                payload["metadata"] = value
            else:
                payload[key] = str(value)

        if not payload:
            raise ValidationError("update() needs at least one field to change")

        pk = self._client._resolve(conversation)
        return self._request("PATCH", f"/api/conversations/{pk}/update/", json=payload)

    def update_metadata(
        self,
        conversation: ConversationRef,
        metadata: Optional[Dict[str, Any]] = None,
        *,
        remove: Optional[Iterable[str]] = None,
    ) -> Dict[str, Any]:
        """Change some metadata keys, keeping the rest. *Write role.*

        :meth:`update` replaces the whole document, because that is all the
        endpoint can do. This reads what is stored, merges, and writes the
        result back::

            ags.conversations.update_metadata("wa-3859", {"plan": "enterprise"})
            ags.conversations.update_metadata("wa-3859", remove=["trial_ends"])

        Merging is shallow — a nested dict is replaced whole — and **no value is
        filtered**: ``None``, ``False``, ``0`` and ``""`` are stored as given.
        ``remove`` is the only thing that deletes a key, and naming a key that
        is not there is a no-op.

        Two round trips, and not atomic: the backend offers no conditional
        write, so two callers merging into the same conversation at the same
        moment can lose one of the two updates. Prefer
        :func:`agentsight.update_metadata` while the conversation is still open
        in this process — it needs no fetch and cannot race.

        Blocking, like the rest of this client. It does not need to be async to
        stay off an event loop:

        * FastAPI / Starlette —
          ``background_tasks.add_task(ags.conversations.update_metadata, ...)``.
          ``add_task`` hands a sync callable to ``run_in_threadpool``.
        * anywhere else —
          ``await asyncio.to_thread(ags.conversations.update_metadata, ...)``.
        """
        _metadata.check(metadata, remove)

        record = self.get(conversation, full=False)
        if not isinstance(record, dict) or "metadata" not in record:
            # Merging into {} here would write an empty document over whatever
            # is stored. The field is visibility-flagged server-side and the
            # flag fails open for API keys, so this should not happen — but
            # "should not" is not worth a silent data loss.
            raise ValidationError(
                "the server did not return this conversation's metadata, so "
                "there is nothing safe to merge into. Use update(metadata=...) "
                "to replace it outright."
            )

        merged = _metadata.merge(
            _metadata.coerce(record["metadata"], source="stored metadata"),
            metadata,
            remove,
        )
        response = self.update(conversation, metadata=merged)
        _sync_live_scope(record.get("conversation_id"), merged)
        return response

    def delete(self, conversation: ConversationRef) -> Dict[str, Any]:
        """Soft-delete a conversation. *Write role.*

        The row survives with ``is_deleted=True`` and is hidden from listings
        unless you pass ``include_deleted=True``. Use :meth:`purge` to destroy
        it outright.
        """
        pk = self._client._resolve(conversation)
        response = self._request("DELETE", f"/api/conversations/{pk}/delete/")
        self._client.forget(conversation)
        return response

    def purge(self, conversation: ConversationRef) -> Dict[str, Any]:
        """Permanently delete a conversation and everything on it. *Write role.*

        Unrecoverable — the row, its messages, its attachments and its spans
        are gone. :meth:`delete` is the reversible one.
        """
        pk = self._client._resolve(conversation)
        response = self._request("DELETE", f"/api/conversations/{pk}/")
        self._client.forget(conversation)
        self._client.forget(pk)
        return response

    # -- internals ---------------------------------------------------------

    def _list(self, filters: Dict[str, Any], *, full: bool) -> PageIterator:
        _params.check_sentiment(filters.get("feedback_sentiment"))
        params = _params.build(
            filters, _params.CONVERSATION_FILTERS, what="conversation"
        )
        params["full"] = "true" if full else "false"

        def fetch(query: Dict[str, Any]) -> Any:
            body = self._request("GET", "/api/conversations/", params=query)
            # Every row names both its id and its conversation_id, so listing
            # then managing costs no extra lookups.
            records = body.get("results") if isinstance(body, dict) else body
            for record in records or []:
                self._client.remember(record)
            return body

        return PageIterator(fetch, params)


def _sync_live_scope(conversation_id: Any, merged: Dict[str, Any]) -> None:
    """Carry a written document into the tracking scope, if it is this one.

    Conversation metadata rides on every span, and ingest takes the newest
    document it has seen — so a conversation still open in this process would
    overwrite what was just written the moment it emitted its next span. The
    caller would see a successful PATCH and, seconds later, the old metadata.

    Best-effort and deliberately quiet: this client is usable on its own, in a
    process where the tracking SDK was never imported or never initialised.
    """
    if not isinstance(conversation_id, str):
        return
    try:
        from agentsight.sdk import context as ags_context

        scope = ags_context.current_conversation()
        if scope is not None and scope.conversation_id == conversation_id:
            scope.set_metadata(merged)
    except Exception as exc:  # pragma: no cover
        logger.debug("could not sync metadata into the live scope: %s", exc)


def _check_name(name: Any) -> str:
    if not isinstance(name, str) or not name.strip():
        raise ValidationError("name must be a non-empty string")
    if len(name) > _MAX_NAME:
        raise ValidationError(
            f"name cannot exceed {_MAX_NAME} characters (got {len(name)})"
        )
    return name.strip()
