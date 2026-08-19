"""Token capture for the ``openai`` SDK.

The patch goes on the resource *classes*, not on a client instance, because one
class patch covers every route to the same method: ``client.chat``,
``client.beta.chat`` (literally the same class object), the module-level
``openai.chat`` proxy, and ``AzureOpenAI``, which subclasses ``OpenAI`` and
reuses its resources. Patching them by name instead would stack two wrappers on
one method and double every token count.

``.parse()`` is patched separately and deliberately. It does not route through
``create`` — it posts to ``/chat/completions`` itself with a ``post_parser``
attached — so a patch on ``create`` alone would miss every structured-output
call, which in an agent codebase is often the majority of them. ``.stream()``
needs no patch: it builds its request through ``create``.
"""

import functools
import inspect
import weakref
from typing import Any, Callable, Dict, NamedTuple, Optional, Tuple

from agentsight.sdk import context as ags_context
from agentsight.sdk.instrumentation.base import (
    already_patched,
    capturing,
    from_openai,
    mark_patched,
    now_ns,
    record_llm_call,
)
from agentsight.sdk.semconv import LLMAttributes

#: Set by ``with_raw_response`` / ``with_streaming_response`` before they call
#: the very same ``create`` we patched.
_RAW_RESPONSE_HEADER = "X-Stainless-Raw-Response"

#: Whether we are still able to take back the chunk we ask for. Asking for the
#: usage chunk and then failing to swallow it is the one failure in this file
#: that can break a user's loop, so the answer is settled from the stream
#: classes at install time — before any request — and cleared again if a live
#: stream still surprises us. When it is false, streamed calls report zero
#: tokens, which is the correct thing to lose.
_INJECTION_SAFE = True

#: Said once, at WARNING, whenever the latch above closes. Streamed calls keep
#: their span, their duration and their errors; what they lose is the token
#: counts, and a silent loss of those is a bill that stops being explainable.
_INTERNALS_CHANGED = (
    "agentsight: this openai release does not expose the stream internals the "
    "SDK reads, so streamed calls will report no token usage. Their spans, "
    "durations and errors are unaffected, as is every non-streamed call. "
    "Upgrading agentsight is the fix; please report it if there is not one yet."
)


# ---------------------------------------------------------------------------
# Where the usage lives, per endpoint family
# ---------------------------------------------------------------------------


def _chunk_usage(item: Any) -> Optional[Tuple[Any, Optional[str]]]:
    """Chat and legacy completions report on the chunk itself.

    Keyed on ``usage is not None`` rather than on empty ``choices``: an
    empty-choices chunk with no usage is representable, and ``n > 1`` does not
    change the shape.
    """
    usage = getattr(item, "usage", None)
    if usage is None:
        return None
    return usage, getattr(item, "model", None)


def _event_usage(item: Any) -> Optional[Tuple[Any, Optional[str]]]:
    """Responses streams carry usage on the terminal event's response object.

    ``response.completed``, ``response.incomplete`` and ``response.failed`` all
    carry one; every earlier event carries a response with ``usage`` unset, so
    matching on the usage rather than on the event type covers all three
    without a list that goes stale when a fourth is added.
    """
    response = getattr(item, "response", None)
    usage = getattr(response, "usage", None)
    if usage is None:
        return None
    return usage, getattr(response, "model", None)


class _Surface(NamedTuple):
    """What differs between the endpoint families. Everything else is shared."""

    operation: str
    extract: Callable[[Any], Optional[Tuple[Any, Optional[str]]]]
    #: Whether ``stream_options={"include_usage": True}`` exists here. The
    #: Responses API has no such knob — usage rides the terminal event and
    #: arrives whether or not anyone asked for it.
    injectable: bool


_CHAT = _Surface("chat", _chunk_usage, True)
_TEXT = _Surface("text_completion", _chunk_usage, True)
_RESPONSES = _Surface("chat", _event_usage, False)


# ---------------------------------------------------------------------------
# Emitting
# ---------------------------------------------------------------------------


