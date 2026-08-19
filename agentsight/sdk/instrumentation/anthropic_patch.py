"""Token capture for the ``anthropic`` SDK.

Patched on the resource *classes*, like the OpenAI patch and for the same
reason: ``AnthropicVertex``, ``AnthropicBedrock``, ``AnthropicAWS`` and
``AnthropicFoundry`` all build the very same ``Messages``/``AsyncMessages``, so
one class patch covers every platform. (Their model ids are platform-flavoured
— ``anthropic.claude-...-v2:0`` on Bedrock, ``claude-...@20240229`` on Vertex —
so the backend's prefix match misses them and they book as ``unpriced`` until
somebody adds a rate for that shape. Tokens are still exact, so the cost is
recoverable with ``reprice_token_usage`` whenever that happens.)

Three separate patch points are needed where one would seem to do:

* ``.parse()`` and ``.stream()`` **do not route through** ``create``. Both build
  their own ``self._post(...)``, so a patch on ``create`` alone silently loses
  every structured-output call and every ``with client.messages.stream(...)``
  block — which is the idiomatic streaming API.
* ``beta.messages`` is a *different class that happens to share the name*
  ``Messages``. Patching the stable one does nothing for it, and every
  ``tool_runner`` loop iteration goes through it.

``.stream()`` is instrumented at ``MessageStreamManager.__enter__`` rather than
at ``Messages.stream``. ``stream()`` returns the manager without making a
request; the request fires in ``__enter__``, which is also the only place the
``MessageStream`` object exists. Python looks ``__enter__`` up on the type, so
there is no instance-level hook and no way to do this from ``stream()`` short of
impersonating the whole class.

Legacy Text Completions is deliberately not patched: ``anthropic.types.
Completion`` has no ``usage`` field at all, so the span could carry a model and
a duration but zero tokens and therefore no cost.
"""

import functools
import inspect
import weakref
from typing import Any, Callable, Dict, Optional

from agentsight.sdk import context as ags_context
from agentsight.sdk.instrumentation.base import (
    already_patched,
    capturing,
    from_anthropic,
    mark_patched,
    now_ns,
    record_llm_call,
)
from agentsight.sdk.semconv import LLMAttributes

#: The four counters ``from_anthropic`` reads. Named the same on ``Usage``,
#: ``MessageDeltaUsage`` and their beta twins.
_COUNTERS = (
    "input_tokens",
    "output_tokens",
    "cache_read_input_tokens",
    "cache_creation_input_tokens",
)

#: Set by ``with_raw_response`` / ``with_streaming_response`` before they call
#: the very same ``create`` we patched — the same Stainless plumbing, and the
#: same header name, as the OpenAI SDK.
_RAW_RESPONSE_HEADER = "X-Stainless-Raw-Response"


def _record(
    usage: Any,
    model: Optional[str],
    start_time_ns: int,
    end_time_ns: int,
    streaming: bool,
    logger: Any,
    error: Optional[BaseException] = None,
    requested_model: Optional[str] = None,
    model_hint: Optional[str] = None,
) -> None:
    """Emit one ``llm`` span. Never raises into the caller."""
    try:
        extra: Dict[str, Any] = {}
        if streaming:
            extra[LLMAttributes.STREAMING] = True
            if usage is None:
                # Stream closed without a usage event: the 0/0 counts are
                # unknowns, not zeros — mark it so ingest can tell.
                extra[LLMAttributes.USAGE_REPORTED] = False
        record_llm_call(
            **from_anthropic(usage, model),
            operation="chat",
            requested_model=requested_model,
            model_hint=model_hint,
            start_time_ns=start_time_ns,
            end_time_ns=end_time_ns,
            extra=extra or None,
            error=error,
        )
    except Exception:
        logger.debug("agentsight: anthropic span failed", exc_info=True)


# ---------------------------------------------------------------------------
# Streaming
# ---------------------------------------------------------------------------


