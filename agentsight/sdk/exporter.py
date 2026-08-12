"""Translating finished spans into AgentSight ingest payloads.

The exporter runs on the batch processor's background thread, so nothing here
can reach the user's call stack. It follows the rule from design §10: log and
return ``FAILURE``, never raise.
"""

import gzip
import json
import time
from collections import OrderedDict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence

import requests
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult

from agentsight import _settings
from agentsight._transport import retry_after
from agentsight.sdk.semconv import (
    ConversationAttributes,
    SpanAttributes,
    string_attribute,
)

#: Re-exported: this module was where they lived before both planes needed
#: them, and ``sdk.uploads`` still imports them from here.
SDK_NAME = _settings.SDK_NAME
SDK_VERSION = _settings.SDK_VERSION

#: How many failing blocks a rejection warning names before it stops listing
#: them and just counts. Ingest itself lists at most 20; a log line is read by
#: a human, and five is enough to see the pattern.
_MAX_REPORTED_BLOCKS = 5


def _iso(nanoseconds: Optional[int]) -> Optional[str]:
    if not nanoseconds:
        return None
    return datetime.fromtimestamp(nanoseconds / 1e9, tz=timezone.utc).isoformat()


def _duration_ms(span: ReadableSpan) -> Optional[float]:
    if span.start_time and span.end_time:
        return round((span.end_time - span.start_time) / 1e6, 3)
    return None


