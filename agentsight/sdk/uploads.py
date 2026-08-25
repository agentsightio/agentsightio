"""Uploading attachment bytes — the data plane, not telemetry.

Spans carry attachment *descriptors* because blobs cannot ride a pipeline that
is sized in spans and allowed to drop batches under backpressure: losing a
metric is acceptable, losing a customer's file is not. The bytes go over the
existing ``/api/attachments/`` route instead, synchronously, on the caller's
thread.

That placement changes the failure contract. Tracking must never raise into
user code; an upload is the opposite — silently dropping a file the caller
believes was delivered is the one unacceptable outcome. So
:func:`upload_attachments` raises: ``ValueError`` for caller mistakes,
:class:`~agentsight.exceptions.UploadError` when the backend refuses or the
network fails.

How the bytes travel (base64 JSON vs multipart) is this module's business,
not the caller's — the parameter for it was deliberately not carried over
from 0.0.x.
"""

import base64
import mimetypes
import os
import threading
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple, Union

import requests

from agentsight._transport import Transport
from agentsight.exceptions import NetworkError, UploadError
from agentsight.sdk import context as ags_context
from agentsight.sdk.api import _attachment_span
from agentsight.sdk.core import api_credentials, default_environment, logger
from agentsight.sdk.semconv import ConversationAttributes, MessageAttributes

_TIMEOUT_SECONDS = 30

#: One pooled transport per credential pair, kept for the life of the process.
#: A fresh Transport per call meant a new session, a new connection pool and a
#: new TLS handshake for every file — on a conversation that uploads several,
#: that is the dominant cost of the call.
_transports: Dict[Tuple[str, str], Transport] = {}
_transports_lock = threading.Lock()


def _shared_transport(api_key: str, endpoint: str) -> Transport:
    key = (api_key, endpoint)
    with _transports_lock:
        transport = _transports.get(key)
        if transport is None:
            transport = Transport(api_key, endpoint, timeout=_TIMEOUT_SECONDS)
            _transports[key] = transport
        return transport


def close_transports() -> None:
    """Release the pooled sessions. Called by ``agentsight.shutdown()``."""
    with _transports_lock:
        pooled = list(_transports.values())
        _transports.clear()
    for transport in pooled:
        try:
            transport.close()
        except Exception:  # pragma: no cover - closing a dead socket
            pass


def upload_attachments(
    files: Any,
    conversation_id: Optional[str] = None,
    sender: str = MessageAttributes.SENDER_USER,
    metadata: Optional[Dict[str, Any]] = None,
    timeout: float = _TIMEOUT_SECONDS,
    message_id: Optional[Union[int, str]] = None,
    *,
    _timestamp: Optional[Union[datetime, str]] = None,
) -> Any:
    """Upload file bytes and attach them to a conversation.

    ``files`` is one attachment or a list of them, where each may be:

    * a filesystem path (``str`` or ``os.PathLike``),
    * an open file object (read as bytes; name taken from ``.name``),
    * a dict ``{"filename": ..., "data": ...}`` where ``data`` is raw bytes,
      a file object, or an already-base64-encoded string — with an optional
      ``"mime_type"`` overriding the guess from the filename.

    ``conversation_id`` defaults to the active ``with agentsight.conversation(...)``
    scope. The conversation row is created server-side if the span pipeline has
    not delivered it yet, so uploading right after opening a scope is safe.

    ``message_id`` attaches the files to an existing message — the ``id`` a
    transcript read (``conversations.get()`` / ``list_full()``) returns —
    instead of the backend creating a message of its own for them. The message
    must belong to ``conversation_id``: the backend answers 404 (raised here as
    ``UploadError(status_code=404)``) when it does not.

    Without ``message_id`` the backend creates a message to hold the files,
    stamped at upload time. Nothing here lets a caller choose that stamp: a
    transcript's order is what the SDK observed, and every other writer —
    ``user_message``, ``agent_message``, every span — is stamped by the
    machine. ``_timestamp`` exists for AgentSight's own integrations, which
    upload out of band and know the instant the files actually arrived; it is
    private, unsupported, and may change without a major version.

    Blocks the calling thread and raises on failure — this is the one
    AgentSight call that is allowed to, because it moves customer data rather
    than telemetry. Returns the backend's response body.
    """
    normalized = _normalize_all(files)

    resolved_id = conversation_id
    environment = None
    scope = ags_context.current_conversation()
    if scope is not None:
        if resolved_id is None:
            resolved_id = scope.conversation_id
        environment = scope.attributes.get(ConversationAttributes.ENVIRONMENT)
    if environment is None:
        environment = default_environment()
    if not resolved_id:
        raise ValueError(
            "upload_attachments() needs a conversation: pass conversation_id= "
            "or call it inside `with agentsight.conversation(...)`."
        )

    api_key, endpoint = api_credentials()
    if not api_key:
        raise UploadError(
            "upload_attachments() needs the HTTP transport: call "
            "agentsight.init(api_key=...) first. (A file exporter or custom "
            "span exporter carries spans only — attachment bytes always go "
            "over HTTP.)"
        )

    # The shared transport: one pooled session, one auth header, one URL
    # joiner. Its raising taxonomy is not used here — this call owes its
    # callers UploadError — so it is driven through ``raw()``.
    #
    # Not closed on the way out: it is pooled per credential pair and every
    # request carries its own timeout, so nothing about it is per-call.
    # ``agentsight.shutdown()`` releases it.
    transport = _shared_transport(api_key, endpoint)
    return _upload(
        transport, normalized, resolved_id, environment, sender, metadata,
        timeout, message_id, _timestamp,
    )


