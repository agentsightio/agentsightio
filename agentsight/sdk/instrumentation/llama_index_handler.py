"""Tool and token capture for LlamaIndex.

Registration goes through the ``instrumentation`` dispatcher rather than the
older ``callbacks`` system, and in 0.12.47 that is not a preference:

* ``set_global_handler()`` takes a *vendor string* ("wandb", "arize_phoenix",
  ...), not a handler instance. There is no slot in it for ours.
* ``Settings.callback_manager`` is read once per LLM, when the LLM object is
  constructed. Agent code builds its ``OpenAI(...)`` at module import, before
  ``agentsight.init()`` runs, so a callback manager installed afterwards
  reaches nothing.
* ``CBEventType.FUNCTION_CALL`` is emitted only by the legacy agents. The
  ``agent.workflow`` agents — what ``webtasy`` and every current LlamaIndex app
  uses — emit none of it.

The dispatcher is a module-level singleton, and every module dispatcher
propagates up to it, so one event handler and one span handler on the root see
every LLM call and every instrumented method in the process with no user code
at all.

Tool spans come from the *span* handler, not from an event. ``ToolCall`` and
``ToolCallResult`` are workflow stream events written with
``ctx.write_event_to_stream()``; they only ever reach a caller iterating
``handler.stream_events()`` itself and never reach the dispatcher, so the
design's §8 note that they are the tool signal does not hold for this path.
What does reach it is the ``dispatcher.span`` that ``DispatcherSpanMixin``
wraps around ``FunctionTool.call`` / ``.acall`` — a real bracket, with the
arguments on the way in and the ``ToolOutput`` on the way out.
"""

import threading
from collections import OrderedDict
from typing import Any, Dict, NamedTuple, Optional, Tuple

from agentsight.sdk.instrumentation.base import (
    already_patched,
    capturing,
    end_tool_span,
    from_anthropic,
    from_openai,
    mark_patched,
    nothing_reported,
    now_ns,
    provider_patch_covers,
    record_llm_call,
    start_tool_span,
)
from agentsight.sdk.semconv import LLMAttributes

#: Tool methods worth a span. ``FunctionTool.__call__`` is deliberately absent:
#: it delegates to ``call`` and both carry a span, so accepting it would emit
#: two nested spans for one synchronous tool invocation.
_TOOL_METHODS = frozenset({"call", "acall"})

#: The eight methods ``llm_chat_callback`` / ``llm_completion_callback`` wrap,
#: and so the only ones that can be either half of a nested pair — see
#: :meth:`_PendingCalls.enclosed`.
_LLM_METHODS = frozenset(
    {
        "chat",
        "achat",
        "stream_chat",
        "astream_chat",
        "complete",
        "acomplete",
        "stream_complete",
        "astream_complete",
    }
)

#: Ceilings on the two in-flight maps. Both are evicted on every normal path;
#: the caps are for the abnormal ones. A server that runs for months cannot
#: afford one leaked entry per request, and the alternative to a cap is trusting
#: a third-party dispatcher to always deliver the second half of a pair.
_MAX_PENDING_CALLS = 256
_MAX_OPEN_TOOL_SPANS = 256

#: Used when neither the response object nor ``class_name`` identifies a vendor.
#: It must not be one of the registry's target names: ``provider_patch_covers``
#: keys on those, so calling the unidentified case "llama_index" would suppress
#: every one of them. Guessing "openai" because most LlamaIndex apps are OpenAI
#: apps would do the same, and be a lie as well.
_UNKNOWN_SYSTEM = "unknown"


def _field(source: Any, name: str) -> Any:
    """Read one field whether the payload is an object or a plain dict.

    Both shapes reach us: ``LLMChatEndEvent.model_dump()`` replaces
    ``response.raw`` with a dict *in place*, so any handler registered before
    ours that dumps the event leaves us reading a dict where the provider's own
    response object used to be.
    """
    if source is None:
        return None
    if isinstance(source, dict):
        return source.get(name)
    return getattr(source, name, None)


