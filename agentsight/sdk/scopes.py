"""The two user-facing scopes: ``conversation()`` and ``turn()``.

Both work as a context manager *and* as a decorator, because real code needs
both: a decorator for a clean handler, a context manager when the id has to be
dug out of a payload first (which, in every production service reviewed, it
does).
"""

import asyncio
import functools
import inspect
import threading
import uuid
from typing import Any, Callable, Dict, Optional

from opentelemetry import context as otel_context
from opentelemetry import trace as otel_trace
from opentelemetry.trace import Status, StatusCode

from agentsight.sdk import context as ags_context
from agentsight.sdk.semconv import (
    ConversationAttributes,
    MessageAttributes,
    SpanAttributes,
    SpanKind,
    TurnAttributes,
)
from agentsight.sdk.serialization import first_string_argument, bind_arguments, to_json, to_text

_logger = None


def _log():
    global _logger
    if _logger is None:
        from agentsight.sdk.core import logger

        _logger = logger
    return _logger


def generate_conversation_id() -> str:
    """Used when the caller supplies none.

    Required by product: every span must carry a conversation id, and a
    missing one is generated rather than rejected — losing the data would be
    worse than a synthetic id.
    """
    return f"conv_{uuid.uuid4().hex[:12]}"


# ---------------------------------------------------------------------------
# conversation
# ---------------------------------------------------------------------------


class ConversationScope:
    """Ambient conversation identity plus the metadata behind the charts.

    Produces no span of its own. A conversation outlives any single process,
    so there is nothing for a span to bracket; instead every span inside
    inherits these attributes and the exporter groups by them.
    """

    def __init__(
        self,
        conversation_id: Optional[str] = None,
        *,
        customer_id: Optional[str] = None,
        customer_ip_address: Optional[str] = None,
        device: Optional[str] = None,
        source: Optional[str] = None,
        language: Optional[str] = None,
        name: Optional[str] = None,
        environment: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        enabled: bool = True,
    ):
        self.conversation_id = conversation_id or generate_conversation_id()
        self.enabled = enabled
        self._token = None

        attributes: Dict[str, Any] = {
            ConversationAttributes.ID: self.conversation_id,
        }
        supplied = {
            "customer_id": customer_id,
            "customer_ip_address": customer_ip_address,
            "device": device,
            "source": source,
            "language": language,
            "name": name,
            "environment": environment,
        }
        for kwarg, value in supplied.items():
            if value is not None:
                attributes[ConversationAttributes.BY_KWARG[kwarg]] = value
        if environment is None:
            # The deployment-wide default from init(environment=...) /
            # AGENTSIGHT_ENVIRONMENT. Per-conversation always wins — a
            # staging conversation inside a production process is the
            # caller's statement, not ours to override.
            from agentsight.sdk.core import default_environment

            fallback = default_environment()
            if fallback:
                attributes[ConversationAttributes.BY_KWARG["environment"]] = fallback
        if metadata:
            attributes[ConversationAttributes.METADATA] = to_json(metadata)

        self.attributes = attributes

    # -- context manager ----------------------------------------------------

    def __enter__(self) -> "ConversationScope":
        self._token = ags_context.set_conversation(self)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        if self._token is None:
            return False
        # Only unwind if this scope is still the active one. A streaming turn
        # closes its conversation from inside the consumer's context, which is
        # not the context that opened it — resetting there would clear whatever
        # conversation the consumer legitimately had.
        if ags_context.current_conversation() is self:
            ags_context.reset_conversation(self._token)
        self._token = None
        return False

    async def __aenter__(self) -> "ConversationScope":
        return self.__enter__()

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> bool:
        return self.__exit__(exc_type, exc_val, exc_tb)

    # -- decorator ----------------------------------------------------------

    def __call__(self, func: Callable) -> Callable:
        if asyncio.iscoroutinefunction(func):

            @functools.wraps(func)
            async def async_wrapper(*args, **kwargs):
                async with ConversationScope(
                    self.conversation_id, enabled=self.enabled
                ) as scope:
                    scope.attributes = dict(self.attributes)
                    return await func(*args, **kwargs)

            return async_wrapper

        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs):
            with ConversationScope(self.conversation_id, enabled=self.enabled) as scope:
                scope.attributes = dict(self.attributes)
                return func(*args, **kwargs)

        return sync_wrapper