class _StreamRecorder:
    """Merges the usage scattered across a stream into one span.

    Anthropic splits the numbers over two events and neither is complete:
    ``message_start`` carries the final input and cache counts plus a *priming*
    ``output_tokens``, and ``message_delta`` carries the real output. Both sides
    of every counter on ``message_delta`` are **cumulative totals, not deltas**
    — the SDK's own accumulator assigns rather than adds — so this overwrites.
    Summing them would multiply output tokens by the number of deltas.
    """

    def __init__(self, model: Optional[str], start_time_ns: int, logger: Any):
        self._model = model
        #: Kept separately because ``_model`` is overwritten by the resolved id
        #: the moment ``message_start`` arrives. Without a second slot the alias
        #: the caller typed is lost on every streamed call, which is most of an
        #: agent's traffic.
        self._requested_model = model
        #: Snapshotted here because __init__ runs while the call starts — for
        #: ``create`` inside the patched method, for ``.stream()`` inside the
        #: manager's ``__enter__``, which is where the request actually fires.
        #: ``finish`` runs when the stream drains, which can be after the
        #: caller's ``model_hint`` block has exited.
        self._model_hint = ags_context.current_model_hint()
        self._start_time_ns = start_time_ns
        self._logger = logger
        self._usage: Dict[str, int] = {}
        self._finished = False
        self._error: Optional[BaseException] = None

    def capture(self, event: Any) -> None:
        try:
            # ``message_start`` is the only raw event carrying a whole Message,
            # and ``message_delta`` the only one carrying a bare usage. Keying
            # on shape rather than on ``type`` covers the beta events, which are
            # a separate class hierarchy with identical fields.
            message = getattr(event, "message", None)
            if message is not None:
                self._model = getattr(message, "model", None) or self._model
                self._merge(getattr(message, "usage", None))
            else:
                self._merge(getattr(event, "usage", None))
        except Exception:
            self._logger.debug("agentsight: anthropic usage read failed", exc_info=True)

    def _merge(self, usage: Any) -> None:
        if usage is None:
            return
        for counter in _COUNTERS:
            value = getattr(usage, counter, None)
            if value is not None:
                self._usage[counter] = value

    def fail(self, error: BaseException) -> None:
        """Remember why the stream died, so the span says so. Consumer
        disconnects (``GeneratorExit``) never land here — the call itself did
        not fail, someone just stopped listening."""
        self._error = error

    def finish(self) -> None:
        # A stream can reach its end more than once — closed by the user, closed
        # again by the manager's ``__exit__``, then collected — and a second
        # span here would double the tokens.
        if self._finished:
            return
        self._finished = True
        _record(
            # Empty means no usage event ever arrived. It has to reach _record
            # as None, not as {}, or the stream is recorded as a complete call
            # that really did bill 0/0 — and the backend prices that as an
            # authoritative $0 instead of counting it unreported.
            self._usage or None,
            self._model,
            self._start_time_ns,
            now_ns(),
            True,
            self._logger,
            error=self._error,
            requested_model=self._requested_model,
            model_hint=self._model_hint,
        )


def _iterator_of(stream: Any, logger: Any) -> Any:
    """The one attribute every way of consuming a stream funnels through.

    ``Stream.__next__``/``__iter__`` and ``AsyncStream.__anext__``/``__aiter__``
    all read ``_iterator``, and ``MessageStream`` reads it through the raw
    stream it wraps — so replacing it instruments direct iteration,
    ``text_stream``, ``get_final_message()`` and ``until_done()`` at once, while
    leaving the object's type, identity, ``.response``, ``.close()`` and
    context-manager behaviour exactly as the user found them.

    A proxy is not an option here. ``MessageStream`` reaches past the public
    surface into ``raw_stream.response``, and ``isinstance(x, Stream)`` is a
    lie on this SDK — ``_SyncStreamMeta.__instancecheck__`` is overridden and
    returns True only for ``MessageStream``.

    ``None`` means leave this object alone. Either it is already instrumented,
    or it is a ``with_streaming_response`` body the user has not entered yet —
    ``with_raw_response`` no longer lands here, :func:`_unwrap_raw` opens it
    first — or a stream from a release that renamed the attribute. The last two
    record nothing at all rather than zero: a span reporting no tokens would be
    indistinguishable from a real call that cost nothing.
    """
    if already_patched(stream):
        # Two patch points can reach one stream: ``create(stream=True)`` and
        # ``__enter__`` both instrument whatever they are handed, and whether
        # ``.stream()`` builds its request through ``create`` is a fact about
        # the installed anthropic, not something this file can decide. Wrapping
        # twice would nest two recorders over one call and double its tokens.
        return None
    source = getattr(stream, "_iterator", None)
    if source is None:
        logger.debug("agentsight: anthropic response not instrumented")
    return source