def _method_of(span_id: Optional[str]) -> str:
    """The method name out of a dispatcher span id.

    Ids are ``f"{func.__qualname__}-{uuid4()}"`` — ``FunctionTool.acall-c658…``.
    Qualnames cannot contain a hyphen, so the split is exact.
    """
    qualname = (span_id or "").split("-", 1)[0]
    return qualname.rpartition(".")[2]


def _system_from_raw(raw: Any) -> Optional[str]:
    """``gen_ai.system`` from the provider object LlamaIndex passed through.

    The top-level module of ``response.raw`` is the provider's own package —
    ``openai.types.chat.chat_completion`` gives ``openai`` — which stays correct
    when a vendor we have never heard of ships an integration, and needs no
    table of magic strings to keep current. It also gets Azure right, where the
    class name says ``azure_openai`` but the patch that covers the call is the
    plain OpenAI one.
    """
    if raw is None or isinstance(raw, dict):
        return None
    root = (type(raw).__module__ or "").split(".")[0]
    # A response class defined in the user's own entrypoint or in the stdlib is
    # not a vendor; the class name is the better guess there.
    if root in ("", "builtins", "__main__"):
        return None
    return root


def _system_from_class_name(class_name: Optional[str]) -> Optional[str]:
    """Fallback identity from ``llm.to_dict()``: ``openai_llm`` -> ``openai``.

    ``base_component`` is what an LLM class that never overrode ``class_name()``
    reports. It names no vendor, so it is worth no more than nothing.
    """
    if not class_name or class_name == "base_component":
        return None
    name = class_name.lower()
    if name.endswith("_llm"):
        name = name[: -len("_llm")]
    return name or None


def _tool_arguments(bound_args: Any) -> Dict[str, Any]:
    """The tool's real arguments out of ``BoundArguments``.

    ``FunctionTool.acall(*args, **kwargs)`` binds to ``{"kwargs": {...}}`` with
    a sibling ``"args"`` tuple, so the arguments the model actually chose sit
    one level down. Recording the wrapper shape instead would put
    ``{"kwargs": {...}}`` in every ActionLog.
    """
    arguments = dict(getattr(bound_args, "arguments", None) or {})
    arguments.pop("self", None)
    positional = arguments.pop("args", None)
    keyword = arguments.pop("kwargs", None)
    if isinstance(keyword, dict):
        arguments.update(keyword)
    if positional:
        arguments["args"] = list(positional)
    return arguments


class _PendingCall(NamedTuple):
    """What the Start event knows and the End event does not.

    The End event carries neither model nor provider, and its ``timestamp`` is a
    naive wall-clock ``datetime.now()``, so the start time has to be taken and
    kept here. ``operation`` rides along for the calls that never get an End
    event at all — a failed call is recorded from this struct alone.
    """

    start_time_ns: int
    model: Optional[str]
    system: Optional[str]
    streaming: bool
    operation: str = "chat"


class _PendingCalls:
    """Start events waiting for their End, keyed by dispatcher span id.

    Every LLM entry point runs inside its own span, so the id matches a Start to
    exactly one End — including across streaming, where the End arrives only
    once the caller has finished iterating.

    It also holds how those spans nest, because the event handler is never told:
    only the span handler is given a ``parent_span_id``, and without it one API
    call gets counted twice — see :meth:`enclosed`.
    """

    def __init__(self, limit: int = _MAX_PENDING_CALLS):
        self._limit = limit
        self._lock = threading.Lock()
        self._entries: "OrderedDict[str, _PendingCall]" = OrderedDict()
        self._parents: "OrderedDict[str, str]" = OrderedDict()

    def start(self, span_id: Optional[str], call: _PendingCall) -> None:
        if not span_id:
            return
        with self._lock:
            self._entries[span_id] = call
            while len(self._entries) > self._limit:
                self._entries.popitem(last=False)

    def finish(self, span_id: Optional[str]) -> Optional[_PendingCall]:
        if not span_id:
            return None
        with self._lock:
            self._parents.pop(span_id, None)
            return self._entries.pop(span_id, None)

    def link(self, span_id: Optional[str], parent_span_id: Optional[str]) -> None:
        """Remember one LLM method span's parent."""
        if not span_id or not parent_span_id:
            return
        with self._lock:
            self._parents[span_id] = parent_span_id
            while len(self._parents) > self._limit:
                self._parents.popitem(last=False)

    def enclosed(self, span_id: Optional[str]) -> bool:
        """Whether an LLM call already in flight will report this one's tokens.

        LlamaIndex implements each of ``chat`` and ``complete`` in terms of the
        other for any model that only provides one — every ``CustomLLM``, and
        every chat-only integration the moment somebody calls ``.complete()``.
        Both halves emit their own Start/End pair carrying the *same* response
        object, so recording both bills one API call twice.

        The outer call wins: it is the one the application made, and the inner
        one adds nothing but a second copy of its usage.
        """
        with self._lock:
            parent = self._parents.get(span_id or "")
            for _ in range(self._limit):
                if parent is None:
                    return False
                if parent in self._entries:
                    return True
                parent = self._parents.get(parent)
        return False


