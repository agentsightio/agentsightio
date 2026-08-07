"""Uploading attachment bytes — the data plane, not telemetry.

Spans carry attachment *descriptors* because blobs cannot ride a pipeline that
is sized in spans and allowed to drop batches under backpressure: losing a
metric is acceptable, losing a customer's file is not. The bytes go over the
existing ``/api/attachments/`` route instead, synchronously, on the caller's
thread.

That placement changes the failure contract. Tracking must never raise into
user code (design §10); an upload is the opposite — silently dropping a file
the caller believes was delivered is the one unacceptable outcome. So
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
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import requests

from agentsight.exceptions import UploadError
from agentsight.sdk import context as ags_context
from agentsight.sdk.api import attachments as _record_attachment_span
from agentsight.sdk.core import api_credentials, default_environment, logger
from agentsight.sdk.exporter import SDK_NAME, SDK_VERSION
from agentsight.sdk.semconv import ConversationAttributes, MessageAttributes

_TIMEOUT_SECONDS = 30


def upload_attachments(
    files: Any,
    conversation_id: Optional[str] = None,
    sender: str = MessageAttributes.SENDER_USER,
    metadata: Optional[Dict[str, Any]] = None,
    timeout: float = _TIMEOUT_SECONDS,
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

    headers = {
        "Authorization": f"Api-Key {api_key}",
        "User-Agent": f"{SDK_NAME}/{SDK_VERSION}",
    }
    base = endpoint.rstrip("/")

    conversation_pk = _ensure_conversation(
        base, headers, resolved_id, environment, timeout
    )

    payload = {
        "conversation": str(conversation_pk),
        "timestamp": datetime.now(timezone.utc).isoformat(),
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

    url = f"{base}/api/attachments/"
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=timeout)
    except requests.RequestException as exc:
        raise UploadError(f"attachment upload to {url} failed: {exc}") from exc

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
        _record_attachment_span(
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
    base: str,
    headers: Dict[str, str],
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
    """
    url = f"{base}/api/conversations/"
    payload: Dict[str, Any] = {"conversation_id": conversation_id}
    if environment:
        payload["environment"] = environment
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=timeout)
    except requests.RequestException as exc:
        raise UploadError(f"could not reach {url}: {exc}") from exc

    if response.status_code in (200, 201):
        pk = _response_body(response).get("id")
        if pk is not None:
            return pk

    # The upsert can be refused on grounds an existing row doesn't suffer
    # (e.g. an environment slug the agent doesn't have). The conversation may
    # still exist from the span path — look it up before giving up.
    lookup_url = f"{base}/api/conversations/lookup/"
    try:
        lookup = requests.get(
            lookup_url,
            params={"conversation_id": conversation_id},
            headers=headers,
            timeout=timeout,
        )
    except requests.RequestException as exc:
        raise UploadError(f"could not reach {lookup_url}: {exc}") from exc
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
