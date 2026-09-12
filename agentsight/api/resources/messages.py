"""Reading one message and editing what your application attached to it."""

from typing import Any, Dict, Iterable, Optional

from agentsight import _metadata
from agentsight.api.resources._base import Resource
from agentsight.exceptions import ValidationError


def _pk(message: Any) -> int:
    """A message reference as a primary key.

    Messages have no business id of their own — the tracking SDK never asked
    you to name one — so the only way to point at a message is the integer
    pk the API hands back (``conversation["messages"][n]["id"]``, or the
    ``id`` a feedback row names). A string is refused rather than looked up,
    because there is nothing to look it up by.
    """
    if isinstance(message, bool) or not isinstance(message, int):  # bool is an int
        raise ValidationError(
            f"message must be the integer pk the API returned, got "
            f"{type(message).__name__}. Messages have no business id; read the "
            "pk from conversation['messages'][n]['id']."
        )
    return message


class Messages(Resource):
    """``ags.messages`` — one message at a time, by pk.

    A message's content, sender and timestamp are what tracking observed and
    they stay that way; this namespace does not create messages and does not
    edit the transcript. What it edits is **metadata**: the document your
    application attached to a message when it was recorded, which is also the
    document the dashboard's message templates render. Something your
    application learns about a message *after* the turn — a picture generated
    for it in the background, a verdict, a score — belongs there, next to the
    message it is about, and this is the way to put it there.

    There is no ``list()``: the API returns messages nested in their
    conversation (``ags.conversations.get(...)["messages"]``), and a message
    list of its own does not exist server-side.
    """

    def get(self, message: int) -> Dict[str, Any]:
        """One message — content, sender, timestamp, metadata, attachments
        with signed URLs, action logs and its vote. *Read role.*"""
        return self._request("GET", f"/api/track/{_pk(message)}/")

    def update(self, message: int, *, metadata: Dict[str, Any]) -> Dict[str, Any]:
        """Replace a message's metadata document. *Write role.*

        Metadata is the only field this exposes. The endpoint would accept
        more, but content, sender and timestamp are the transcript, and a
        client that could rewrite the transcript would have two sets of
        semantics for what a message is.

        This **replaces the whole document** — keys you do not send are gone.
        Prefer :meth:`update_metadata`, which keeps them.
        """
        if not isinstance(metadata, dict):
            raise ValidationError("metadata must be a dict")
        return self._request(
            "PATCH", f"/api/track/{_pk(message)}/", json={"metadata": metadata}
        )

    def update_metadata(
        self,
        message: int,
        metadata: Optional[Dict[str, Any]] = None,
        *,
        remove: Optional[Iterable[str]] = None,
    ) -> Dict[str, Any]:
        """Change some metadata keys on a message, keeping the rest. *Write role.*

        :meth:`update` replaces the whole document, because that is all the
        endpoint can do. This reads what is stored, merges, and writes the
        result back::

            ags.messages.update_metadata(4821, {"visualization": record})
            ags.messages.update_metadata(4821, remove=["draft"])

        Merging is shallow — a nested dict is replaced whole — and **no value
        is filtered**: ``None``, ``False``, ``0`` and ``""`` are stored as
        given. ``remove`` is the only thing that deletes a key, and naming a
        key that is not there is a no-op.

        Two round trips, and not atomic: the backend offers no conditional
        write, so two callers merging into the same message at the same moment
        can lose one of the two updates. A message is normally written once,
        by the turn that recorded it, and enriched afterwards by one job, so
        this matters less than it does for conversations — but it is still
        true.

        Blocking, like the rest of this client. Off an event loop:
        ``await asyncio.to_thread(ags.messages.update_metadata, pk, data)``.
        """
        _metadata.check(metadata, remove)

        pk = _pk(message)
        record = self.get(pk)
        if not isinstance(record, dict) or "metadata" not in record:
            # Merging into {} here would write an empty document over whatever
            # is stored. The field is visibility-flagged server-side and the
            # flag fails open for API keys, so this should not happen — but
            # "should not" is not worth a silent data loss.
            raise ValidationError(
                "the server did not return this message's metadata, so there "
                "is nothing safe to merge into. Use update(metadata=...) to "
                "replace it outright."
            )

        merged = _metadata.merge(
            _metadata.coerce(record["metadata"], source="stored metadata"),
            metadata,
            remove,
        )
        return self.update(pk, metadata=merged)