def _begin_llm_call(pending: _PendingCalls, event: Any, operation: str) -> None:
    if pending.enclosed(event.span_id):
        return

    model_dict = event.model_dict or {}
    pending.start(
        event.span_id,
        _PendingCall(
            start_time_ns=now_ns(),
            model=model_dict.get("model"),
            system=_system_from_class_name(model_dict.get("class_name")),
            # The qualname says it: chat vs stream_chat vs astream_chat.
            streaming="stream" in _method_of(event.span_id),
            operation=operation,
        ),
    )


def _end_llm_call(pending: _PendingCalls, event: Any, operation: str) -> None:
    """Emit the ``llm`` span for a finished chat or completion call.

    Popping first is what keeps the map honest: a response we cannot read is
    still a pending entry we must drop.
    """
    call = pending.finish(event.span_id)
    if call is None or event.response is None:
        return

    raw = _field(event.response, "raw")

    # Two independent signals, and they can disagree: a thin wrapper around an
    # OpenAI client announces ``openai_llm`` but hands back its own response
    # class, so the module of ``raw`` names the wrapper's package instead.
    # *Either* signal naming a provider we patch is enough to stand down —
    # recording a call the patch also recorded doubles both the tokens and the
    # bill, which is a worse failure than missing one call.
    candidates = [name for name in (_system_from_raw(raw), call.system) if name]
    if any(provider_patch_covers(name) for name in candidates):
        # The patch reads the provider's own usage object; this handler reads
        # whatever LlamaIndex chose to surface, which drops the cache counters.
        return

    system = candidates[0] if candidates else _UNKNOWN_SYSTEM

    usage = _field(raw, "usage")
    if usage is None:
        # LlamaIndex's own flat fallback: prompt/completion/total, no breakdown.
        usage = _field(event.response, "additional_kwargs")

    normalize = from_anthropic if system == "anthropic" else from_openai
    tokens = normalize(usage, _field(raw, "model") or call.model)
    tokens["system"] = system

    extra: Optional[Dict[str, Any]] = None
    if call.streaming:
        extra = {LLMAttributes.STREAMING: True}
        if nothing_reported(tokens):
            # The stream ended and LlamaIndex surfaced no counts at all. The
            # 0/0 on this span is an unknown, not a zero — without the marker
            # the backend prices it as an authoritative $0. Only on the
            # streamed path: a blocking call that reports nothing is a
            # provider that never reports, which is a different gap.
            extra[LLMAttributes.USAGE_REPORTED] = False

    record_llm_call(
        **tokens,
        operation=operation,
        # ``model_dict`` holds the id the caller configured; recorded alongside
        # whenever ``raw`` resolved it to something else, exactly as the
        # provider patches do.
        requested_model=call.model,
        start_time_ns=call.start_time_ns,
        end_time_ns=now_ns(),
        extra=extra,
    )


