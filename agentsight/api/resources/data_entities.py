"""Managing an agent's data entities — the tenants one agent serves."""

from typing import Any, Dict, Optional

from agentsight.api._pagination import PageIterator
from agentsight.api.resources._base import Resource
from agentsight.exceptions import ValidationError

_MAX_KEY = 255
_MAX_NAME = 255

_UPDATABLE = ("name", "description", "metadata")


def _pk(entity: Any) -> int:
    """A data entity reference as a primary key.

    The key is what your application knows, but these routes address a row by
    its pk, and a string is refused rather than looked up: finding it means
    walking the list, a cost that should be visible where it is paid.
    """
    if isinstance(entity, bool) or not isinstance(entity, int):  # bool is an int
        raise ValidationError(
            f"entity must be the integer pk the API returned, got "
            f"{type(entity).__name__}. A key is not accepted here; read the pk "
            "from the 'id' of a row in data_entities.list()."
        )
    return entity


def _check_key(key: Any) -> str:
    """The key as it will be stored, or an error.

    Refused rather than clamped, unlike the same value on the tracking plane.
    A key is permanent, and this call is the moment someone chooses it, so
    quietly storing a different one is not a kindness.
    """
    if not isinstance(key, str):
        raise ValidationError(f"key must be a string, got {type(key).__name__}")
    trimmed = key.strip()
    if not trimmed:
        raise ValidationError("key must not be empty")
    if len(trimmed) > _MAX_KEY:
        raise ValidationError(f"key must be at most {_MAX_KEY} characters")
    return trimmed


def _check_name(name: Any) -> str:
    if not isinstance(name, str):
        raise ValidationError(f"name must be a string, got {type(name).__name__}")
    if len(name) > _MAX_NAME:
        raise ValidationError(f"name must be at most {_MAX_NAME} characters")
    return name


def _check_description(description: Any) -> str:
    if not isinstance(description, str):
        raise ValidationError(
            f"description must be a string, got {type(description).__name__}"
        )
    return description


class DataEntities(Resource):
    """``ags.data_entities`` — the tenants this agent serves.

    Tracking creates a data entity on first sight of its key, so nothing here
    is needed to start. Opening the conversation with its key is enough::

        with agentsight.conversation("c-1", data_entity="hotel-paris"):
            ...

    This namespace is for what comes after, or before: giving one a readable
    name, declaring one ahead of its traffic, soft-deleting one.

    Conversations are not moved here. A conversation's entity is set once, by
    the first key that reaches it, and re-assigning one is not supported.

    Against a backend that does not support data entities these routes do not
    exist, and every call raises
    :class:`~agentsight.exceptions.NotFoundError`.
    """

    def list(self, *, include_deleted: bool = False) -> PageIterator:
        """The agent's data entities. *Read role.*

        Soft-deleted rows are left out unless ``include_deleted=True``. Each
        row carries ``id``, ``key``, ``name``, ``description``, ``metadata``,
        ``origin``, ``first_seen_at``, ``last_seen_at``, ``is_deleted``,
        ``deleted_at``, ``conversation_count``, ``receiving_traffic``,
        ``embed_token_count``, ``member_count``, ``rule_count`` and
        ``invitation_count``. ``receiving_traffic`` is true on a deleted row
        that conversations are still landing on. The last three are dashboard
        access: team members, email-domain rules and pending invitations
        restricted to the entity.

        Lazy, like every list on this client: nothing is fetched until you
        iterate. An agent holds at most 500 active entities, so walking this is
        cheap.
        """
        params = {"include_deleted": "true"} if include_deleted else {}
        return PageIterator(
            lambda query: self._request("GET", self._path(), params=query), params
        )

    def get(self, entity: int) -> Dict[str, Any]:
        """One data entity by pk, soft-deleted or not. *Read role.*"""
        return self._request("GET", self._path(_pk(entity)))

    def create(
        self,
        key: str,
        *,
        name: Optional[str] = None,
        description: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Declare a data entity ahead of any traffic. *Write role.*

        ``key`` is what tracking sends as ``data_entity`` and what the filters
        take: trimmed, up to 255 characters, matched case-insensitively, and
        permanent. ``name`` defaults to the key and can be changed at any time.

        The backend answers 400, raised as
        :class:`~agentsight.exceptions.ValidationError`, when the key already
        exists in any casing, including on a deleted row (a key stays reserved
        so its history has one row), or when the agent already has 500 active
        entities.
        """
        payload: Dict[str, Any] = {"key": _check_key(key)}
        if name is not None:
            payload["name"] = _check_name(name)
        if description is not None:
            payload["description"] = _check_description(description)
        if metadata is not None:
            if not isinstance(metadata, dict):
                raise ValidationError("metadata must be a dict")
            payload["metadata"] = metadata
        return self._request("POST", self._path(), json=payload)

    def update(self, entity: int, **fields: Any) -> Dict[str, Any]:
        """Change a data entity's label. *Write role.*

        Accepts ``name``, ``description`` and ``metadata``. An empty ``name``
        goes back to the key; ``metadata`` is replaced whole, and ``None``
        clears it. The key cannot change, because it is what your tracking code
        sends and your filters name.
        """
        if "key" in fields:
            raise ValidationError(
                "cannot update key: a data entity's key is permanent. Change "
                "its name instead."
            )
        unknown = sorted(set(fields) - set(_UPDATABLE))
        if unknown:
            raise ValidationError(
                f"cannot update: {', '.join(unknown)}. "
                f"Updatable fields: {', '.join(_UPDATABLE)}"
            )
        if not fields:
            raise ValidationError("update() needs at least one field to change")

        payload: Dict[str, Any] = {}
        if "name" in fields:
            payload["name"] = _check_name(fields["name"])
        if "description" in fields:
            payload["description"] = _check_description(fields["description"])
        if "metadata" in fields:
            metadata = fields["metadata"]
            if metadata is not None and not isinstance(metadata, dict):
                raise ValidationError("metadata must be a dict or None")
            payload["metadata"] = metadata
        return self._request("PATCH", self._path(_pk(entity)), json=payload)

    def delete(self, entity: int) -> Dict[str, Any]:
        """Soft-delete a data entity. *Write role.* Safe to repeat.

        Nothing is lost: its conversations keep it, and its key stays reserved.
        Traffic that still sends the key keeps landing on the hidden row, which
        then reports ``receiving_traffic``. It frees a slot under the cap, and
        hides the entity from the dashboard's filters. Embed tokens pinned to
        it stop working until it is restored.
        """
        return self._request("DELETE", self._path(_pk(entity)))

    def restore(self, entity: int) -> Dict[str, Any]:
        """Undo a soft delete, returning the row. *Write role.*

        Raises :class:`~agentsight.exceptions.ValidationError` when the agent
        already has 500 active entities, because a restored row takes its slot
        back.
        """
        return self._request("POST", self._path(_pk(entity), "restore"))

    # -- internals ---------------------------------------------------------

    def _path(self, entity: Optional[int] = None, action: Optional[str] = None) -> str:
        # A key belongs to exactly one agent, so the pk in this path is the
        # key's own. me() is cached, and calling it here keeps list() lazy.
        path = f"/api/agents/{self._client.me()['agent_id']}/data-entities/"
        if entity is not None:
            path += f"{entity}/"
        if action is not None:
            path += f"{action}/"
        return path