def _isoformat(timestamp: Optional[Union[datetime, str]]) -> str:
    """The payload's ``timestamp`` field: now, unless an internal caller said.

    A naive datetime is read as UTC rather than local time — the backend
    stores UTC, and a host-offset shift here would silently reorder the
    transcript.
    """
    if timestamp is None:
        return datetime.now(timezone.utc).isoformat()
    if isinstance(timestamp, datetime):
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        return timestamp.isoformat()
    return timestamp


def _upload(
    transport: Transport,
    normalized: List[Dict[str, Any]],
    resolved_id: str,
    environment: Optional[str],
    sender: str,
    metadata: Optional[Dict[str, Any]],
    timeout: float,
    message_id: Optional[Union[int, str]] = None,
    timestamp: Optional[Union[datetime, str]] = None,
) -> Any:
    conversation_pk = _ensure_conversation(
        transport, resolved_id, environment, timeout
    )

    payload = {
        "conversation": str(conversation_pk),
        "timestamp": _isoformat(timestamp),
        "mode": "base64",
        "sender": sender,
        "metadata": metadata or {},
        "attachments": [
            {
                "filename": entry["filename"],
                "mime_type": entry["mime_type"],
                "data": entry["data"],
            }
            for entry in normalized
        ],
    }
    # Blank is omitted, not sent: the serializer allows "" and the backend
    # treats it as absent, so sending it would only blur the contract.
    if message_id is not None and str(message_id).strip():
        payload["message"] = str(message_id)

    try:
        response = transport.raw(
            "POST", "/api/attachments/", json=payload, timeout=timeout
        )
    except NetworkError as exc:
        raise UploadError(f"attachment upload failed: {exc}") from exc

    if response.status_code not in (200, 201):
        raise UploadError(
            "attachment upload rejected (%s): %s"
            % (response.status_code, _error_detail(response)),
            status_code=response.status_code,
            response=_response_body(response),
        )

    # The bytes are delivered; now record the fact. Best-effort by design —
    # the span pipeline may be disabled or scopeless, and a missing descriptor
    # span must not turn a successful upload into an error.
    try:
        _attachment_span(
            [
                {
                    "filename": entry["filename"],
                    "mime_type": entry["mime_type"],
                    "size": entry["size"],
                }
                for entry in normalized
            ],
            sender=sender,
            mode="base64",
            metadata=metadata,
        )
    except Exception as exc:  # pragma: no cover
        logger.debug("attachment descriptor span failed: %s", exc)

    return _response_body(response)


def _normalize_all(files: Any) -> List[Dict[str, Any]]:
    if files is None:
        raise ValueError("no files to upload")
    if isinstance(files, (str, bytes, dict)) or hasattr(files, "read") or (
        isinstance(files, os.PathLike)
    ):
        files = [files]
    normalized = [_normalize(file, index) for index, file in enumerate(files)]
    if not normalized:
        raise ValueError("no files to upload")
    return normalized