# ---------------------------------------------------------------------------
# turn
# ---------------------------------------------------------------------------


class TurnScope:
    """One exchange. Grouping and latency — nothing else.

    A turn does not capture messages; you emit those. What it gives you is the
    span whose duration *is* the answer latency, and a parent for the tool and
    LLM spans that happen inside, so "how much of the wait was tools" is
    answerable without new instrumentation.

    A turn that does not finish is still exported — marked incomplete, with
    the reason — so ingest can keep it out of the transcript while the token
    spend stays recoverable (design §4.3). Completion is therefore tracked
    explicitly rather than inferred from the span ending.
    """

    def __init__(self, name: Optional[str] = None):
        self.name = name or "turn"
        self.span = None
        self._otel_token = None
        self._ctx_token = None
        self._complete = False
        self._deferred = False
        self._ended = False
        self._watchdog = None
        #: Guards the end-once transition. A deferred turn really can be raced:
        #: the watchdog fires on its own thread while the iterator is finishing
        #: on the consumer's, and ending a span twice corrupts the export.
        self._lock = threading.Lock()
        #: Captured at start() so a wrapped iterator can re-attach it while it
        #: drains — see _enter_step().
        self._conversation = None
        self.turn_id: Optional[str] = None

    # -- lifecycle ----------------------------------------------------------

    def start(self) -> "TurnScope":
        from agentsight.sdk.core import get_tracer, is_enabled

        if not is_enabled() or not ags_context.tracking_enabled():
            return self

        try:
            tracer = get_tracer()
            self._conversation = ags_context.current_conversation()
            attributes = dict(ags_context.conversation_attributes())
            attributes[SpanAttributes.KIND] = SpanKind.TURN
            attributes[SpanAttributes.ENTITY_NAME] = self.name

            self.span = tracer.start_span(self.name, attributes=attributes)
            # Tag the turn with its own span id so every descendant can carry
            # it; a ReadableSpan exposes only its immediate parent, so the
            # buffering processor cannot walk a chain at export time.
            self.turn_id = format(self.span.get_span_context().span_id, "016x")
            self.span.set_attribute(TurnAttributes.ID, self.turn_id)

            self._otel_token = otel_context.attach(
                otel_trace.set_span_in_context(self.span)
            )
            self._ctx_token = ags_context.set_turn(self)
        except Exception as exc:
            # §10: a turn that cannot be started is a turn that records
            # nothing. It is not a reason for the user's handler to fail.
            _log().debug("could not start turn span: %s", exc)
            self.span = None
        return self

    def finish(self, complete: bool = True, *, reason: Optional[str] = None) -> None:
        """End the span. ``complete=False`` marks the turn incomplete: it is
        exported anyway, and ingest archives it without projecting it into the
        transcript. ``reason`` says why (one of ``TurnAttributes.REASON_*``);
        when omitted on an incomplete turn it defaults to ``abandoned``, since
        every path that has an exception in hand passes ``error`` explicitly.

        Idempotent by design: a deferred turn can be raced by its iterator
        finishing and its watchdog firing, and whichever gets here first wins —
        including the reason, which is written only by the winner.
        """
        self._cancel_watchdog()
        with self._lock:
            if self._ended or self.span is None:
                already_done = True
            else:
                already_done = False
                self._ended = True
        if already_done:
            self._detach_context()
            return
        self._complete = complete
        try:
            self.span.set_attribute(TurnAttributes.COMPLETE, complete)
            if not complete:
                self.span.set_attribute(
                    TurnAttributes.INCOMPLETE_REASON,
                    reason or TurnAttributes.REASON_ABANDONED,
                )
            self.span.set_status(Status(StatusCode.OK if complete else StatusCode.ERROR))
            self.span.end()
        except Exception as exc:  # pragma: no cover - never reach user code
            _log().debug("failed to end turn span: %s", exc)
        finally:
            self._detach_context()

    def abandon(self) -> None:
        """Mark this turn unfinished: it will be archived but never projected.

        Needed because an application that detects its own client disconnect
        (``if await request.is_disconnected(): break``) then returns *normally* —
        from the SDK's side that is indistinguishable from success.

        No attribute is written here: only finish()'s winner may touch the
        span. A pre-write outside that lock could stamp ``complete=false``
        onto a turn another thread just finished as OK, producing the
        contradiction "incomplete, status OK, no reason" on the wire.
        """
        self._complete = False
        self._deferred = False
        self.finish(complete=False, reason=TurnAttributes.REASON_ABANDONED)

    def _record_failure(self, exc: BaseException) -> None:
        """Attach the exception to the span, if there is one to attach to."""
        if self.span is None or exc is None:
            return
        try:
            self.span.record_exception(exc)
        except Exception:
            pass

    def _cancel_watchdog(self) -> None:
        if self._watchdog is None:
            return
        from agentsight.sdk import watchdog

        watchdog.cancel(self._watchdog)
        self._watchdog = None

    def _detach_context(self) -> None:
        """Stop being the ambient turn, without ending the span.

        A deferred turn calls this when its ``with`` block exits: the span
        stays open because the work is still running, but leaving the turn
        attached would make the *next* thing that happens in this context —
        the next message off the queue, the next iteration of a loop — nest
        inside an exchange that has already been handed off.
        """
        if self._otel_token is not None:
            # Detaching a token in a context that did not create it makes OTel
            # log an error of its own, which no try/except of ours can stop.
            # If we are no longer current, the context that owns the token is
            # gone anyway and there is nothing to unwind.
            if otel_trace.get_current_span() is self.span:
                try:
                    otel_context.detach(self._otel_token)
                except Exception:
                    pass
            self._otel_token = None
        if self._ctx_token is not None:
            if ags_context.current_turn() is self:
                ags_context.reset_turn(self._ctx_token)
            self._ctx_token = None

    # -- messages -----------------------------------------------------------

    def add_message(
        self, sender: str, content: Any, metadata: Optional[Dict[str, Any]] = None
    ) -> None:
        if self.span is None:
            return
        attributes = {
            MessageAttributes.SENDER: sender,
            MessageAttributes.CONTENT: to_text(content),
        }
        if metadata:
            attributes[MessageAttributes.METADATA] = to_json(metadata)
        try:
            self.span.add_event(MessageAttributes.EVENT_NAME, attributes=attributes)
        except Exception as exc:  # pragma: no cover
            _log().debug("failed to add message event: %s", exc)

    def user_message(
        self, content: Any, metadata: Optional[Dict[str, Any]] = None
    ) -> None:
        """Attach a user message to *this* turn, wherever it is called from.

        The module-level :func:`agentsight.user_message` targets whichever turn
        is active on the current context, and opens one of its own when there
        is none. That is right almost always and wrong in exactly one place: a
        turn deferred by :meth:`keep_open` outlives its block, so the later
        callback that finishes it is no longer inside it, and the module-level
        call would quietly file the message under a turn of its own.
        """
        self.add_message(MessageAttributes.SENDER_USER, content, metadata)

    def agent_message(
        self, content: Any, metadata: Optional[Dict[str, Any]] = None
    ) -> None:
        """Attach an agent message to *this* turn. See :meth:`user_message`."""
        self.add_message(MessageAttributes.SENDER_AGENT, content, metadata)

    # -- lifetime binding ---------------------------------------------------

    def keep_open(self) -> "TurnScope":
        """Take the turn out of its block's hands. You must end it yourself.

        The escape hatch for work whose end is not an iterator, a future or an
        exception — a websocket exchange finished by a later callback, say.
        Pair it with :meth:`end` or :func:`agentsight.abandon_turn`; the
        watchdog closes the turn as incomplete if you never do.
        """
        self._deferred = True
        self._arm_watchdog()
        return self

    def end(self, complete: bool = True, *, reason: Optional[str] = None) -> None:
        """End a turn that was deferred by :meth:`keep_open` or :meth:`wrap`."""
        self.finish(complete=complete, reason=reason)

    def wrap(self, obj):
        """Bind this turn's lifetime to ``obj`` instead of to a block.

        The one primitive behind every case where a Python block and a unit of
        work disagree. A handler returns a streaming body, a generator, or a
        task; the framework drains or awaits it afterwards. Closing the span at
        the ``return`` would record ~0ms latency and no agent message —
        confidently wrong data, which is worse than none.

        Accepts, in order of how often it shows up:

        * a response object with a ``body_iterator`` (Starlette, FastAPI)
        * an async or sync generator / iterator
        * an ``asyncio.Task`` or ``Future``, or a ``concurrent.futures.Future``
        * any awaitable

        Anything else is returned untouched with the turn still open, which is
        the safe reading of an unrecognised object: better a turn closed late
        by the watchdog than a turn closed before its work happened.
        """
        if obj is None:
            return obj

        # Starlette wraps the real generator in a response object, so unwrap
        # one level and rebuild it rather than wrapping the response itself.
        if hasattr(obj, "body_iterator"):
            obj.body_iterator = self.wrap(obj.body_iterator)
            return obj

        self._deferred = True
        self._arm_watchdog()

        if inspect.isasyncgen(obj) or hasattr(obj, "__aiter__"):
            return self._wrap_async_iterator(obj)
        if hasattr(obj, "add_done_callback"):
            return self._wrap_future(obj)
        if inspect.isawaitable(obj):
            return self._wrap_awaitable(obj)
        if hasattr(obj, "__iter__") or hasattr(obj, "__next__"):
            return self._wrap_sync_iterator(obj)

        _log().debug("turn.wrap() got %r, which has no end to bind to", type(obj))
        return obj

    def _arm_watchdog(self) -> None:
        """A deferred turn that never ends can never be exported — OTel only
        exports ended spans — and its buffered children stay pinned in memory.
        The deadline bounds both."""
        if self.span is None or self._watchdog is not None:
            return
        from agentsight.sdk import watchdog
        from agentsight.sdk.core import get_turn_timeout_ms

        timeout = get_turn_timeout_ms()
        if timeout and timeout > 0:
            self._watchdog = watchdog.arm(timeout / 1000.0, self._expire)

    def _expire(self, deadline_expired: bool = True) -> None:
        """Watchdog callback. ``deadline_expired`` is False when the watchdog
        is being drained at process shutdown — the turn did not out-stay its
        deadline, the process is leaving, and the two deserve different
        reasons on the wire and different log levels here."""
        if self._ended:
            return
        if deadline_expired:
            _log().warning(
                "turn %s exceeded its deadline without ending; recording it as "
                "incomplete. Something wrapped by turn.wrap() was never drained.",
                self.turn_id,
            )
            self.finish(complete=False, reason=TurnAttributes.REASON_DEADLINE)
        else:
            self.finish(complete=False, reason=TurnAttributes.REASON_SHUTDOWN)

    # A wrapped iterator resumes in whoever is *consuming* it — a different
    # task, sometimes a different thread — and generators do not carry the
    # producer's context with them. Without re-attaching around each step, an
    # agent_message() emitted while the stream drains sees no conversation and
    # is silently dropped. Attach per step rather than once, so nothing leaks
    # into the consumer between chunks.

    def _enter_step(self):
        conversation_token = None
        if self._conversation is not None:
            if ags_context.current_conversation() is not self._conversation:
                conversation_token = ags_context.set_conversation(self._conversation)
        turn_token = None
        if ags_context.current_turn() is not self:
            turn_token = ags_context.set_turn(self)
        otel_token = None
        if self.span is not None:
            try:
                otel_token = otel_context.attach(
                    otel_trace.set_span_in_context(self.span)
                )
            except Exception:
                otel_token = None
        return conversation_token, turn_token, otel_token

    def _exit_step(self, tokens) -> None:
        conversation_token, turn_token, otel_token = tokens
        if otel_token is not None:
            try:
                otel_context.detach(otel_token)
            except Exception:
                pass
        if turn_token is not None:
            ags_context.reset_turn(turn_token)
        if conversation_token is not None:
            ags_context.reset_conversation(conversation_token)

    def _wrap_sync_iterator(self, iterator):
        def generator():
            source = iter(iterator)
            try:
                while True:
                    tokens = self._enter_step()
                    try:
                        item = next(source)
                    except StopIteration:
                        break
                    finally:
                        self._exit_step(tokens)
                    yield item
            except GeneratorExit:
                # The consumer walked away — a client disconnect, usually.
                # A partial answer is not an exchange; the turn goes out
                # marked abandoned so the transcript stays clean while the
                # tokens it burned stay on the books.
                self.finish(complete=False, reason=TurnAttributes.REASON_ABANDONED)
                raise
            except BaseException as exc:
                self._record_failure(exc)
                self.finish(complete=False, reason=TurnAttributes.REASON_ERROR)
                raise
            else:
                self.finish(complete=True)

        return generator()

    def _wrap_async_iterator(self, iterator):
        async def generator():
            source = iterator.__aiter__()
            try:
                while True:
                    tokens = self._enter_step()
                    try:
                        item = await source.__anext__()
                    except StopAsyncIteration:
                        break
                    finally:
                        self._exit_step(tokens)
                    yield item
            except (GeneratorExit, asyncio.CancelledError):
                # GeneratorExit is a sync consumer walking away;
                # CancelledError is the same event in async clothing — the
                # task draining this stream was cancelled. Neither is the
                # turn *failing*, and _wrap_future already maps a cancelled
                # future to abandoned; iteration must agree with it.
                self.finish(complete=False, reason=TurnAttributes.REASON_ABANDONED)
                raise
            except BaseException as exc:
                self._record_failure(exc)
                self.finish(complete=False, reason=TurnAttributes.REASON_ERROR)
                raise
            else:
                self.finish(complete=True)

        return generator()

    def _wrap_future(self, future):
        """``asyncio.Future``/``Task`` and ``concurrent.futures.Future`` both.

        Returned as-is: a future has an identity the caller may already hold or
        compare, so replacing it with a wrapper would be a visible change to
        their program. The callback is enough.
        """

        def done(completed):
            try:
                cancelled = completed.cancelled()
            except Exception:
                cancelled = False
            error = None
            if not cancelled:
                try:
                    error = completed.exception()
                except Exception as exc:
                    error = exc
            if error is not None:
                self._record_failure(error)
            # Cancelled and errored are different signals: a cancelled task is
            # the caller walking away, an exception is the work blowing up.
            if cancelled:
                self.finish(complete=False, reason=TurnAttributes.REASON_ABANDONED)
            elif error is not None:
                self.finish(complete=False, reason=TurnAttributes.REASON_ERROR)
            else:
                self.finish(complete=True)

        try:
            future.add_done_callback(done)
        except Exception as exc:
            _log().debug("could not bind turn to future: %s", exc)
            self.finish(complete=True)
        return future

    def _wrap_awaitable(self, awaitable):
        async def runner():
            tokens = self._enter_step()
            try:
                result = await awaitable
            except BaseException as exc:
                self._exit_step(tokens)
                self._record_failure(exc)
                self.finish(complete=False, reason=TurnAttributes.REASON_ERROR)
                raise
            self._exit_step(tokens)
            self.finish(complete=True)
            return result

        return runner()

    # -- context manager ----------------------------------------------------

    def __enter__(self) -> "TurnScope":
        return self.start()

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        if self._deferred and exc_type is None:
            # wrap() took ownership; whatever it bound to closes the span. The
            # block still gives up being the ambient turn on its way out.
            self._detach_context()
            return False
        if exc_type is not None:
            self._record_failure(exc_val)
            self.finish(complete=False, reason=TurnAttributes.REASON_ERROR)
        else:
            self.finish(complete=True)
        return False

    async def __aenter__(self) -> "TurnScope":
        return self.__enter__()

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> bool:
        return self.__exit__(exc_type, exc_val, exc_tb)


