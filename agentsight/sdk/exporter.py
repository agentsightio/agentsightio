"""Translating finished spans into AgentSight ingest payloads.

The exporter runs on the batch processor's background thread, so nothing here
can reach the user's call stack. It follows the rule from design §10: log and
return ``FAILURE``, never raise.
"""

import json
import time
from collections import OrderedDict
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Sequence

import requests
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult

from agentsight import _settings
from agentsight.sdk.semconv import ConversationAttributes, SpanAttributes

#: Re-exported: this module was where they lived before both planes needed
#: them, and ``sdk.uploads`` still imports them from here.
SDK_NAME = _settings.SDK_NAME
SDK_VERSION = _settings.SDK_VERSION


def _iso(nanoseconds: Optional[int]) -> Optional[str]:
    if not nanoseconds:
        return None
    return datetime.fromtimestamp(nanoseconds / 1e9, tz=timezone.utc).isoformat()


def _duration_ms(span: ReadableSpan) -> Optional[float]:
    if span.start_time and span.end_time:
        return round((span.end_time - span.start_time) / 1e6, 3)
    return None


def span_to_dict(span: ReadableSpan) -> Dict[str, Any]:
    """One span, complete, in the shape ``POST /api/ingest/`` expects.

    Everything the OpenTelemetry span carries is serialized — not just the
    fields the projectors currently read. Resource attributes, instrumentation
    scope, links, the OTel span kind, trace flags and dropped-record counts are
    all preserved so a metric invented later can be computed from history
    rather than from the day it shipped.

    Fields the projectors use are hoisted to the top level; the rest live under
    ``otel`` so the two never collide as either side evolves.
    """
    ctx = span.get_span_context()
    attributes = dict(span.attributes or {})

    events = [
        {
            "name": event.name,
            "timestamp": _iso(event.timestamp),
            "attributes": dict(event.attributes or {}),
        }
        for event in (span.events or [])
    ]

    links = [
        {
            "trace_id": format(link.context.trace_id, "032x"),
            "span_id": format(link.context.span_id, "016x"),
            "attributes": dict(link.attributes or {}),
        }
        for link in (span.links or [])
    ]

    status_code = "unset"
    status_description = None
    if span.status is not None:
        status_code = span.status.status_code.name.lower()
        status_description = span.status.description

    otel: Dict[str, Any] = {
        "span_kind": span.kind.name if span.kind is not None else None,
        "trace_flags": int(ctx.trace_flags),
        "trace_state": str(ctx.trace_state) if ctx.trace_state else None,
        "is_remote": bool(ctx.is_remote),
        "status_description": status_description,
        "links": links,
        "resource": dict(getattr(span.resource, "attributes", {}) or {}),
        "dropped": {
            "attributes": getattr(span, "dropped_attributes", 0),
            "events": getattr(span, "dropped_events", 0),
            "links": getattr(span, "dropped_links", 0),
        },
    }

    scope = getattr(span, "instrumentation_scope", None)
    if scope is not None:
        otel["scope"] = {
            "name": getattr(scope, "name", None),
            "version": getattr(scope, "version", None),
            "schema_url": getattr(scope, "schema_url", None),
        }

    return {
        "span_id": format(ctx.span_id, "016x"),
        "trace_id": format(ctx.trace_id, "032x"),
        "parent_span_id": (
            format(span.parent.span_id, "016x") if span.parent is not None else None
        ),
        "kind": attributes.get(SpanAttributes.KIND, "unknown"),
        "name": span.name,
        "started_at": _iso(span.start_time),
        "ended_at": _iso(span.end_time),
        "duration_ms": _duration_ms(span),
        "status": status_code,
        "attributes": attributes,
        "events": events,
        "otel": otel,
    }


def _as_object(value: Any) -> Any:
    """A serialized metadata attribute back as a dict.

    Anything that will not parse into one is passed through untouched rather
    than dropped: export runs on a background thread with no caller to tell,
    and letting ingest reject a malformed document is more honest than
    silently sending nothing.
    """
    if not isinstance(value, str):
        return value
    try:
        loaded = json.loads(value)
    except ValueError:  # pragma: no cover — to_json guarantees this parses
        return value
    return loaded if isinstance(loaded, dict) else value


def build_payload(spans: Sequence[ReadableSpan]) -> Dict[str, Any]:
    """Group spans into per-conversation blocks.

    Conversation metadata is carried on every span rather than sent once,
    because a conversation outlives any single process — there is no span that
    owns it. Later spans win on conflict, so a scope that supplies richer
    metadata mid-conversation updates the row.

    It is also parsed back into an object on the way out. Span attributes have
    to be primitives, so the metadata attribute is a JSON *string* — but ingest
    stores conversation metadata in a JSON column without parsing it first, and
    a string handed to that column is stored as a JSON string rather than an
    object. Metadata filtering and the metadata-key endpoints then cannot see
    inside it. The wire block is ours to shape, so it is shaped here.
    """
    conversations: "OrderedDict[str, Dict[str, Any]]" = OrderedDict()

    for span in spans:
        attributes = span.attributes or {}
        conversation_id = attributes.get(ConversationAttributes.ID)
        if not conversation_id:
            continue  # every AgentSight span carries one; anything else is not ours

        block = conversations.get(conversation_id)
        if block is None:
            block = {"conversation_id": conversation_id, "spans": []}
            conversations[conversation_id] = block

        for kwarg, attribute in ConversationAttributes.BY_KWARG.items():
            if attribute in attributes:
                block[kwarg] = attributes[attribute]
        if ConversationAttributes.METADATA in attributes:
            block["metadata"] = _as_object(
                attributes[ConversationAttributes.METADATA]
            )

        block["spans"].append(span_to_dict(span))

    for block in conversations.values():
        block["spans"].sort(key=lambda s: s["started_at"] or "")

    return {
        "sdk": {"name": SDK_NAME, "version": SDK_VERSION},
        "conversations": list(conversations.values()),
    }


