"""SDK lifecycle: ``init()``, the tracer, flushing and shutdown.

Deliberately does not import ``agentsight.config``: that module raises on a
malformed key at construction, and ``init()`` must never raise into user code
(design §10). The constants both planes need live in ``agentsight._settings``
instead, which holds nothing but literals and pure functions.
"""

import atexit
import logging
import os
import threading
from typing import List, Optional, Sequence, Union

from opentelemetry import trace as otel_trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExporter

from agentsight import _settings
from agentsight.sdk import watchdog
from agentsight.sdk.exporter import SDK_NAME, SDK_VERSION, AgentSightSpanExporter
from agentsight.sdk.file_exporter import FileSpanExporter
from agentsight.sdk.processors import TurnBufferingProcessor

logger = logging.getLogger("agentsight")

#: Shared with the data plane. ``_settings`` is the one module both sides may
#: import: it holds only constants and pure functions, so it cannot raise the
#: way ``agentsight.config`` does.
API_KEY_PATTERN = _settings.API_KEY_PATTERN

DEFAULT_ENDPOINT = _settings.DEFAULT_ENDPOINT

_TRACER_NAME = "agentsight"


class _State:
    """Process-wide SDK state. One per process, guarded by a lock."""

    def __init__(self):
        self.lock = threading.Lock()
        self.enabled = False
        self.provider: Optional[TracerProvider] = None
        #: Typed to the OTel interface, not our concrete class: the exporter
        #: is the transport seam, and nothing outside it may depend on which
        #: transport is behind it (design §13, transport question).
        self.exporter: Optional[SpanExporter] = None
        self.tracer = None
        self.environment: Optional[str] = None
        self.turn_timeout_ms: int = watchdog.DEFAULT_TIMEOUT_MS
        #: What init() resolved, kept for the data-plane calls (attachment
        #: uploads) that share the key but not the span pipeline. The key is
        #: None when init() ran without one (file exporter, custom transport).
        self.api_key: Optional[str] = None
        self.endpoint: str = DEFAULT_ENDPOINT


_state = _State()


def is_enabled() -> bool:
    return _state.enabled


def get_tracer():
    return _state.tracer


def get_exporter() -> Optional[SpanExporter]:
    return _state.exporter


def get_turn_timeout_ms() -> int:
    """How long a turn may stay open after its lifetime was handed to
    ``turn.wrap()`` before it is closed as incomplete. 0 disables the deadline."""
    return _state.turn_timeout_ms


def api_credentials() -> "tuple[Optional[str], str]":
    """``(api_key, endpoint)`` as resolved by :func:`init`."""
    return _state.api_key, _state.endpoint


def default_environment() -> Optional[str]:
    """The deployment-wide environment from ``init(environment=...)`` or
    ``AGENTSIGHT_ENVIRONMENT``. Conversations that don't name their own
    environment inherit it; one that does always wins."""
    return _state.environment