class _TurnSpec:
    """Options for a turn, shared by the decorator and context-manager forms."""

    def __init__(
        self,
        name: Optional[str] = None,
        id_from: Optional[Any] = None,
        infer: bool = False,
        conversation_kwargs: Optional[Dict[str, Any]] = None,
    ):
        self.name = name
        self.id_from = id_from
        self.infer = infer
        self.conversation_kwargs = conversation_kwargs or {}


class _TurnFactory:
    """What ``turn(...)`` returns: usable as ``with`` or as ``@``.

    Both forms are needed. The decorator is the clean case; the context
    manager is what a real handler uses, because the conversation id usually
    has to be dug out of a payload before a turn can be opened.
    """

    def __init__(self, spec: _TurnSpec):
        self._spec = spec
        self._scope: Optional[TurnScope] = None

    def __call__(self, func: Callable) -> Callable:
        return _decorate_turn(func, self._spec)

    def __enter__(self) -> TurnScope:
        self._scope = TurnScope(self._spec.name).start()
        return self._scope

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        return self._scope.__exit__(exc_type, exc_val, exc_tb)

    async def __aenter__(self) -> TurnScope:
        return self.__enter__()

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> bool:
        return self.__exit__(exc_type, exc_val, exc_tb)


def turn(
    func: Optional[Callable] = None,
    *,
    name: Optional[str] = None,
    id_from: Optional[Any] = None,
    infer: bool = False,
    **conversation_kwargs: Any,
):
    """One exchange — grouping and latency.

    Three call shapes, all supported::

        with agentsight.turn("ask"):      ...   # context manager
        @agentsight.turn                        # bare decorator
        @agentsight.turn(id_from="sid")         # configured decorator

    ``infer=True`` is the opt-in shortcut for handlers shaped like
    ``(text) -> str``: first string argument becomes the user message, the
    return value becomes the agent message. It is **off by default** because
    in every production service reviewed the user's text had been rewritten
    before it reached a variable (an image description, a templated prompt),
    so inferring it would put the wrong text into a client-facing transcript.
    """
    # ``turn("ask")`` is the obvious way to name a turn and reads as if it
    # already worked. Without this it binds to ``func``, fails the callable
    # test, and the name is discarded in silence — every span named "turn".
    if isinstance(func, str):
        name = name or func
        func = None

    spec = _TurnSpec(name, id_from, infer, conversation_kwargs)
    if func is not None and callable(func):
        return _decorate_turn(func, spec)  # bare @turn
    return _TurnFactory(spec)