class AgentSightSpanExporter(SpanExporter):
    """POSTs span batches to ``/api/ingest/`` using the existing API-key plane."""

    _MAX_RETRIES = 3
    _TIMEOUT = 15
    #: Seconds before each retry. Runs on the batch processor's own thread, so
    #: waiting here costs the user nothing — and retrying a struggling backend
    #: three times without pausing is how a brief wobble becomes an outage.
    _BACKOFF = (0.5, 2.0)
    #: Seconds between dropped-batch warnings. A down backend at a 1s flush
    #: interval would otherwise emit one warning per second for as long as
    #: the outage lasts — a log flood that says the same thing every time
    #: (design §10 promises this is rate-limited). Dropped batches between
    #: warnings are counted and reported in the next one, so nothing is lost
    #: from the record, only from the noise.
    _WARN_INTERVAL = 60.0

    def __init__(self, endpoint: str, api_key: str, logger):
        self._url = _settings.join_url(endpoint, "/api/ingest/")
        self._logger = logger
        self._session = requests.Session()
        self._session.headers.update(
            {
                "Authorization": _settings.auth_header(api_key),
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": _settings.USER_AGENT,
            }
        )
        #: Last response body, for tests and the PoC. Not part of the API.
        self.last_response: Optional[Dict[str, Any]] = None
        self._last_drop_warning = 0.0
        self._drops_since_warning = 0

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        try:
            payload = build_payload(spans)
            if not payload["conversations"]:
                return SpanExportResult.SUCCESS
            return self._post(payload)
        except Exception as exc:
            self._logger.error("span export failed: %s", exc)
            return SpanExportResult.FAILURE

    def _post(self, payload: Dict[str, Any]) -> SpanExportResult:
        last_failure = "unknown"
        for attempt in range(self._MAX_RETRIES):
            try:
                response = self._session.post(
                    self._url, json=payload, timeout=self._TIMEOUT
                )
                if response.status_code in (200, 201):
                    self.last_response = response.json() if response.content else {}
                    self._logger.debug(
                        "exported %d conversation(s)", len(payload["conversations"])
                    )
                    return SpanExportResult.SUCCESS

                if 400 <= response.status_code < 500:
                    # Client error: retrying cannot help, and a stuck batch
                    # would block every later batch behind it.
                    #
                    # Note that a bad key shows up here as **403, not 401**:
                    # this route pins itself to ApiKeyAuthentication, which
                    # defines no authenticate_header(), so DRF downgrades the
                    # status. Everywhere else in the API the same failure is a
                    # 401 — which is why agentsight._transport does not try to
                    # special-case it and this loop reports the raw status.
                    self._warn_dropped(
                        "ingest rejected batch (%s): %s"
                        % (response.status_code, response.text[:500])
                    )
                    return SpanExportResult.FAILURE

                self._logger.debug(
                    "ingest error %s (attempt %d/%d)",
                    response.status_code,
                    attempt + 1,
                    self._MAX_RETRIES,
                )
                last_failure = "ingest error %s" % response.status_code
            except requests.RequestException as exc:
                self._logger.debug(
                    "ingest network error (attempt %d/%d): %s",
                    attempt + 1,
                    self._MAX_RETRIES,
                    exc,
                )
                last_failure = "network error: %s" % exc

            if attempt < len(self._BACKOFF):
                time.sleep(self._BACKOFF[attempt])

        self._warn_dropped("batch dropped after %d attempts, last failure: %s"
                           % (self._MAX_RETRIES, last_failure))
        return SpanExportResult.FAILURE

    def _warn_dropped(self, message: str) -> None:
        """One warning per _WARN_INTERVAL, with a count of what it swallowed.

        Per-attempt detail stays available at DEBUG level; this is the
        operator-facing signal, and an operator needs to know the backend is
        unreachable once a minute, not once a second.
        """
        self._drops_since_warning += 1
        now = time.monotonic()
        if now - self._last_drop_warning < self._WARN_INTERVAL:
            return
        suppressed = self._drops_since_warning - 1
        self._last_drop_warning = now
        self._drops_since_warning = 0
        if suppressed:
            self._logger.warning(
                "%s (%d earlier drop(s) suppressed since last warning)",
                message,
                suppressed,
            )
        else:
            self._logger.warning("%s", message)

    def shutdown(self) -> None:
        try:
            self._session.close()
        except Exception:
            pass

    def force_flush(self, timeout_millis: int = 30_000) -> bool:
        return True