def _fail_llm_call(
    pending: _PendingCalls, span_id: Optional[str], error: Optional[BaseException]
) -> None:
    """The failure channel for calls that end without an End event.

    The pending entry must go regardless; what else happens depends on how
    the call died. A ``GeneratorExit`` — client disconnected mid-SSE — is the
    consumer walking away, not the call failing, and LlamaIndex surfaces no
    partial usage on this path, so there is nothing worth a span. A real
    exception is recorded through :func:`record_llm_call`'s failure channel —
    unless a provider patch covers the system, in which case the patch saw
    the raise on the provider's own method and has already recorded it.
    """
    call = pending.finish(span_id)
    if call is None:
        return
    if error is None or isinstance(error, GeneratorExit):
        return
    if call.system and provider_patch_covers(call.system):
        return
    record_llm_call(
        call.system or _UNKNOWN_SYSTEM,
        call.model,
        operation=call.operation,
        start_time_ns=call.start_time_ns,
        end_time_ns=now_ns(),
        extra={LLMAttributes.STREAMING: True} if call.streaming else None,
        error=error,
    )


def _make_handlers(logger: Any) -> Tuple[Any, Any]:
    """Build the two handlers.

    Defined here rather than at module scope because they subclass LlamaIndex's
    own base classes, and importing those at module scope would make this file
    unimportable for everyone who does not have LlamaIndex installed.
    """
    from llama_index.core.base.llms.base import BaseLLM
    from llama_index.core.instrumentation.event_handlers import BaseEventHandler
    from llama_index.core.instrumentation.events.exception import ExceptionEvent
    from llama_index.core.instrumentation.events.llm import (
        LLMChatEndEvent,
        LLMChatStartEvent,
        LLMCompletionEndEvent,
        LLMCompletionStartEvent,
    )
    from llama_index.core.instrumentation.events.span import SpanDropEvent
    from llama_index.core.instrumentation.span.base import BaseSpan
    from llama_index.core.instrumentation.span_handlers import BaseSpanHandler
    from llama_index.core.tools.types import BaseTool

    pending = _PendingCalls()

    class AgentSightEventHandler(BaseEventHandler):
        """LLM tokens, for providers no patch of ours already covers.

        LlamaIndex swallows handler exceptions with a bare ``except
        BaseException: pass``, so the user's program is safe either way — but a
        silent handler makes "why are my tokens missing" unanswerable, which is
        what the debug logging below is for.
        """

        @classmethod
        def class_name(cls) -> str:
            return "AgentSightEventHandler"

        def handle(self, event: Any, **kwargs: Any) -> None:
            try:
                if isinstance(event, LLMChatStartEvent):
                    if capturing():
                        _begin_llm_call(pending, event, "chat")
                elif isinstance(event, LLMCompletionStartEvent):
                    if capturing():
                        _begin_llm_call(pending, event, "text_completion")
                elif isinstance(event, LLMChatEndEvent):
                    _end_llm_call(pending, event, "chat")
                elif isinstance(event, LLMCompletionEndEvent):
                    _end_llm_call(pending, event, "text_completion")
                elif isinstance(event, ExceptionEvent):
                    # One of the two ways a call ends without an End event:
                    # the wrapper caught something. For an abandoned stream
                    # that something is GeneratorExit, which _fail_llm_call
                    # declines to call a failure; anything else is one.
                    _fail_llm_call(
                        pending, event.span_id, getattr(event, "exception", None)
                    )
                elif isinstance(event, SpanDropEvent):
                    # The other way: a provider that raises outright reports
                    # no End event, and the only trace is its dropped span
                    # carrying the stringified error. If an ExceptionEvent
                    # for the same span got here first, the pending entry is
                    # already gone and this is a no-op.
                    err_str = getattr(event, "err_str", None)
                    _fail_llm_call(
                        pending,
                        event.span_id,
                        RuntimeError(err_str) if err_str else None,
                    )
            except Exception:
                logger.debug(
                    "agentsight: llama_index event capture failed", exc_info=True
                )

    class _ToolSpan(BaseSpan):
        """Carries the OTel span the dispatcher's own bookkeeping holds for us."""

        otel: Any = None

    class AgentSightSpanHandler(BaseSpanHandler[_ToolSpan]):
        """Tool spans, and only tool spans.

        The root dispatcher spans everything — retrievers, query engines, all
        five workflow steps, ``LLM._prepare_chat_with_tools`` — so the filter is
        the substance of this class. Returning ``None`` for everything else also
        keeps ``open_spans`` empty of spans we would never close.
        """

        @classmethod
        def class_name(cls) -> str:
            return "AgentSightSpanHandler"

        def new_span(
            self,
            id_: str,
            bound_args: Any,
            instance: Optional[Any] = None,
            parent_span_id: Optional[str] = None,
            tags: Optional[Dict[str, Any]] = None,
            **kwargs: Any,
        ) -> Optional[_ToolSpan]:
            method = _method_of(id_)
            if isinstance(instance, BaseLLM):
                # No span of ours, but this is the one place the nesting of two
                # LLM calls is visible, and the event handler needs it.
                if method in _LLM_METHODS:
                    pending.link(id_, parent_span_id)
                return None
            if not isinstance(instance, BaseTool) or method not in _TOOL_METHODS:
                return None
            try:
                span = start_tool_span(
                    instance.metadata.get_name(),
                    _tool_arguments(bound_args),
                    start_time_ns=now_ns(),
                )
                if span is None:
                    return None
                self._evict_oldest()
                return _ToolSpan(id_=id_, parent_id=parent_span_id, otel=span)
            except Exception:
                logger.debug("agentsight: llama_index tool span failed", exc_info=True)
                return None

        def prepare_to_exit_span(
            self,
            id_: str,
            bound_args: Any,
            instance: Optional[Any] = None,
            result: Optional[Any] = None,
            **kwargs: Any,
        ) -> Optional[_ToolSpan]:
            return self._close(id_, result=result)

        def prepare_to_drop_span(
            self,
            id_: str,
            bound_args: Any,
            instance: Optional[Any] = None,
            err: Optional[BaseException] = None,
            **kwargs: Any,
        ) -> Optional[_ToolSpan]:
            # A tool that raises never reaches prepare_to_exit_span; the agent
            # turns the exception into an error ToolOutput only afterwards.
            return self._close(id_, error=err)

        def _close(
            self,
            id_: str,
            result: Optional[Any] = None,
            error: Optional[BaseException] = None,
        ) -> Optional[_ToolSpan]:
            """Returning the span is what makes the base class forget it.

            So it is returned even when ending went wrong: raising here instead
            would leave the entry in ``open_spans``, holding an unended span,
            for the lifetime of the process.
            """
            span = self.open_spans.get(id_)
            if span is None:
                return None
            try:
                # A tool that reports failure in its ToolOutput rather than
                # raising it is still a failed call, and the row says so.
                if error is None and getattr(result, "is_error", False):
                    error, result = RuntimeError(str(result)), None
                end_tool_span(span.otel, result, error, end_time_ns=now_ns())
            except Exception:
                logger.debug(
                    "agentsight: llama_index tool span end failed", exc_info=True
                )
            return span

        def _evict_oldest(self) -> None:
            """Cap the open spans. Reaching this means a tool call never ended;
            closing it as an error beats letting it pin memory until restart."""
            with self.lock:
                while len(self.open_spans) >= _MAX_OPEN_TOOL_SPANS:
                    stale = self.open_spans.pop(next(iter(self.open_spans)))
                    end_tool_span(
                        stale.otel,
                        error=RuntimeError("tool span never ended; evicted"),
                        end_time_ns=now_ns(),
                    )

    return AgentSightEventHandler(), AgentSightSpanHandler()


def install_llama_index(logger: Any) -> None:
    """Attach both handlers to the root dispatcher.

    Raises when ``llama_index`` is not installed; the registry logs that and
    moves on to the next target.
    """
    from llama_index.core.instrumentation import get_dispatcher

    dispatcher = get_dispatcher()
    # ``add_*_handler`` appends with no deduplication, and the root dispatcher
    # is a module-level singleton that outlives any state this package keeps —
    # so the guard has to live on the dispatcher itself. Two copies of the event
    # handler would double every token count.
    if already_patched(dispatcher):
        return

    event_handler, span_handler = _make_handlers(logger)
    dispatcher.add_event_handler(event_handler)
    dispatcher.add_span_handler(span_handler)
    mark_patched(dispatcher)