def _end_on_close(stream: Any, close_iterator: Callable, logger: Any) -> None:
    """Make ``close()`` the deterministic end of a half-read stream.

    Breaking out of a stream leaves the wrapper generator suspended, and nothing
    runs its ``finally`` until the collector gets to it — by which time the
    conversation scope has usually closed and ``capturing()`` discards the span,
    so the tokens are not late but lost. Async is worse: an async generator is
    finalized by a task the loop schedules, typically while it is shutting down.

    An instance attribute rather than a class patch: this is scoped to the
    streams we instrumented and leaves ``isinstance``, ``.response`` and
    everything else on the class alone.

    The stream is held weakly, and the original taken off the class rather than
    the instance, so the replacement does not close over the stream's own bound
    method. That would put the stream in a reference cycle, and a stream simply
    dropped rather than closed would then wait for the cyclic collector — the
    delay this function exists to remove.
    """
    original = getattr(type(stream), "close", None)
    if original is None:
        return
    ref = weakref.ref(stream)

    def close(*args, **kwargs):
        try:
            close_iterator()
        except Exception:
            logger.debug("agentsight: anthropic stream close failed", exc_info=True)
        return original(ref(), *args, **kwargs)

    stream.close = close


def _end_on_close_async(stream: Any, close_iterator: Callable, logger: Any) -> None:
    original = getattr(type(stream), "close", None)
    # Awaiting a close that is not a coroutine would raise inside the user's
    # ``async with`` exit. Losing the deterministic end is the cheaper failure.
    if not inspect.iscoroutinefunction(original):
        return
    ref = weakref.ref(stream)

    async def close(*args, **kwargs):
        try:
            await close_iterator()
        except Exception:
            logger.debug("agentsight: anthropic stream close failed", exc_info=True)
        return await original(ref(), *args, **kwargs)

    stream.close = close


def _watch_stream(stream: Any, recorder: _StreamRecorder, logger: Any) -> Any:
    source = _iterator_of(stream, logger)
    if source is None:
        return None

    def instrumented():
        try:
            for event in source:
                recorder.capture(event)
                yield event
        except GeneratorExit:
            raise
        except BaseException as exc:
            recorder.fail(exc)
            raise
        finally:
            # Runs on exhaustion, on an exception, and on the close() that
            # abandoning the stream triggers — recording what was seen beats
            # recording nothing, and a stream that died raising goes out
            # marked as the failure it was.
            recorder.finish()

    iterator = instrumented()
    stream._iterator = iterator
    mark_patched(stream)
    _end_on_close(stream, iterator.close, logger)
    return iterator


def _watch_async_stream(stream: Any, recorder: _StreamRecorder, logger: Any) -> Any:
    source = _iterator_of(stream, logger)
    if source is None:
        return None

    async def instrumented():
        try:
            async for event in source:
                recorder.capture(event)
                yield event
        except GeneratorExit:
            raise
        except BaseException as exc:
            recorder.fail(exc)
            raise
        finally:
            recorder.finish()

    iterator = instrumented()
    stream._iterator = iterator
    mark_patched(stream)
    _end_on_close_async(stream, iterator.aclose, logger)
    return iterator


# ---------------------------------------------------------------------------
# Wrappers
# ---------------------------------------------------------------------------


def _requested_model(kwargs: dict) -> Optional[str]:
    """Only ever a fallback: the response's own ``model`` is the resolved id.

    It still earns its place — a stream abandoned before ``message_start`` has
    no response to read, and this is the only model name that call will ever
    have.
    """
    model = kwargs.get("model")
    return model if isinstance(model, str) else None


def _watching(logger: Any) -> bool:
    try:
        return capturing()
    except Exception:
        logger.debug("agentsight: anthropic pre-call capture failed", exc_info=True)
        return False


def _raw_marker(kwargs: dict) -> Optional[str]:
    """``"true"`` for ``with_raw_response``, ``"stream"`` for
    ``with_streaming_response``, ``None`` for an ordinary call.

    The provider sets the same header for both wrappers and distinguishes them
    by value, which matters here because only one of the two is safe to open
    (see :func:`_unwrap_raw`).
    """
    return (kwargs.get("extra_headers") or {}).get(_RAW_RESPONSE_HEADER)


