"""Merging conversation metadata, client-side.

The backend replaces the whole document on every one of its write paths, so
"add a key without losing the others" has to be assembled here before it is
sent. Both planes need the same rule — the tracking SDK merges against the
scope it already holds, the API client merges against what it fetched — and
neither package should import the other, so the rule lives at the top level
next to ``_settings`` and ``_transport``.

The one invariant worth stating out loud: **no value is ever filtered.**
``None``, ``False``, ``0`` and ``""`` are all things a caller may legitimately
want stored, and the ``if value:`` / ``if value is not None:`` guards used
elsewhere in this package would silently eat every one of them. Removing a key
is said explicitly, with ``remove``, and that is the only way to remove one.
"""

import json
from typing import Any, Dict, Iterable, Optional

from agentsight.exceptions import ValidationError


def check(
    metadata: Optional[Dict[str, Any]],
    remove: Optional[Iterable[str]],
) -> None:
    """Validate the caller's arguments, or raise :class:`ValidationError`."""
    if metadata is not None and not isinstance(metadata, dict):
        raise ValidationError(
            f"metadata must be a dict, got {type(metadata).__name__}"
        )
    if metadata is not None:
        for key in metadata:
            if not isinstance(key, str):
                raise ValidationError(
                    f"metadata keys must be strings, got {type(key).__name__}"
                )

    if remove is not None:
        # A bare string is iterable, so `remove="tier"` would silently mean
        # "remove the keys 't', 'i', 'e' and 'r'" — the kind of mistake that
        # is invisible until someone notices data missing.
        if isinstance(remove, str):
            raise ValidationError(
                "remove must be a list of keys, not a single string — "
                f"did you mean remove=[{remove!r}]?"
            )
        try:
            keys = list(remove)
        except TypeError:
            raise ValidationError(
                f"remove must be an iterable of keys, got {type(remove).__name__}"
            )
        for key in keys:
            if not isinstance(key, str):
                raise ValidationError(
                    f"remove keys must be strings, got {type(key).__name__}"
                )

    if not metadata and not remove:
        raise ValidationError(
            "update_metadata() needs something to do — pass metadata to set, "
            "keys to remove, or both"
        )


def merge(
    current: Optional[Dict[str, Any]],
    update: Optional[Dict[str, Any]] = None,
    remove: Optional[Iterable[str]] = None,
) -> Dict[str, Any]:
    """``current`` with ``update`` applied and ``remove`` dropped.

    Shallow, by design: a nested dict is replaced whole rather than merged
    key-by-key, which is what keeps "replace this whole sub-object" sayable at
    all. Deep merging would make that impossible to express.

    Returns a new dict — ``current`` is never mutated, because on the tracking
    plane it is the live scope's document and on the API-client plane it is a
    slice of the response the caller may still be holding.
    """
    merged: Dict[str, Any] = dict(current or {})
    if update:
        merged.update(update)
    for key in remove or ():
        # Removing an absent key is a no-op rather than an error, so a caller
        # clearing optional keys does not have to know which are present.
        merged.pop(key, None)
    return merged


def coerce(value: Any, *, source: str = "metadata") -> Dict[str, Any]:
    """A stored metadata value as a dict, ready to merge into.

    Tolerates a JSON string as well as a dict. Rows written by older SDK
    builds hold the document as a JSON string rather than an object, and a
    merge that treated one of those as "no metadata" would wipe every key it
    was supposed to preserve — so this raises rather than guessing.
    """
    if value is None:
        return {}
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str):
        if not value.strip():
            return {}
        try:
            loaded = json.loads(value)
        except ValueError:
            raise ValidationError(
                f"{source} is a string that is not valid JSON, so it cannot be "
                "merged into without losing it"
            )
        if not isinstance(loaded, dict):
            raise ValidationError(
                f"{source} is JSON {type(loaded).__name__}, not an object, so "
                "it cannot be merged into without losing it"
            )
        return loaded
    raise ValidationError(
        f"{source} is {type(value).__name__}, not a dict, so it cannot be "
        "merged into without losing it"
    )
