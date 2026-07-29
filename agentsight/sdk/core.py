"""SDK lifecycle: ``init()``, the tracer, flushing and shutdown.

Deliberately does not import ``agentsight.config`` or any 0.0.x module. The
old package builds three singletons at import time and raises without an API
key, which is exactly the behaviour design §10 forbids — and those modules are
being removed in 1.0 anyway.
"""

import atexit
import logging
import os
import re
import threading
from typing import Any, List, Optional, Sequence, Union

from opentelemetry import trace as otel_trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from agentsight.sdk import watchdog
from agentsight.sdk.exporter import AgentSightSpanExporter, SDK_NAME, SDK_VERSION
from agentsight.sdk.processors import TurnBufferingProcessor

logger = logging.getLogger("agentsight")

API_KEY_PATTERN = re.compile(r"^ags_[a-f0-9]{32}_[a-f0-9]{6}$", re.IGNORECASE)

DEFAULT_ENDPOINT = "https://api.agentsight.io"

_TRACER_NAME = "agentsight"


class _State:
    """Process-wide SDK state. One per process, guarded by a lock."""

    def __init__(self):
        self.lock = threading.Lock()
        self.enabled = False
        self.provider: Optional[TracerProvider] = None
        self.exporter: Optional[AgentSightSpanExporter] = None
        self.tracer = None
        self.environment: Optional[str] = None
        self.turn_timeout_ms: int = watchdog.DEFAULT_TIMEOUT_MS


_state = _State()


def is_enabled() -> bool:
    return _state.enabled


def get_tracer():
    return _state.tracer


def get_exporter() -> Optional[AgentSightSpanExporter]:
    return _state.exporter


def get_turn_timeout_ms() -> int:
    """How long a turn may stay open after its lifetime was handed to
    ``turn.wrap()`` before it is closed as incomplete. 0 disables the deadline."""
    return _state.turn_timeout_ms


def init(
    api_key: Optional[str] = None,
    *,
    endpoint: Optional[str] = None,
    environment: Optional[str] = None,
    auto_instrument: Union[bool, Sequence[str]] = True,
    export_interval_ms: int = 1000,
    max_queue_size: int = 2048,
    turn_timeout_ms: int = watchdog.DEFAULT_TIMEOUT_MS,
) -> bool:
    """Start the SDK. Returns whether tracking is active.

    Never raises. A missing or malformed key logs an error and leaves the SDK
    disabled, at which point every scope and decorator is a pass-through and
    the application behaves exactly as if AgentSight were not installed.
    """
    with _state.lock:
        if _state.enabled:
            logger.debug("agentsight.init() called twice; ignoring")
            return True

        resolved_key = api_key or os.getenv("AGENTSIGHT_API_KEY")
        resolved_endpoint = (
            endpoint or os.getenv("AGENTSIGHT_API_ENDPOINT") or DEFAULT_ENDPOINT
        )

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
            exporter = AgentSightSpanExporter(resolved_endpoint, resolved_key, logger)

            # Order matters: buffering sits ABOVE batching, so a discarded turn
            # never reaches the export queue at all.
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
            _state.enabled = True
        except Exception as exc:
            logger.error("AgentSight disabled: initialization failed: %s", exc)
            return False

    atexit.register(shutdown)

    if auto_instrument:
        _install_instrumentation(auto_instrument)

    logger.info("AgentSight initialized (endpoint=%s)", resolved_endpoint)
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
    """
    if not _state.enabled or _state.provider is None:
        return False
    try:
        return bool(_state.provider.force_flush(timeout_ms))
    except Exception as exc:
        logger.debug("flush failed: %s", exc)
        return False


def shutdown() -> None:
    """Flush and tear down. Registered with ``atexit`` by :func:`init`."""
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