def _record_usage(
    usage: Any,
    model: Optional[str],
    operation: str,
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
                # The stream closed and the provider never said what it
                # billed. The 0/0 counts on this span are unknowns, not
                # zeros — mark it so ingest can tell the difference.
                extra[LLMAttributes.USAGE_REPORTED] = False
        record_llm_call(
            **from_openai(usage, model),
            operation=operation,
            requested_model=requested_model,
            model_hint=model_hint,
            start_time_ns=start_time_ns,
            end_time_ns=end_time_ns,
            extra=extra or None,
            error=error,
        )
    except Exception:
        logger.debug("agentsight: openai span failed", exc_info=True)


def _record_embeddings(
    result: Any,
    model: Optional[str],
    start_time_ns: int,
    end_time_ns: int,
    logger: Any,
    error: Optional[BaseException] = None,
) -> None:
    """Embedding tokens are their own billable line with their own price.

    Deliberately not routed through ``from_openai()``: that would file
    ``prompt_tokens`` as chat input and price them at chat rates.
    """
    try:
        usage = getattr(result, "usage", None)
        record_llm_call(
            "openai",
            getattr(result, "model", None) or model,
            embedding_tokens=getattr(usage, "prompt_tokens", 0) or 0,
            operation="embeddings",
            requested_model=model,
            start_time_ns=start_time_ns,
            end_time_ns=end_time_ns,
            error=error,
        )
    except Exception:
        logger.debug("agentsight: openai embeddings span failed", exc_info=True)


class _StreamRecorder:
    """Holds a streamed call open until the stream ends, however it ends.

    The span cannot be emitted when ``create`` returns: at that point nothing
    has been generated yet, and a span covering only the HTTP handshake answers
    none of the questions duration is there to answer.
    """

    def __init__(
        self,
        surface: _Surface,
        model: Optional[str],
        start_time_ns: int,
        logger: Any,
    ):
        self._surface = surface
        self._model = model
        #: Kept separately because ``_model`` is overwritten by the resolved id
        #: as soon as a chunk carries one. Without a second slot the alias the
        #: caller typed is lost on every streamed call, which is most of an
        #: agent's traffic.
        self._requested_model = model
        #: Snapshotted here because __init__ runs while ``create`` does — the
        #: last moment the caller's ``model_hint`` block is known to be open.
        #: ``finish`` runs when the stream drains, which with ``wrap()`` can be
        #: after that block exits.
        self._model_hint = ags_context.current_model_hint()
        self._start_time_ns = start_time_ns
        self._logger = logger
        self._usage: Any = None
        self._finished = False
        self._error: Optional[BaseException] = None

    def capture(self, item: Any) -> bool:
        """Read the usage off ``item``. True when it carried nothing else.

        Only a chunk with no ``choices`` is ours to drop. Azure, vLLM, LiteLLM
        and the other OpenAI-compatible servers attach usage to the last
        *content* chunk instead of appending a usage-only one, and some send it
        on every chunk; swallowing those deletes the user's answer, which is a
        far worse failure than missing tokens.
        """
        try:
            found = self._surface.extract(item)
            if found is None:
                return False
            # The report is the whole-request total, not a delta: the last one
            # seen replaces the previous, it never accumulates.
            self._usage, model = found
            if model:
                self._model = model
            return not getattr(item, "choices", None)
        except Exception:
            self._logger.debug("agentsight: openai usage read failed", exc_info=True)
            return False

    def fail(self, error: BaseException) -> None:
        """Remember why the stream died, so the span says so.

        Only provider/transport failures land here — a consumer walking away
        (``GeneratorExit``) is not the call failing, and marking disconnects
        as errors would pollute an error-rate metric with user behaviour.
        """
        self._error = error

    def finish(self) -> None:
        # A stream can reach its end more than once — exhausted, then closed,
        # then collected — and a second span here would double the tokens.
        if self._finished:
            return
        self._finished = True
        _record_usage(
            self._usage,
            self._model,
            self._surface.operation,
            self._start_time_ns,
            now_ns(),
            True,
            self._logger,
            error=self._error,
            requested_model=self._requested_model,
            model_hint=self._model_hint,
        )


# ---------------------------------------------------------------------------
# Streaming
# ---------------------------------------------------------------------------


def _inject_usage_option(kwargs: dict) -> bool:
    """Ask for the usage the caller forgot to ask for. Returns whether we did.

    A streamed call reports no usage at all unless
    ``stream_options={"include_usage": True}`` is set, so without this a
    streaming agent has no token counts and no costs. But the option is not
    free: the provider then appends a final chunk with ``usage`` set and
    ``choices == []``, and the loop everyone writes —
    ``for chunk in stream: print(chunk.choices[0].delta.content)`` — raises
    IndexError on it.

    So the injection is only half of the bargain. Whoever injects must also
    swallow that chunk on the way out, which is what ``swallow`` does in
    :func:`_watch_stream`. When the caller set the option themselves the whole
    stream passes through untouched and we simply read the usage as it goes by.

    ``NOT_GIVEN`` is falsy, so both ``stream`` and ``stream_options`` can be
    tested for truth directly.
    """
    if not _INJECTION_SAFE or not kwargs.get("stream"):
        return False
    if kwargs.get("stream_options"):
        return False
    kwargs["stream_options"] = {"include_usage": True}
    return True


def _iterator_of(stream: Any, logger: Any) -> Any:
    """The single choke point every way of consuming a stream funnels through.

    ``Stream.__next__`` and ``Stream.__iter__`` both read ``_iterator``, as do
    ``AsyncStream.__anext__`` and ``__aiter__``, so replacing it instruments
    every consumption style at once while leaving the object's identity, its
    type, ``.response``, ``.close()`` and its context-manager behaviour exactly
    as the user found them.

    A proxy object was the alternative and it is not safe here: the SDK's own
    ``.stream()`` helpers reach past the public surface into
    ``raw_stream.response`` and iterate the raw object directly, and user code
    is entitled to ``isinstance(chunk_source, Stream)``. A proxy would have to
    impersonate the entire class and would still fail that check.

    ``None`` when the attribute is gone — a future release could rename it, and
    finding that out must cost telemetry, not the user's program.
    """
    global _INJECTION_SAFE

    source = getattr(stream, "_iterator", None)
    if source is None and _INJECTION_SAFE:
        # The latch is one-way, so this branch is the transition and the
        # warning is therefore once per process. It is a warning rather than a
        # debug line because the symptom — every streamed call reporting zero
        # tokens — is otherwise indistinguishable from an agent that stopped
        # making calls, and nothing else in the process will ever mention it.
        _INJECTION_SAFE = False
        logger.warning(_INTERNALS_CHANGED)
    return source


def _watch_stream(
    stream: Any, recorder: _StreamRecorder, swallow: bool, logger: Any
) -> None:
    source = _iterator_of(stream, logger)
    if source is None:
        recorder.finish()
        return

    def instrumented():
        try:
            for item in source:
                if recorder.capture(item) and swallow:
                    continue
                yield item
        except GeneratorExit:
            # The consumer walked away; the call itself did not fail.
            raise
        except BaseException as exc:
            recorder.fail(exc)
            raise
        finally:
            # Runs on exhaustion, on an exception, and on close() — recording
            # whatever usage was seen beats recording nothing, and a stream
            # that died raising goes out marked as the failure it was.
            recorder.finish()

    iterator = instrumented()
    stream._iterator = iterator
    _end_on_close(stream, iterator.close, logger)


def _watch_async_stream(
    stream: Any, recorder: _StreamRecorder, swallow: bool, logger: Any
) -> None:
    source = _iterator_of(stream, logger)
    if source is None:
        recorder.finish()
        return

    async def instrumented():
        try:
            async for item in source:
                if recorder.capture(item) and swallow:
                    continue
                yield item
        except GeneratorExit:
            raise
        except BaseException as exc:
            recorder.fail(exc)
            raise
        finally:
            recorder.finish()

    iterator = instrumented()
    stream._iterator = iterator
    _end_on_close_async(stream, iterator.aclose, logger)


def _end_on_close(stream: Any, close_iterator: Callable, logger: Any) -> None:
    """Make ``close()`` the deterministic end of a half-read stream.

    Abandoning a stream leaves the wrapper generator suspended, and nothing runs
    its ``finally`` until the collector gets to it. Sync generators are usually
    reclaimed by refcount straight away, but ``async`` ones are finalized by a
    task the loop schedules — typically while it is already shutting down, with
    the conversation contextvar long gone — so the tokens are simply lost. An
    instance attribute rather than a class patch: this is scoped to the streams
    we instrumented, and leaves ``isinstance``, ``.response`` and everything
    else on the class alone.

    The stream is held weakly and the original taken off the *class* rather
    than the instance, so the replacement does not close over the stream's own
    bound method. That would put the stream in a reference cycle, and a stream
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
            logger.debug("agentsight: openai stream close failed", exc_info=True)
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
            logger.debug("agentsight: openai stream close failed", exc_info=True)
        return await original(ref(), *args, **kwargs)

    stream.close = close


# ---------------------------------------------------------------------------
# Wrappers
# ---------------------------------------------------------------------------


def _raw_marker(kwargs: dict) -> Optional[str]:
    """``"true"`` for ``with_raw_response``, ``"stream"`` for
    ``with_streaming_response``, ``None`` for an ordinary call.

    The provider sets the same header for both wrappers and distinguishes them
    by value, which matters here because the two are not equally safe to look
    at (see :func:`_deferred_body`).
    """
    return (kwargs.get("extra_headers") or {}).get(_RAW_RESPONSE_HEADER)


def _deferred_body(kwargs: dict) -> bool:
    """Whether the response body is one we must not touch.

    Only ``with_streaming_response`` qualifies. It hands back a body whose
    reading belongs to the user — its ``parse()`` reads a JSON body whole,
    eagerly, which is the exact thing that wrapper exists to let them avoid —
    and injecting ``stream_options`` into a stream we never get to instrument
    would leak the usage chunk into their loop. Those we leave alone entirely,
    and they are the one raw surface still invisible to telemetry.

    ``with_raw_response`` is not deferred, ``stream=True`` included. A
    non-streaming body is already in memory by the time we see it, and on a
    streamed request ``parse()`` reads no bytes — it builds the lazy ``Stream``
    over the unread response, memoised, so the caller's own ``parse()``
    returns the identical object with our instrumentation already on it.
    Treating either as untouchable was silent and expensive —
    ``langchain-openai`` routes every chat call through ``with_raw_response``,
    streamed ones too when ``include_response_headers=True``, and the
    LangChain handler stands down on LLM spans for a provider this patch is
    supposed to cover, so those calls recorded neither. No span, no tokens, no
    cost, no error: exactly the invisible loss the failure channel exists to
    prevent.
    """
    return _raw_marker(kwargs) == "stream"


def _unwrap_raw(result: Any, kwargs: dict, logger: Any) -> Any:
    """The parsed body behind a ``with_raw_response`` result.

    ``parse()`` memoises, so the caller's own ``parse()`` returns the identical
    object afterwards — this is a read, not a consumption. ``"raw"`` is the
    successor wrapper generation's spelling of ``"true"``, with the same
    ``parse()`` contract; unused by the resources today, accepted now so a
    release that migrates does not silently reopen this hole. Anything
    unexpected leaves the result untouched and costs only the usage numbers.
    """
    if _raw_marker(kwargs) not in ("true", "raw"):
        return result
    try:
        return result.parse()
    except Exception:
        logger.debug("agentsight: could not read raw response body", exc_info=True)
        return result


def _requested_model(kwargs: dict) -> Optional[str]:
    """``model`` is optional on the Responses API — a call using a stored
    ``prompt=`` omits it, leaving ``NOT_GIVEN`` behind."""
    model = kwargs.get("model")
    return model if isinstance(model, str) else None


def _wrap_create(original: Callable, surface: _Surface, stream_type, logger: Any):
    @functools.wraps(original)
    def create(self, *args, **kwargs):
        try:
            watching = capturing() and not _deferred_body(kwargs)
            injected = watching and surface.injectable and _inject_usage_option(kwargs)
        except Exception:
            logger.debug("agentsight: openai pre-call capture failed", exc_info=True)
            watching = injected = False

        if not watching:
            return original(self, *args, **kwargs)

        start_time_ns = now_ns()
        try:
            result = original(self, *args, **kwargs)
        except BaseException as exc:
            # The failure channel: a call that raised is a call that happened.
            # Recorded with zero tokens and the error, then re-raised — the
            # span must never eat the user's exception.
            _record_usage(
                None,
                _requested_model(kwargs),
                surface.operation,
                start_time_ns,
                now_ns(),
                False,
                logger,
                error=exc,
            )
            raise
        end_time_ns = now_ns()

        try:
            model = _requested_model(kwargs)
            # Unwrapped before the dispatch, not inside the non-stream branch:
            # a raw-wrapped stream is a Stream in an APIResponse coat, and
            # dispatching on the coat would send it below — a "blocking" span
            # with zero tokens for a call that streamed.
            body = _unwrap_raw(result, kwargs, logger)
            if isinstance(body, stream_type):
                recorder = _StreamRecorder(surface, model, start_time_ns, logger)
                _watch_stream(body, recorder, injected, logger)
            else:
                _record_usage(
                    getattr(body, "usage", None),
                    getattr(body, "model", None) or model,
                    surface.operation,
                    start_time_ns,
                    end_time_ns,
                    False,
                    logger,
                    requested_model=model,
                )
        except Exception:
            logger.debug("agentsight: openai capture failed", exc_info=True)
        return result

    return create


def _wrap_async_create(original: Callable, surface: _Surface, stream_type, logger: Any):
    # A real coroutine function, not a wrapper returning one:
    # ``AsyncCompletions.stream()`` is a plain ``def`` that calls ``create()``
    # eagerly and awaits the coroutine later, so the body — and with it
    # start_time_ns — has to run at await time.
    @functools.wraps(original)
    async def create(self, *args, **kwargs):
        try:
            watching = capturing() and not _deferred_body(kwargs)
            injected = watching and surface.injectable and _inject_usage_option(kwargs)
        except Exception:
            logger.debug("agentsight: openai pre-call capture failed", exc_info=True)
            watching = injected = False

        if not watching:
            return await original(self, *args, **kwargs)

        start_time_ns = now_ns()
        try:
            result = await original(self, *args, **kwargs)
        except BaseException as exc:
            _record_usage(
                None,
                _requested_model(kwargs),
                surface.operation,
                start_time_ns,
                now_ns(),
                False,
                logger,
                error=exc,
            )
            raise
        end_time_ns = now_ns()

        try:
            model = _requested_model(kwargs)
            body = _unwrap_raw(result, kwargs, logger)
            if isinstance(body, stream_type):
                recorder = _StreamRecorder(surface, model, start_time_ns, logger)
                _watch_async_stream(body, recorder, injected, logger)
            else:
                _record_usage(
                    getattr(body, "usage", None),
                    getattr(body, "model", None) or model,
                    surface.operation,
                    start_time_ns,
                    end_time_ns,
                    False,
                    logger,
                    requested_model=model,
                )
        except Exception:
            logger.debug("agentsight: openai capture failed", exc_info=True)
        return result

    return create


def _wrap_embeddings(original: Callable, logger: Any):
    @functools.wraps(original)
    def create(self, *args, **kwargs):
        try:
            watching = capturing() and not _deferred_body(kwargs)
        except Exception:
            logger.debug("agentsight: openai pre-call capture failed", exc_info=True)
            watching = False

        if not watching:
            return original(self, *args, **kwargs)

        start_time_ns = now_ns()
        try:
            result = original(self, *args, **kwargs)
        except BaseException as exc:
            _record_embeddings(
                None, _requested_model(kwargs), start_time_ns, now_ns(), logger,
                error=exc,
            )
            raise
        _record_embeddings(
            _unwrap_raw(result, kwargs, logger),
            _requested_model(kwargs), start_time_ns, now_ns(), logger,
        )
        return result

    return create


def _wrap_async_embeddings(original: Callable, logger: Any):
    @functools.wraps(original)
    async def create(self, *args, **kwargs):
        try:
            watching = capturing() and not _deferred_body(kwargs)
        except Exception:
            logger.debug("agentsight: openai pre-call capture failed", exc_info=True)
            watching = False

        if not watching:
            return await original(self, *args, **kwargs)

        start_time_ns = now_ns()
        try:
            result = await original(self, *args, **kwargs)
        except BaseException as exc:
            _record_embeddings(
                None, _requested_model(kwargs), start_time_ns, now_ns(), logger,
                error=exc,
            )
            raise
        _record_embeddings(
            _unwrap_raw(result, kwargs, logger),
            _requested_model(kwargs), start_time_ns, now_ns(), logger,
        )
        return result

    return create


# ---------------------------------------------------------------------------
# Install
# ---------------------------------------------------------------------------


def _injection_is_safe(sync_stream: Any, async_stream: Any) -> bool:
    """Whether this openai release still lets us take back what we ask for.

    Both stream classes read every item through ``_iterator``, which is the
    attribute :func:`_iterator_of` replaces. If a release stops doing that there
    is nothing to replace, so the usage chunk we asked for would arrive in the
    user's loop and ``chunk.choices[0]`` would raise IndexError. Answering that
    from the class costs nothing and answers it *before* the first request;
    answering it from the first live stream costs someone a broken loop.

    A method with no ``__code__`` — reimplemented in C, wrapped by a decorator
    we do not recognise — is trusted rather than assumed broken, because the
    cost of a false negative here is every streamed token in the process.
    """
    for owner, method in ((sync_stream, "__next__"), (async_stream, "__anext__")):
        code = getattr(getattr(owner, method, None), "__code__", None)
        if code is not None and "_iterator" not in code.co_names:
            return False
    return True


def _patch(owner: Any, name: str, build: Callable[[Callable], Callable]) -> None:
    original = getattr(owner, name, None)
    if original is None or already_patched(original):
        return
    setattr(owner, name, mark_patched(build(original), original))


def install_openai(logger: Any) -> None:
    """Patch every OpenAI surface that reports token usage.

    Raises when ``openai`` is not installed; the registry logs that and moves
    on to the next target.
    """
    global _INJECTION_SAFE

    from openai import AsyncStream, Stream
    from openai.resources.chat.completions import AsyncCompletions, Completions

    # Same name, different class: legacy text completions, not chat.
    from openai.resources.completions import AsyncCompletions as AsyncTextCompletions
    from openai.resources.completions import Completions as TextCompletions
    from openai.resources.embeddings import AsyncEmbeddings, Embeddings

    _INJECTION_SAFE = _injection_is_safe(Stream, AsyncStream)
    if not _INJECTION_SAFE:
        # Install runs once per process, so this is a one-shot too. Said here
        # as well as at the runtime latch because this is the earlier and more
        # useful moment: before the first request, while somebody is still
        # watching the startup logs.
        logger.warning(_INTERNALS_CHANGED)

    def patch_sync(owner, name, surface):
        _patch(owner, name, lambda fn: _wrap_create(fn, surface, Stream, logger))

    def patch_async(owner, name, surface):
        _patch(
            owner, name, lambda fn: _wrap_async_create(fn, surface, AsyncStream, logger)
        )

    patch_sync(Completions, "create", _CHAT)
    patch_sync(Completions, "parse", _CHAT)
    patch_async(AsyncCompletions, "create", _CHAT)
    patch_async(AsyncCompletions, "parse", _CHAT)

    patch_sync(TextCompletions, "create", _TEXT)
    patch_async(AsyncTextCompletions, "create", _TEXT)

    _patch(Embeddings, "create", lambda fn: _wrap_embeddings(fn, logger))
    _patch(AsyncEmbeddings, "create", lambda fn: _wrap_async_embeddings(fn, logger))

    try:
        from openai.resources.responses import AsyncResponses, Responses
    except ImportError:
        # Predates the Responses API. Everything above still applies.
        return

    patch_sync(Responses, "create", _RESPONSES)
    patch_sync(Responses, "parse", _RESPONSES)
    patch_async(AsyncResponses, "create", _RESPONSES)
    patch_async(AsyncResponses, "parse", _RESPONSES)