def _unwrap_raw(result: Any, kwargs: dict, logger: Any) -> Any:
    """The parsed body behind a ``with_raw_response`` result.

    An APIResponse has neither a ``usage`` nor an ``_iterator``, so before this
    unwrap a raw-wrapped call recorded nothing at all — no span, no tokens, no
    cost, no error. ``parse()`` makes it visible without changing anything the
    caller can observe: it memoises, so their own ``parse()`` returns the
    identical object, and on a ``stream=True`` request it reads no bytes — it
    builds the lazy ``Stream`` over the still-unread response, which is exactly
    the shape :func:`_watch_stream` instruments.

    ``"raw"`` is the successor wrapper generation's spelling of ``"true"``,
    with the same ``parse()`` contract; unused by the resources today, accepted
    now so a release that migrates does not reopen this hole silently.
    ``with_streaming_response`` (``"stream"``) stays untouched: reading that
    body belongs to the user, and its ``parse()`` reads a JSON body whole —
    the exact thing that wrapper exists to let them avoid.

    Anything unexpected leaves the result alone and costs only the telemetry.
    """
    if _raw_marker(kwargs) not in ("true", "raw"):
        return result
    try:
        return result.parse()
    except Exception:
        logger.debug("agentsight: could not read raw response body", exc_info=True)
        return result


def _capture(
    result: Any,
    kwargs: dict,
    start_time_ns: int,
    end_time_ns: int,
    watch: Callable,
    logger: Any,
) -> None:
    """A Message reports its usage on the spot; a Stream reports it as it goes.

    Keyed on the result rather than on ``stream=``, which defaults to the
    ``Omit`` sentinel and is absent from ``parse`` altogether. Raw wrappers are
    opened first, so both branches see the body they expect.
    """
    result = _unwrap_raw(result, kwargs, logger)
    model = _requested_model(kwargs)
    usage = getattr(result, "usage", None)
    if usage is None:
        watch(result, _StreamRecorder(model, start_time_ns, logger), logger)
        return
    _record(
        usage,
        getattr(result, "model", None) or model,
        start_time_ns,
        end_time_ns,
        False,
        logger,
        requested_model=model,
    )


def _wrap_create(original: Callable, logger: Any):
    # Every parameter is keyword-only and ``create`` is wrapped in
    # ``@required_args``, which inspects the call — so this forwards verbatim
    # and never re-declares the signature.
    @functools.wraps(original)
    def create(self, *args, **kwargs):
        if not _watching(logger):
            return original(self, *args, **kwargs)

        start_time_ns = now_ns()
        try:
            result = original(self, *args, **kwargs)
        except BaseException as exc:
            # The failure channel: a call that raised is a call that happened.
            # Recorded with zero tokens and the error, then re-raised.
            _record(
                None, _requested_model(kwargs), start_time_ns, now_ns(),
                False, logger, error=exc,
            )
            raise
        end_time_ns = now_ns()

        try:
            _capture(result, kwargs, start_time_ns, end_time_ns, _watch_stream, logger)
        except Exception:
            logger.debug("agentsight: anthropic capture failed", exc_info=True)
        return result

    return create


def _wrap_async_create(original: Callable, logger: Any):
    @functools.wraps(original)
    async def create(self, *args, **kwargs):
        if not _watching(logger):
            return await original(self, *args, **kwargs)

        start_time_ns = now_ns()
        try:
            result = await original(self, *args, **kwargs)
        except BaseException as exc:
            _record(
                None, _requested_model(kwargs), start_time_ns, now_ns(),
                False, logger, error=exc,
            )
            raise
        end_time_ns = now_ns()

        try:
            _capture(
                result, kwargs, start_time_ns, end_time_ns, _watch_async_stream, logger
            )
        except Exception:
            logger.debug("agentsight: anthropic capture failed", exc_info=True)
        return result

    return create


def _wrap_stream_method(original: Callable, logger: Any):
    """Stash the requested model on the manager ``.stream()`` returns.

    The manager holds the request privately, so by ``__enter__`` the kwargs
    are out of reach — but a stream that dies before ``message_start`` has no
    other model name, and the accounting row it becomes would say NULL where
    the caller plainly wrote one. ``.stream()`` is the last moment the name
    is visible; the attribute carries it across.
    """

    @functools.wraps(original)
    def stream(self, *args, **kwargs):
        manager = original(self, *args, **kwargs)
        try:
            manager._agentsight_requested_model = _requested_model(kwargs)
        except Exception:
            logger.debug("agentsight: could not stash requested model", exc_info=True)
        return manager

    return stream