def init(
    api_key: Optional[str] = None,
    *,
    endpoint: Optional[str] = None,
    environment: Optional[str] = None,
    auto_instrument: Union[bool, Sequence[str]] = True,
    export_interval_ms: int = 1000,
    max_queue_size: int = 2048,
    turn_timeout_ms: int = watchdog.DEFAULT_TIMEOUT_MS,
    span_exporter: Optional[SpanExporter] = None,
) -> bool:
    """Start the SDK. Returns whether tracking is active.

    Never raises. A missing or malformed key logs an error and leaves the SDK
    disabled, at which point every scope and decorator is a pass-through and
    the application behaves exactly as if AgentSight were not installed.

    ``span_exporter`` swaps the transport: any OTel ``SpanExporter`` slots in
    behind the same buffering and batching. With one supplied, the API key is
    not required — it exists only to authenticate the default transport.

    Setting ``AGENTSIGHT_FILE_EXPORTER`` to a directory does the same thing
    without a code change: spans are written there as the JSON the ingest
    endpoint would have received, and nothing is sent over the network. It is a
    development aid for seeing what an integration emits. An explicit
    ``span_exporter`` still wins, because code is a clearer statement of intent
    than an environment left over in a shell.
    """
    with _state.lock:
        if _state.enabled:
            logger.debug("agentsight.init() called twice; ignoring")
            return True

        resolved_key = api_key or os.getenv("AGENTSIGHT_API_KEY")
        resolved_endpoint = (
            endpoint or os.getenv("AGENTSIGHT_API_ENDPOINT") or DEFAULT_ENDPOINT
        )
        file_destination = os.getenv("AGENTSIGHT_FILE_EXPORTER")

        # Only the HTTP transport has anything to authenticate, so only the
        # HTTP transport requires a key.
        if span_exporter is None and not file_destination:
            if not resolved_key:
                logger.error(
                    "AgentSight disabled: no API key. Pass api_key= or set "
                    "AGENTSIGHT_API_KEY."
                )
                return False

            if not API_KEY_PATTERN.match(resolved_key):
                logger.error("AgentSight disabled: API key is malformed.")
                return False

        try:
            resource = Resource.create(
                {
                    "service.name": SDK_NAME,
                    "telemetry.sdk.name": SDK_NAME,
                    "telemetry.sdk.version": SDK_VERSION,
                }
            )
            provider = TracerProvider(resource=resource)

            exporter: SpanExporter
            destination: str
            if span_exporter is not None:
                exporter = span_exporter
                destination = type(span_exporter).__name__
            elif file_destination:
                exporter = FileSpanExporter(file_destination, logger)
                destination = exporter.directory
                # Loud, because replacing the transport out from under someone
                # who thinks they are shipping data is the failure this guards
                # against — a stale variable in a shell must not look like a
                # working integration.
                logger.info(
                    "AgentSight: AGENTSIGHT_FILE_EXPORTER is set, so spans are "
                    "being written to %s and are NOT sent to the ingest "
                    "endpoint.",
                    destination,
                )
            else:
                exporter = AgentSightSpanExporter(
                    resolved_endpoint, resolved_key, logger
                )
                destination = resolved_endpoint

            # Order matters: buffering sits ABOVE batching, so a turn and its
            # children enter the export queue together and land in the same
            # payload — which is what lets ingest treat the family atomically.
            provider.add_span_processor(
                TurnBufferingProcessor(
                    BatchSpanProcessor(
                        exporter,
                        max_queue_size=max_queue_size,
                        schedule_delay_millis=export_interval_ms,
                    )
                )
            )

            _state.provider = provider
            _state.exporter = exporter
            _state.tracer = otel_trace.get_tracer(_TRACER_NAME, SDK_VERSION, provider)
            _state.environment = environment or os.getenv("AGENTSIGHT_ENVIRONMENT")
            _state.turn_timeout_ms = turn_timeout_ms
            _state.api_key = resolved_key
            _state.endpoint = resolved_endpoint
            _state.enabled = True
        except Exception as exc:
            logger.error("AgentSight disabled: initialization failed: %s", exc)
            return False

    atexit.register(shutdown)

    if auto_instrument:
        _install_instrumentation(auto_instrument)

    logger.info("AgentSight initialized (exporting to %s)", destination)
    return True


def _install_instrumentation(selection: Union[bool, Sequence[str]]) -> None:
    """Register provider patches and framework handlers.

    Phase 5/6 work. Each target is installed independently and a failure in one
    never disables the others or the SDK.
    """
    from agentsight.sdk import instrumentation

    targets: List[str] = (
        list(instrumentation.ALL_TARGETS) if selection is True else list(selection)
    )
    for target in targets:
        try:
            instrumentation.install(target, logger)
        except Exception as exc:
            # Expected and uninteresting for a provider the user does not have
            # installed, which is why this is debug and not a warning.
            logger.debug("instrumentation for %s not installed: %s", target, exc)


def flush(timeout_ms: int = 10_000) -> bool:
    """Force a synchronous export.

    Needed wherever the process may be frozen or killed before the background
    timer fires — serverless handlers and short scripts.

    Delivers everything whose turn has ended. Spans inside a turn that is
    still open are deliberately *not* delivered: they wait for their turn so
    the family lands in one payload, and the open turn span itself cannot be
    exported until it ends. End the turn (or let it end), then flush.
    """
    if not _state.enabled or _state.provider is None:
        return False
    try:
        return bool(_state.provider.force_flush(timeout_ms))
    except Exception as exc:
        logger.debug("flush failed: %s", exc)
        return False


def shutdown() -> None:
    """Flush and tear down. Registered with ``atexit`` by :func:`init`.

    The order here is load-bearing:

    1. ``watchdog.shutdown()`` fires every pending deadline, so each open
       *deferred* turn ends now, marked incomplete with reason ``shutdown``.
       Ending it hands its buffered children plus the turn span to the batch
       queue — which must still be alive, hence watchdog first.
    2. ``provider.shutdown()`` then releases any orphaned children of turns
       that could not be ended (a plain ``with`` block open in a live
       thread) and force-flushes the queue.

    Flip the order and every turn in flight at exit is silently lost: the
    spans would end after the pipeline below them is gone.

    Only covers orderly exits. ``atexit`` does not run on SIGTERM — how
    containers stop — or SIGKILL; installing signal handlers from a library
    would fight the host application, so that is deliberately its job.
    """
    with _state.lock:
        if not _state.enabled:
            return
        _state.enabled = False
        provider = _state.provider

    watchdog.shutdown()

    if provider is not None:
        try:
            provider.shutdown()
        except Exception as exc:
            logger.debug("shutdown failed: %s", exc)