def span_to_dict(
    span: ReadableSpan, resource: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """One span, complete, in the shape ``POST /api/ingest/`` expects.

    Everything the OpenTelemetry span carries is serialized — not just the
    fields the projectors currently read. Resource attributes, instrumentation
    scope, links, the OTel span kind, trace flags and dropped-record counts are
    all preserved so a metric invented later can be computed from history
    rather than from the day it shipped.

    Fields the projectors use are hoisted to the top level; the rest live under
    ``otel`` so the two never collide as either side evolves.

    ``resource`` is the span's resource attributes, already as a dict. The
    resource is process-wide and immutable, so ``build_payload`` builds the
    dict once per export call and passes it in rather than paying the copy per
    span; spans sharing a resource then share one dict object, which is safe
    because the payload is serialized to JSON and never mutated. Left unset,
    the dict is built here — same output, one copy per call.
    """
    ctx = span.get_span_context()
    # ReadableSpan types the context as Optional because one can be built
    # bare; every span the tracer hands the exporter carries one.
    assert ctx is not None
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
        "resource": (
            dict(getattr(span.resource, "attributes", {}) or {})
            if resource is None
            else resource
        ),
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
    #: conversation_id -> the raw metadata value last parsed for that block.
    #: Every span in a conversation carries the same serialized document, so
    #: without this the same string is parsed once per span. A local dict, not
    #: a key on ``block``: the block is serialized straight to JSON and ingest
    #: rejects fields it does not know.
    last_raw: Dict[str, Any] = {}
    #: id(resource) -> its attributes as a dict, built once per export call.
    #: In practice one process has one resource, so this is one entry. Keyed
    #: by identity, which is safe here because the spans in hand keep their
    #: resources alive for the duration of the call.
    resources: Dict[int, Dict[str, Any]] = {}

    for span in spans:
        attributes = span.attributes or {}
        conversation_id = string_attribute(attributes, ConversationAttributes.ID)
        if not conversation_id:
            continue  # every AgentSight span carries one; anything else is not ours

        block = conversations.get(conversation_id)
        if block is None:
            block = {"conversation_id": conversation_id, "spans": []}
            conversations[conversation_id] = block

        for kwarg, attribute in ConversationAttributes.BY_KWARG.items():
            if attribute in attributes:
                block[kwarg] = attributes[attribute]
        # Compared by raw value, not truthiness: `{}` is a real instruction
        # ("clear it") and must still travel, while a *changed* document —
        # richer metadata supplied mid-conversation — must still re-parse and
        # overwrite so later spans win. Attribute values are never None, so
        # None from .get() can only mean the attribute is absent.
        raw = attributes.get(ConversationAttributes.METADATA)
        if raw is not None and last_raw.get(conversation_id) != raw:
            block["metadata"] = _as_object(raw)
            last_raw[conversation_id] = raw

        resource_key = id(span.resource)
        resource = resources.get(resource_key)
        if resource is None:
            resource = dict(getattr(span.resource, "attributes", {}) or {})
            resources[resource_key] = resource

        block["spans"].append(span_to_dict(span, resource))

    for block in conversations.values():
        block["spans"].sort(key=lambda s: s["started_at"] or "")

    return {
        "sdk": {"name": SDK_NAME, "version": SDK_VERSION},
        "conversations": list(conversations.values()),
    }


def _rejection_detail(response: requests.Response) -> str:
    """What a 400 from ingest actually says, block by block where it can.

    Ingest names the offending conversation blocks rather than just failing:
    ``detail`` plus a ``conversations`` list of ``{index, conversation_id,
    errors}``. Surfacing those ids is the difference between an operator
    knowing which conversation to look at and knowing only that something in
    the last flush was wrong.

    Errors that are *not* per-block — a missing ``conversations`` key, a
    top-level type error — carry neither key, because there is no block to
    point at. Those fall back to the raw text, which is all there is.
    """
    try:
        body = response.json()
    except ValueError:
        body = None

    if not isinstance(body, dict):
        return (response.text or "")[:500]

    blocks = body.get("conversations")
    if not isinstance(blocks, list) or not blocks:
        return (response.text or "")[:500]

    named: List[str] = []
    for block in blocks[:_MAX_REPORTED_BLOCKS]:
        if not isinstance(block, dict):
            continue
        # conversation_id is read back from the raw request server-side, so it
        # survives even when conversation_id is itself the invalid field.
        who = block.get("conversation_id") or f"index {block.get('index')}"
        named.append(f"{who} ({_errors_summary(block.get('errors'))})")

    if not named:
        return (response.text or "")[:500]

    detail = body.get("detail") or "ingest rejected the batch"
    suffix = ""
    hidden = len(blocks) - len(named)
    if hidden > 0:
        suffix = f", and {hidden} more"
    if body.get("truncated"):
        suffix += " (server truncated the list)"
    return f"{detail} Offending block(s): {'; '.join(named)}{suffix}"


def _errors_summary(errors: Any) -> str:
    """One block's field errors, flattened to a line."""
    if isinstance(errors, dict):
        parts = []
        for field, messages in errors.items():
            if isinstance(messages, (list, tuple)):
                joined = ", ".join(str(message) for message in messages)
            else:
                joined = str(messages)
            parts.append(f"{field}: {joined}")
        if parts:
            return "; ".join(parts)
    elif errors:
        return str(errors)
    return "no field detail"


class AgentSightSpanExporter(SpanExporter):
    """POSTs span batches to ``/api/ingest/`` using the existing API-key plane."""

    _MAX_RETRIES = 3
    _TIMEOUT = 15
    #: Seconds before each retry. Runs on the batch processor's own thread, so
    #: waiting here costs the user nothing — and retrying a struggling backend
    #: three times without pausing is how a brief wobble becomes an outage.
    _BACKOFF = (0.5, 2.0)
    #: Ceiling on a server-supplied ``Retry-After``. The header is honoured
    #: because the backend knows its own budget better than a fixed curve does,
    #: but it arrives on the batch processor's only export thread: an
    #: unbounded value would park every later batch behind it and let one
    #: header stall the whole pipeline. Past this we wait the cap, retry, and
    #: let the batch drop normally if it is still throttled.
    _MAX_RETRY_AFTER = 30.0
    #: How full the export queue may get before waiting out a throttle stops
    #: being worth it. Blocking the one export thread saves the batch in hand
    #: — at most ``max_export_batch_size`` spans — and costs everything the
    #: queue drops meanwhile, which is unbounded in time and silent: the
    #: overflow warning comes from OpenTelemetry's logger, not ours, so an
    #: application that configured only the ``agentsight`` logger never hears
    #: it. Below this line the queue has room and waiting is free; above it,
    #: the trade has inverted and dropping one batch now is the cheaper loss.
    _QUEUE_PRESSURE_LIMIT = 0.5
    #: How full the queue may get before the operator is told, whatever the
    #: cause. Deliberately higher than ``_QUEUE_PRESSURE_LIMIT``: that one
    #: marks where a *trade* inverts, which is an internal decision nobody
    #: needs to hear about, while this marks where the pipeline is losing
    #: ground and somebody has to act on it. It sits below 1.0 so the warning
    #: arrives while the loss is still avoidable rather than after.
    _QUEUE_WARN_LIMIT = 0.8
    #: Serialized batches at or under this many bytes are sent as-is. Span
    #: batches gzip at 10-30x — most of every span is byte-identical to its
    #: neighbours by design — but below this line the batch already fits in
    #: a couple of TCP segments and the compression CPU, spent on the single
    #: export thread, buys nothing that matters.
    _COMPRESS_MIN_BYTES = 8 * 1024
    #: Level 6 (zlib's own default). Level 9 was measured to buy almost
    #: nothing on this data and costs visibly more CPU on that same thread.
    _COMPRESS_LEVEL = 6
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
        #: Tracked separately from the drop warning above. The two say
        #: different things — "the backend is refusing us" and "we cannot
        #: keep up" — and one must not suppress the other, least of all
        #: during an outage that causes both at once.
        self._last_pressure_warning = 0.0
        #: Set by :meth:`watch_queue` once the processor above exists.
        self._queue_source: Optional[Any] = None

    # -- backpressure ------------------------------------------------------

    def watch_queue(self, processor: Any) -> None:
        """Let the exporter see how much is waiting behind it.

        Called by ``init()`` after the ``BatchSpanProcessor`` is built, because
        the exporter has to exist first to be handed to it. Without this the
        exporter knows only about the batch in its hands and will happily block
        the single export thread while the queue behind it overflows.

        Read through :meth:`_queue_pressure`, which treats every part of this
        as optional — the attributes are OpenTelemetry internals and have moved
        between releases. When they cannot be read the exporter behaves exactly
        as it did before this existed.
        """
        self._queue_source = processor

    def _queue_pressure(self) -> Optional[float]:
        """How full the export queue is, in ``[0, 1]``, or ``None`` if unknown.

        ``None`` is not zero and must not be treated as it: "the queue is
        empty" and "we cannot see the queue" lead to opposite decisions, and
        guessing the first would make an OpenTelemetry rename look like an idle
        pipeline right when it matters.
        """
        source = self._queue_source
        if source is None:
            return None
        try:
            # The attribute moved to an inner BatchProcessor in newer releases
            # and sat directly on the span processor in older ones.
            holder = getattr(source, "_batch_processor", source)
            # Explicit None tests, not `or`: an empty deque is falsy, and
            # reading a healthy queue as an unreadable one is the failure this
            # method's whole contract is written to avoid.
            queue = getattr(holder, "_queue", None)
            if queue is None:
                queue = getattr(holder, "queue", None)
            capacity = getattr(holder, "_max_queue_size", None)
            if capacity is None:
                capacity = getattr(holder, "max_queue_size", None)
            if queue is None or not capacity:
                return None
            return min(len(queue) / float(capacity), 1.0)
        except Exception:
            return None

    def _warn_if_falling_behind(self) -> None:
        """Say so, on our logger, when the queue is filling up.

        OpenTelemetry already notices this — ``BatchProcessor.emit`` drops from
        a full queue and logs about it — but on *its* logger and once **per
        dropped span**. That leaves two failure modes and no good one. An
        application that configured the ``agentsight`` logger, which is what
        the docs ask for, hears nothing at all while spans are being thrown
        away. An application that configured root logging gets one line per
        span, at exactly the volume that filled the queue in the first place,
        and the log flood becomes its own incident.

        So this reports it once a minute, on the logger the user was told to
        configure, and before the queue is full rather than after — at 100%
        the only honest thing left to say is how much has already been lost.
        The message carries the three things that actually change the outcome,
        because a warning that only announces loss cannot be acted on.
        """
        pressure = self._queue_pressure()
        if pressure is None or pressure < self._QUEUE_WARN_LIMIT:
            return
        now = time.monotonic()
        if now - self._last_pressure_warning < self._WARN_INTERVAL:
            return
        self._last_pressure_warning = now
        if pressure >= 1.0:
            state = ("export queue is full; spans are now being dropped as "
                     "they are recorded")
        else:
            state = ("export queue is %d%% full; spans will be dropped once it "
                     "reaches 100%%" % round(pressure * 100))
        self._logger.warning(
            "%s. The exporter cannot keep up with this process: raise "
            "max_queue_size to absorb bursts, lower export_interval_ms to "
            "drain more often, or check that ingest is reachable.",
            state,
        )

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        try:
            # Read before the POST, not after: this is the depth at the moment
            # the batch was picked up, and it still gets reported if the
            # request then hangs for the full timeout.
            self._warn_if_falling_behind()
            payload = build_payload(spans)
            if not payload["conversations"]:
                return SpanExportResult.SUCCESS
            return self._post(payload)
        except Exception as exc:
            self._logger.error("span export failed: %s", exc)
            return SpanExportResult.FAILURE

    def _post(self, payload: Dict[str, Any]) -> SpanExportResult:
        # Serialized (and possibly compressed) ONCE, before the retry loop:
        # every attempt sends the same bytes, and a retry must not pay the
        # CPU again for an answer that did not depend on the encoding.
        # ``allow_nan=False`` matches what ``requests``' own ``json=`` kwarg
        # did here before — strict JSON, refused locally rather than shipped
        # to a parser that rejects it anyway. ``Content-Type`` stays correct
        # because it is pinned on the session headers in ``__init__``.
        body = json.dumps(payload, allow_nan=False).encode("utf-8")
        headers: Optional[Dict[str, str]] = None

        # Compression is feature-detected, never assumed — decided
        # deliberately (audit F-04, option 1). This SDK is published and
        # versioned, and a self-hosted backend may lag it; a gzipped batch
        # sent to a backend that cannot decode it is a terminal 400 in the
        # loop below, i.e. silent, total data loss for whoever upgraded the
        # SDK first. So the exporter compresses only after the key preflight
        # has seen ``GET /api/me/`` advertise ``gzip-ingest``. Every fallback
        # — preflight disabled, still in flight, unreachable, or a backend
        # that predates the capability list — leaves batches uncompressed,
        # which every backend accepts. The cost of that caution is only the
        # first second or two of a process's batches travelling fat.
        if (
            len(body) > self._COMPRESS_MIN_BYTES
            and _settings.has_capability(_settings.GZIP_INGEST)
        ):
            body = gzip.compress(body, compresslevel=self._COMPRESS_LEVEL)
            headers = {"Content-Encoding": "gzip"}

        last_failure = "unknown"
        for attempt in range(self._MAX_RETRIES):
            pause: Optional[float] = None
            try:
                response = self._session.post(
                    self._url, data=body, headers=headers, timeout=self._TIMEOUT
                )
                if response.status_code in (200, 201):
                    self.last_response = response.json() if response.content else {}
                    self._logger.debug(
                        "exported %d conversation(s)", len(payload["conversations"])
                    )
                    return SpanExportResult.SUCCESS

                if response.status_code == 429:
                    # Throttled, not refused. The batch is fine and the same
                    # bytes will be accepted once the window rolls over, so
                    # this is the one 4xx worth waiting on — dropping it loses
                    # data that nothing was wrong with.
                    #
                    # Unless something is waiting behind it. Then the wait is
                    # no longer free, and it is paid for in spans that are
                    # dropped without ever reaching this code.
                    pressure = self._queue_pressure()
                    if pressure is not None and pressure >= self._QUEUE_PRESSURE_LIMIT:
                        self._warn_dropped(
                            "ingest throttled (429) and the export queue is %d%% "
                            "full; dropped this batch rather than blocking the "
                            "export thread while the queue overflows. Raise "
                            "export_interval_ms, or ask for a higher ingest rate."
                            % round(pressure * 100)
                        )
                        return SpanExportResult.FAILURE

                    pause = retry_after(response, self._MAX_RETRY_AFTER)
                    last_failure = "throttled by ingest (429)"
                    self._logger.debug(
                        "ingest throttled (attempt %d/%d), waiting %ss",
                        attempt + 1,
                        self._MAX_RETRIES,
                        pause if pause is not None else self._BACKOFF[0],
                    )

                elif 400 <= response.status_code < 500:
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
                        % (response.status_code, _rejection_detail(response))
                    )
                    return SpanExportResult.FAILURE

                else:
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
                time.sleep(self._BACKOFF[attempt] if pause is None else pause)

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