def _wrap_manager_enter(original: Callable, logger: Any):
    """``.stream()`` builds the request but does not send it; ``__enter__`` does.

    So this is both the honest start of the call and the first moment the
    ``MessageStream`` — and the raw stream underneath it — exists. The model
    starts as the requested id stashed by ``_wrap_stream_method`` and is
    replaced by the resolved id from ``message_start`` when one arrives.

    The close hook goes on the ``MessageStream`` as well as on the raw stream
    beneath it, because ``__exit__`` closes the wrapper and the wrapper releases
    the HTTP response rather than the raw stream. Hooking both means the span
    lands on whichever one the release actually routes through; the recorder
    only fires once either way.
    """

    @functools.wraps(original)
    def __enter__(self):
        if not _watching(logger):
            return original(self)

        model = getattr(self, "_agentsight_requested_model", None)
        start_time_ns = now_ns()
        try:
            stream = original(self)
        except BaseException as exc:
            # The request fires in __enter__, so this is where a failed
            # .stream() call surfaces.
            _record(None, model, start_time_ns, now_ns(), True, logger, error=exc)
            raise
        try:
            iterator = _watch_stream(
                getattr(stream, "_raw_stream", None),
                _StreamRecorder(model, start_time_ns, logger),
                logger,
            )
            if iterator is not None:
                _end_on_close(stream, iterator.close, logger)
        except Exception:
            logger.debug("agentsight: anthropic capture failed", exc_info=True)
        return stream

    return __enter__


def _wrap_async_manager_enter(original: Callable, logger: Any):
    @functools.wraps(original)
    async def __aenter__(self):
        if not _watching(logger):
            return await original(self)

        model = getattr(self, "_agentsight_requested_model", None)
        start_time_ns = now_ns()
        try:
            stream = await original(self)
        except BaseException as exc:
            _record(None, model, start_time_ns, now_ns(), True, logger, error=exc)
            raise
        try:
            iterator = _watch_async_stream(
                getattr(stream, "_raw_stream", None),
                _StreamRecorder(model, start_time_ns, logger),
                logger,
            )
            if iterator is not None:
                _end_on_close_async(stream, iterator.aclose, logger)
        except Exception:
            logger.debug("agentsight: anthropic capture failed", exc_info=True)
        return stream

    return __aenter__


# ---------------------------------------------------------------------------
# Install
# ---------------------------------------------------------------------------


def _patch(owner: Any, name: str, build: Callable[[Callable], Callable]) -> None:
    """Per-callable, so a release that drops one method still gets the rest.

    ``already_patched`` is what makes a second ``init()`` a no-op rather than a
    patch stacked on a patch, which would double every token count.
    """
    original = getattr(owner, name, None)
    if original is None or already_patched(original):
        return
    setattr(owner, name, mark_patched(build(original), original))


def install_anthropic(logger: Any) -> None:
    """Patch every Anthropic surface that reports token usage.

    Raises when ``anthropic`` is not installed; the registry logs that and moves
    on to the next target.
    """
    from anthropic.lib.streaming import AsyncMessageStreamManager, MessageStreamManager
    from anthropic.resources.messages import AsyncMessages, Messages

    def patch_messages(sync_cls, async_cls):
        for name in ("create", "parse"):
            _patch(sync_cls, name, lambda fn: _wrap_create(fn, logger))
            _patch(async_cls, name, lambda fn: _wrap_async_create(fn, logger))
        # ``stream`` returns a manager synchronously on both surfaces; the
        # wrapper only stashes the requested model for the manager's enter.
        _patch(sync_cls, "stream", lambda fn: _wrap_stream_method(fn, logger))
        _patch(async_cls, "stream", lambda fn: _wrap_stream_method(fn, logger))

    def patch_managers(sync_cls, async_cls):
        _patch(sync_cls, "__enter__", lambda fn: _wrap_manager_enter(fn, logger))
        _patch(async_cls, "__aenter__", lambda fn: _wrap_async_manager_enter(fn, logger))

    patch_messages(Messages, AsyncMessages)
    patch_managers(MessageStreamManager, AsyncMessageStreamManager)

    try:
        from anthropic.lib.streaming import (
            BetaAsyncMessageStreamManager,
            BetaMessageStreamManager,
        )
        from anthropic.resources.beta.messages import (
            AsyncMessages as AsyncBetaMessages,
        )
        from anthropic.resources.beta.messages import Messages as BetaMessages
    except ImportError:
        # Predates the beta resource. Everything above still applies.
        return

    patch_messages(BetaMessages, AsyncBetaMessages)
    patch_managers(BetaMessageStreamManager, BetaAsyncMessageStreamManager)