def _resolve_conversation_id(spec: Any, arguments: Dict[str, Any]) -> Optional[str]:
    """``id_from`` accepts a parameter name or a callable.

    Parameter-name lookup covers the clean case. The callable exists because
    in real handlers the id is nested — ``json.loads(data)["conversation_id"]``
    is two dereferences from any argument.
    """
    if spec is None:
        return None
    if callable(spec):
        try:
            return spec(arguments)
        except Exception as exc:
            _log().warning("id_from callable failed: %s", exc)
            return None
    value = arguments.get(spec)
    return str(value) if value is not None else None


def _defer_if_streaming(result: Any, scope: TurnScope) -> Any:
    """Hand the span's lifetime to the result, if the result is still working.

    Deliberately a short list rather than "anything iterable": a handler that
    returns a list or a dict has finished, and deferring on those would leave
    every ordinary turn open until the watchdog killed it. Starlette's
    ``StreamingResponse`` is recognised by ``body_iterator`` rather than by
    importing it, so the SDK stays free of a FastAPI dependency.
    """
    if hasattr(result, "body_iterator"):
        return scope.wrap(result)
    if inspect.isasyncgen(result) or inspect.isgenerator(result):
        return scope.wrap(result)
    if hasattr(result, "add_done_callback"):  # asyncio / concurrent futures
        return scope.wrap(result)
    return None