def _normalize(file: Any, index: int) -> Dict[str, Any]:
    """One attachment → ``{filename, mime_type, data (base64 str), size}``."""
    if isinstance(file, bytes):
        raise ValueError(
            f"attachment {index}: raw bytes carry no filename — pass "
            '{"filename": ..., "data": <bytes>} instead'
        )

    if isinstance(file, dict):
        filename = file.get("filename") or file.get("name")
        if not filename:
            raise ValueError(f"attachment {index}: dict form needs a 'filename'")
        raw = file.get("data", file.get("content"))
        if raw is None:
            raise ValueError(
                f"attachment {index}: dict form needs 'data' "
                "(bytes, a file object, or a base64 string)"
            )
        if hasattr(raw, "read"):
            raw = raw.read()
        if isinstance(raw, str):
            try:
                size = len(base64.b64decode(raw, validate=True))
            except Exception:
                raise ValueError(
                    f"attachment {index}: string 'data' must be valid base64 "
                    "(pass bytes for raw content)"
                )
            encoded = raw
        elif isinstance(raw, (bytes, bytearray)):
            size = len(raw)
            encoded = base64.b64encode(bytes(raw)).decode("ascii")
        else:
            raise ValueError(
                f"attachment {index}: unsupported 'data' type {type(raw).__name__}"
            )
        mime = file.get("mime_type") or file.get("content_type") or _guess_mime(filename)
        return {"filename": filename, "mime_type": mime, "data": encoded, "size": size}

    if isinstance(file, (str, os.PathLike)):
        path = os.fspath(file)
        if not os.path.isfile(path):
            raise ValueError(f"attachment {index}: no such file: {path}")
        with open(path, "rb") as handle:
            raw = handle.read()
        filename = os.path.basename(path)
        return {
            "filename": filename,
            "mime_type": _guess_mime(filename),
            "data": base64.b64encode(raw).decode("ascii"),
            "size": len(raw),
        }

    if hasattr(file, "read"):
        raw = file.read()
        if isinstance(raw, str):
            raw = raw.encode("utf-8")
        name = getattr(file, "name", None)
        filename = os.path.basename(str(name)) if name else f"attachment-{index}"
        return {
            "filename": filename,
            "mime_type": _guess_mime(filename),
            "data": base64.b64encode(raw).decode("ascii"),
            "size": len(raw),
        }

    raise ValueError(
        f"attachment {index}: cannot read {type(file).__name__} — pass a path, "
        "an open file, or a {'filename': ..., 'data': ...} dict"
    )


def _guess_mime(filename: str) -> str:
    return mimetypes.guess_type(filename)[0] or "application/octet-stream"


def _ensure_conversation(
    transport: Transport,
    conversation_id: str,
    environment: Optional[str],
    timeout: float,
) -> Any:
    """Get-or-create the conversation row, returning its primary key.

    The attachments route addresses conversations by pk, but callers hold the
    string ``conversation_id`` — and the row may not exist yet, because spans
    travel on a batched background pipeline while this call is immediate.
    ``POST /api/conversations/`` upserts on (agent, conversation_id), which
    closes both gaps in one round trip.

    Note this is *not* the same operation as ``AgentSight.conversations``'
    id resolution, which fails when the conversation is unknown. Creating on
    demand is load-bearing here and wrong there.
    """
    payload: Dict[str, Any] = {"conversation_id": conversation_id}
    if environment:
        payload["environment"] = environment
    try:
        response = transport.raw(
            "POST", "/api/conversations/", json=payload, timeout=timeout
        )
    except NetworkError as exc:
        raise UploadError(f"could not create conversation: {exc}") from exc

    if response.status_code in (200, 201):
        pk = _response_body(response).get("id")
        if pk is not None:
            return pk

    # The upsert can be refused on grounds an existing row doesn't suffer
    # (e.g. an environment slug the agent doesn't have). The conversation may
    # still exist from the span path — look it up before giving up. This route
    # is write-role-only, which is fine: uploading already requires one.
    try:
        lookup = transport.raw(
            "GET",
            "/api/conversations/lookup/",
            params={"conversation_id": conversation_id},
            timeout=timeout,
        )
    except NetworkError as exc:
        raise UploadError(f"could not look up conversation: {exc}") from exc
    if lookup.status_code == 200:
        pk = _response_body(lookup).get("id")
        if pk is not None:
            return pk

    raise UploadError(
        "could not resolve conversation %r (%s): %s"
        % (conversation_id, response.status_code, _error_detail(response)),
        status_code=response.status_code,
        response=_response_body(response),
    )


def _response_body(response: requests.Response) -> Any:
    try:
        return response.json()
    except Exception:
        return {}


def _error_detail(response: requests.Response) -> str:
    text = response.text or ""
    return text[:500]
