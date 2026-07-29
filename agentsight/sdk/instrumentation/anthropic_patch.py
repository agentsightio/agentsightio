"""Token capture for the ``anthropic`` SDK.

Patched on the resource *classes*, like the OpenAI patch and for the same
reason: ``AnthropicVertex``, ``AnthropicBedrock``, ``AnthropicAWS`` and
``AnthropicFoundry`` all build the very same ``Messages``/``AsyncMessages``, so
one class patch covers every platform. (Their model ids are platform-flavoured
— ``anthropic.claude-...-v2:0`` on Bedrock, ``claude-...@20240229`` on Vertex —
so ``lookup_price`` misses them and the cost comes back ``None``. Tokens are
still exact.)

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


def _record(
    usage: Any,
    model: Optional[str],
    start_time_ns: int,
    end_time_ns: int,
    streaming: bool,
    logger: Any,
) -> None:
    """Emit one ``llm`` span. Never raises into the caller."""
    try:
        record_llm_call(
            **from_anthropic(usage, model),
            operation="chat",
            start_time_ns=start_time_ns,
            end_time_ns=end_time_ns,
            extra={LLMAttributes.STREAMING: True} if streaming else None,
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
        self._start_time_ns = start_time_ns
        self._logger = logger
        self._usage: Dict[str, int] = {}
        self._finished = False

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

    def finish(self) -> None:
        # A stream can reach its end more than once — closed by the user, closed
        # again by the manager's ``__exit__``, then collected — and a second
        # span here would double the tokens.
        if self._finished:
            return
        self._finished = True
        _record(
            self._usage, self._model, self._start_time_ns, now_ns(), True, self._logger
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
    or it is a ``with_raw_response`` APIResponse — whose body the user has not
    read yet, and reading it here would consume it — or a stream from a release
    that renamed the attribute. The last two record nothing at all rather than
    zero: a span reporting no tokens would be indistinguishable from a real
    call that cost nothing.
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
        finally:
            # Runs on exhaustion, on an exception, and on the close() that
            # abandoning the stream triggers — recording what was seen beats
            # recording nothing.
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
    ``Omit`` sentinel and is absent from ``parse`` altogether.
    """
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
        result = original(self, *args, **kwargs)
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
        result = await original(self, *args, **kwargs)
        end_time_ns = now_ns()

        try:
            _capture(
                result, kwargs, start_time_ns, end_time_ns, _watch_async_stream, logger
            )
        except Exception:
            logger.debug("agentsight: anthropic capture failed", exc_info=True)
        return result

    return create


def _wrap_manager_enter(original: Callable, logger: Any):
    """``.stream()`` builds the request but does not send it; ``__enter__`` does.

    So this is both the honest start of the call and the first moment the
    ``MessageStream`` — and the raw stream underneath it — exists. The model
    comes from ``message_start``, which is the resolved id anyway.

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

        start_time_ns = now_ns()
        stream = original(self)
        try:
            iterator = _watch_stream(
                getattr(stream, "_raw_stream", None),
                _StreamRecorder(None, start_time_ns, logger),
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

        start_time_ns = now_ns()
        stream = await original(self)
        try:
            iterator = _watch_async_stream(
                getattr(stream, "_raw_stream", None),
                _StreamRecorder(None, start_time_ns, logger),
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
