"""SDK lifecycle: ``init()``, the tracer, flushing and shutdown.

``init()`` must never raise into user code (design §10), so nothing on this
path may import a module that validates on construction. The constants and
resolvers both planes need live in ``agentsight._settings``, which holds
nothing but literals and pure functions.
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
#: import: it holds only constants and pure functions, so importing it cannot
#: raise, read the environment or open anything.
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
    environment inherit it; one that does always wins.

    Resolved on every read rather than once in ``init()``, deliberately:
    ``_state.environment`` holds the *raw* value, and the key preflight can
    widen the allowed set after ``init()`` returns. A custom slug is ``None``
    here — conversations fall back to the agent's default — until the
    preflight confirms it, and the real slug from then on.
    """
    return _settings.normalize_environment(_state.environment)


def init(
    api_key: Optional[str] = None,
    *,
    endpoint: Optional[str] = None,
    environment: Optional[str] = None,
    auto_instrument: Union[bool, Sequence[str]] = True,
    export_interval_ms: int = 5000,
    max_queue_size: int = 2048,
    turn_timeout_ms: int = watchdog.DEFAULT_TIMEOUT_MS,
    span_exporter: Optional[SpanExporter] = None,
    verify_key: bool = True,
) -> bool:
    """Start the SDK. Returns whether tracking is active.

    Never raises. A missing or malformed key logs an error and leaves the SDK
    disabled, at which point every scope and decorator is a pass-through and
    the application behaves exactly as if AgentSight were not installed.

    ``span_exporter`` swaps the transport: any OTel ``SpanExporter`` slots in
    behind the same buffering and batching. With one supplied, the API key is
    not required — it exists only to authenticate the default transport.

    ``export_interval_ms`` is how long finished spans wait before a batch is
    POSTed, and it is a **per-process** rate against a **per-agent** ingest
    budget. Every worker in a deployment spends from the same allowance, so the
    figure that matters is ``60_000 / export_interval_ms × worker_count``. At
    the default that is 12 batches a minute each, which leaves room for a few
    dozen workers on one agent; at 1000 it was 60, and ten busy workers were
    enough to start being throttled. Lower it if you want the dashboard to
    update faster and know your worker count is small — nothing in the SDK
    reads its own data back, so the only cost of the wait is freshness.

    Setting ``AGENTSIGHT_FILE_EXPORTER`` to a directory does the same thing
    without a code change: spans are written there as the JSON the ingest
    endpoint would have received, and nothing is sent over the network. It is a
    development aid for seeing what an integration emits. An explicit
    ``span_exporter`` still wins, because code is a clearer statement of intent
    than an environment left over in a shell.

    ``verify_key`` asks the backend once, on a background thread, whether the
    key actually works. Only the shape of a key can be checked locally, and a
    key that is revoked, belongs to an inactive subscription, or carries the
    read role instead of write is indistinguishable from a good one until the
    first batch is refused — at which point the exporter drops it as a terminal
    4xx and says so once a minute, forever. Something that fails that quietly
    should be announced while somebody is still watching the logs. The check
    never blocks ``init()``, never raises, and its failure changes nothing:
    tracking stays on, because a preflight that could not reach the backend is
    not evidence the key is bad. Pass ``False`` to skip it entirely.

    The same response names the agent's environments, and the SDK learns them:
    it is how a custom slug — anything beyond ``production``/``development`` —
    becomes acceptable to ``init(environment=...)`` and
    ``conversation(environment=...)``. Passing ``False`` therefore also
    disables custom environment discovery, leaving only the built-in pair.
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
            batching = BatchSpanProcessor(
                exporter,
                max_queue_size=max_queue_size,
                schedule_delay_millis=export_interval_ms,
            )
            # Only now can the exporter see what is waiting behind it: it had
            # to exist before the processor it is handed to. Without this it
            # would wait out a throttle no matter how full the queue was.
            watch = getattr(exporter, "watch_queue", None)
            if callable(watch):
                watch(batching)
            provider.add_span_processor(TurnBufferingProcessor(batching))

            _state.provider = provider
            _state.exporter = exporter
            _state.tracer = otel_trace.get_tracer(_TRACER_NAME, SDK_VERSION, provider)
            # Stored raw, not resolved: the preflight started below may widen
            # the allowed set after init() returns, so resolution happens on
            # every read in default_environment(). _check_environment() only
            # vets the value for an early, loud warning.
            _state.environment = _check_environment(
                environment or os.getenv("AGENTSIGHT_ENVIRONMENT")
            )
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

    # Only the HTTP transport authenticates, so only it has a key worth
    # checking — the file exporter and a caller-supplied exporter have none.
    if verify_key and resolved_key and span_exporter is None and not file_destination:
        _start_key_preflight(resolved_key, resolved_endpoint)

    logger.info("AgentSight initialized (exporting to %s)", destination)
    return True


def _start_key_preflight(api_key: str, endpoint: str) -> None:
    """Ask ``GET /api/me/`` whether this key works, off the startup path.

    A daemon thread, so a process that finishes before the answer arrives is
    not held open by it, and so a hung backend cannot delay an exit.
    """
    try:
        thread = threading.Thread(
            target=_verify_key,
            args=(api_key, endpoint),
            name="agentsight-preflight",
            daemon=True,
        )
        thread.start()
    except Exception as exc:  # pragma: no cover — thread creation failing
        logger.debug("key preflight could not start: %s", exc)


def _verify_key(api_key: str, endpoint: str) -> None:
    """The preflight body. Runs on its own thread and swallows everything.

    The distinction that matters here is between *this key will never work*
    and *we could not find out right now*. Only the first is worth an error:
    the second is what a network blip, a proxy, or a backend that predates
    ``/api/me/`` looks like, and shouting about those trains people to ignore
    the message that matters.

    ``max_retries=1`` for the same reason, and it is not a detail. The shared
    transport logs a **warning** before each retry, so a preflight against a
    backend that happens to be unreachable — a process starting during a
    deploy, an outbound rule not applied yet — announced the outage twice at
    WARNING before quietly concluding "don't know" at DEBUG. That is precisely
    the case this function promises to keep quiet about, and the noise arrived
    from a check the user never asked for. Retrying could not help either: if
    the backend answers, one GET is enough; if it does not, a second attempt
    2.5 seconds later says exactly the same thing.
    """
    from agentsight._transport import Transport
    from agentsight.exceptions import (
        AuthenticationError,
        NotFoundError,
        PermissionDeniedError,
        SubscriptionInactiveError,
    )

    transport = Transport(api_key, endpoint, timeout=10, max_retries=1)
    try:
        identity = transport.request("GET", "/api/me/")
    # Subclass first: SubscriptionInactiveError *is* an AuthenticationError,
    # and it is the one 401 that rotating a key will not fix — telling someone
    # to replace a key that is fine is worse than saying nothing.
    except SubscriptionInactiveError:
        logger.error(
            "AgentSight: the subscription behind this API key is not active, "
            "so %s will refuse every batch. Tracking stays on and costs "
            "nothing, but nothing will reach the dashboard until it is.",
            endpoint,
        )
        return
    except AuthenticationError:
        logger.error(
            "AgentSight: this API key was refused by %s. Spans will be "
            "collected and then dropped by the exporter until it is replaced. "
            "Check AGENTSIGHT_API_KEY against the dashboard — a rotated or "
            "revoked key looks exactly like a working one from here.",
            endpoint,
        )
        return
    except PermissionDeniedError:
        # /api/me/ needs only the read role, which write implies — so a 403
        # here is a key the backend will not talk to at all.
        logger.error(
            "AgentSight: %s refused this API key on /api/me/, which needs only "
            "the read role. Ingest will refuse it too.",
            endpoint,
        )
        return
    except NotFoundError:
        # A backend older than /api/me/. Says nothing about the key.
        logger.debug("key preflight: %s has no /api/me/ route", endpoint)
        return
    except Exception as exc:
        logger.debug("key preflight did not complete: %s", exc)
        return
    finally:
        try:
            transport.close()
        except Exception:  # pragma: no cover
            pass

    # The same response carries the authoritative environment list; learning
    # it is what lets a custom slug pass normalize_environment(). Its own
    # try/except, like the role read below, because a backend that shapes
    # this part differently must not turn a successful preflight into a
    # logged failure.
    try:
        rows = (identity or {}).get("environments") or ()
        _settings.learn_environments(
            row.get("slug") for row in rows if isinstance(row, dict)
        )
    except Exception as exc:
        logger.debug("key preflight could not read the environments: %s", exc)

    # The optional behaviours this backend advertises — "gzip-ingest" is what
    # lets the exporter start compressing batches. Learned here rather than
    # assumed because the SDK is published and a self-hosted backend can lag
    # it; see AgentSightSpanExporter._post for the full reasoning. Its own
    # try/except for the same reason as the environments above.
    try:
        _settings.learn_capabilities((identity or {}).get("capabilities") or ())
    except Exception as exc:
        logger.debug("key preflight could not read the capabilities: %s", exc)

    try:
        role = (identity or {}).get("role")
        agent = (identity or {}).get("agent_name") or (identity or {}).get("agent_id")
        if role == "read":
            # Format-valid, live, and useless for tracking: ingest takes the
            # write role. This is the one the exporter would report as a bare
            # 403 with no hint that the key is simply the wrong kind.
            logger.error(
                "AgentSight: this API key has the read role, and ingest "
                "requires write. Every batch will be refused. Issue a write "
                "key for agent %s.",
                agent,
            )
        else:
            logger.debug(
                "key preflight ok: agent %s, role %s", agent, role
            )
    except Exception as exc:  # pragma: no cover
        logger.debug("key preflight could not read the identity: %s", exc)


def _check_environment(raw: Optional[str]) -> Optional[str]:
    """Vet the deployment-wide environment at startup — and keep it raw.

    Loud, and at startup, because the alternative is silent: ingest rejects an
    unknown environment with a 400, the exporter treats a 4xx as terminal, and
    the drop warning is rate-limited — so a typo in ``AGENTSIGHT_ENVIRONMENT``
    loses every batch for the life of the process while looking healthy. An
    error here happens while someone is still watching the logs.

    Returns the raw (stripped) value rather than the resolved slug — this is
    the subtle half of custom-environment support. What counts as allowed can
    change after init() returns, when the key preflight learns the agent's
    real environment list, so resolution belongs to default_environment(),
    which normalizes on every read. Resolving eagerly here would throw a
    custom slug away moments before the preflight confirmed it.
    """
    if not raw:
        return None
    raw = str(raw).strip()
    if not raw:
        return None
    if _settings.normalize_environment(raw) is None:
        logger.error(
            "AgentSight: environment %r is not one the SDK can confirm this "
            "agent has (confirmed so far: %s). Conversations will be recorded "
            "against the agent's default environment unless the key preflight "
            "learns this slug from the backend — if it exists server-side, "
            "that happens moments from now and it is honoured from then on; "
            "if it is a typo, nothing will ever be recorded against it. "
            "AgentSight().environments() is the authoritative list.",
            raw,
            ", ".join(_settings.allowed_environments()),
        )
    return raw


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

    # The attachment plane keeps a pooled session of its own; it has nothing
    # to flush, so it goes last.
    try:
        from agentsight.sdk.uploads import close_transports

        close_transports()
    except Exception as exc:  # pragma: no cover
        logger.debug("closing upload transports failed: %s", exc)