def _decorate_turn(func: Callable, spec: _TurnSpec) -> Callable:
    """Wrap ``func`` so each call is one turn.

    The conversation scope is opened here only when the decorator was given
    enough to identify one (``id_from`` or conversation kwargs) and no scope is
    already active — so a decorated handler nested inside an explicit
    ``with conversation(...)`` does not start a second one.
    """

    def open_conversation_scope(arguments: Dict[str, Any]) -> Optional[ConversationScope]:
        conversation_id = _resolve_conversation_id(spec.id_from, arguments)
        if conversation_id is None and not spec.conversation_kwargs:
            return None
        if conversation_id is None and ags_context.current_conversation() is not None:
            return None
        scope = ConversationScope(conversation_id, **spec.conversation_kwargs)
        scope.__enter__()
        return scope

    def close(conversation_scope: Optional[ConversationScope]) -> None:
        if conversation_scope is not None:
            conversation_scope.__exit__(None, None, None)

    def record_input(scope: TurnScope, arguments: Dict[str, Any]) -> None:
        if not spec.infer:
            return
        # The id parameter is a string too, and usually comes first — without
        # excluding it, `@turn(id_from="session_id", infer=True)` records the
        # session id as the user's message.
        candidates = dict(arguments)
        if isinstance(spec.id_from, str):
            candidates.pop(spec.id_from, None)
        text = first_string_argument(candidates)
        if text:
            scope.add_message(MessageAttributes.SENDER_USER, text)

    def record_output(scope: TurnScope, result: Any) -> None:
        if spec.infer and result is not None:
            scope.add_message(MessageAttributes.SENDER_AGENT, result)

    def fail(scope: TurnScope, exc: BaseException) -> None:
        scope._record_failure(exc)
        scope.finish(complete=False, reason=TurnAttributes.REASON_ERROR)

    if asyncio.iscoroutinefunction(func):

        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            # Fast path. bind_arguments() calls inspect.signature(), which is
            # ~15us — far too much to pay on a decorator that is meant to be a
            # pure pass-through when the SDK is off.
            from agentsight.sdk.core import is_enabled

            if not is_enabled():
                return await func(*args, **kwargs)

            arguments = bind_arguments(func, args, kwargs)
            conversation_scope = open_conversation_scope(arguments)
            scope = TurnScope(spec.name or func.__name__).start()
            record_input(scope, arguments)
            try:
                result = await func(*args, **kwargs)
            except BaseException as exc:
                fail(scope, exc)
                close(conversation_scope)
                raise

            # A streaming result owns the span's lifetime from here: the
            # handler returns before the work happens. The conversation scope
            # must stay open too, or messages emitted while the stream drains
            # are dropped for having no active conversation.
            streamed = _defer_if_streaming(result, scope)
            if streamed is not None:
                # Released here rather than deferred: wrap() captured both
                # scopes at start() and re-attaches them around each step, so
                # the stream keeps them. Leaving them attached to *this*
                # context instead would follow the handler home — into the next
                # iteration of a worker loop, or the next task on this thread.
                scope._detach_context()
                close(conversation_scope)
                return streamed

            record_output(scope, result)
            scope.finish(complete=True)
            close(conversation_scope)
            return result

        return async_wrapper

    @functools.wraps(func)
    def sync_wrapper(*args, **kwargs):
        from agentsight.sdk.core import is_enabled

        if not is_enabled():
            return func(*args, **kwargs)

        arguments = bind_arguments(func, args, kwargs)
        conversation_scope = open_conversation_scope(arguments)
        scope = TurnScope(spec.name or func.__name__).start()
        record_input(scope, arguments)
        try:
            result = func(*args, **kwargs)
        except BaseException as exc:
            fail(scope, exc)
            close(conversation_scope)
            raise

        streamed = _defer_if_streaming(result, scope)
        if streamed is not None:
            # See the async wrapper: wrap() owns both scopes from here.
            scope._detach_context()
            close(conversation_scope)
            return streamed

        record_output(scope, result)
        scope.finish(complete=True)
        close(conversation_scope)
        return result

    return sync_wrapper
