"""Tool and token capture for LangChain.

LangChain has no method worth patching: every model, tool and chain announces
itself through ``BaseCallbackHandler``, and the framework's own tracers are
built that way. So this is a handler, registered once into LangChain's global
hook list so the user never has to thread ``callbacks=[...]`` through their
code — which for an agent built out of LCEL runnables would mean touching every
construction site.

**Tool spans are the reason this file exists.** The OpenAI and Anthropic patches
see the tool *call* in the model's response but never the tool *running* — not
its arguments as bound, not its result, not how long it took. Only the
framework knows that. LLM spans, by contrast, are the patches' job wherever a
patch exists: ``provider_patch_covers()`` decides, and this handler stands down
for OpenAI and Anthropic so a LangChain app on either does not count every
token twice.

Sync callbacks only. A sync handler is dispatched on every path — including
``ainvoke``, where LangChain hands it to an executor with the context copied —
whereas an async-only handler is never called from the sync path at all.
``run_inline = True`` keeps even that executor hop away.
"""

import functools
import logging
import threading
from collections import OrderedDict
from typing import Any, Dict, Optional, Tuple

from agentsight.exceptions import ToolFailure
from agentsight.sdk.instrumentation.base import (
    capturing,
    end_tool_span,
    from_anthropic,
    from_openai,
    now_ns,
    provider_patch_covers,
    record_llm_call,
    start_tool_span,
)
from agentsight.sdk.semconv import LLMAttributes
from agentsight.sdk.serialization import to_text

try:
    from langchain_core.callbacks.base import BaseCallbackHandler
except ImportError:
    # Keeps the module importable without LangChain, so the registry can report
    # a missing framework rather than failing at import of its own package.
    # ``install_langchain`` imports for real and raises the honest ImportError.
    BaseCallbackHandler = object  # type: ignore[assignment,misc]

_logger = logging.getLogger("agentsight")

#: Cap on runs waiting for their end callback. An end callback normally always
#: arrives — even an abandoned stream produces ``on_llm_error`` — but "normally"
#: is not a memory bound, and a long-lived process must not grow one entry per
#: dispatcher bug. The oldest pending entry is dropped; its span is never
#: ended, so it is never exported either.
_MAX_PENDING_RUNS = 1024

#: Reported when nothing identifies the provider. Deliberately not
#: ``"langchain"``: that is one of our own installed target names, so
#: ``provider_patch_covers()`` would return True for it and silently suppress
#: the span of every model we failed to recognise.
_UNKNOWN_SYSTEM = "unknown"

_SYSTEM_ALIASES = {
    # Azure OpenAI reports itself as "azure" but runs on the patched ``openai``
    # SDK, so the patch is already recording these calls. Left unmapped, the
    # coverage check below would miss and every token would be counted twice.
    # Renamed rather than merely covered because Azure OpenAI *is* OpenAI.
    "azure": "openai",
    "azure_openai": "openai",
}

#: Providers that are not OpenAI but make their calls through the ``openai``
#: SDK — ``ChatDeepSeek``, ``ChatXAI``, ``ChatTogether``, ``ChatFireworks`` and
#: friends are thin ``BaseChatOpenAI`` subclasses. The patch is already
#: recording those calls, so this handler must stand down, but the system it
#: *reports* stays truthful: a DeepSeek call is not an OpenAI call.
#:
#: A list, and therefore one that will go stale. When it does the failure is a
#: double count for that provider, which the user can stop with
#: ``init(auto_instrument=["langchain"])`` — the handler alone, no patch.
_COVERED_BY = {
    provider: "openai"
    for provider in (
        "deepseek",
        "xai",
        "together",
        "fireworks",
        "perplexity",
        "moonshot",
        "openrouter",
        "nvidia",
    )
}


# ---------------------------------------------------------------------------
# Usage normalisation — LangChain's shape is a third one
# ---------------------------------------------------------------------------


def _tokens_from_usage_metadata(usage: Dict[str, Any]) -> Dict[str, int]:
    """Normalize ``AIMessage.usage_metadata``, which is neither provider shape.

    LangChain restates every provider in one convention: ``input_tokens`` is
    "the sum of all input token types" — cached input included. That matches
    OpenAI and is the *opposite* of raw Anthropic, which LangChain converts by
    adding the cache counts back in. So neither :func:`from_openai` (no
    ``prompt_tokens`` here, so it would report zeros) nor :func:`from_anthropic`
    (no ``cache_read_input_tokens``, and it would skip the subtraction) can be
    reused, and the subtraction has to happen here instead.

    Providers add their own keys to ``input_token_details`` —
    ``ephemeral_1h_input_tokens`` and friends. They are subsets of
    ``cache_creation``, which is why this reads the two names it knows rather
    than summing whatever is present.
    """
    input_details = usage.get("input_token_details") or {}
    output_details = usage.get("output_token_details") or {}

    cache_read = input_details.get("cache_read") or 0
    cache_write = input_details.get("cache_creation") or 0

    return {
        "input_tokens": max(
            (usage.get("input_tokens") or 0) - cache_read - cache_write, 0
        ),
        "output_tokens": usage.get("output_tokens") or 0,
        "cache_read_tokens": cache_read,
        "cache_write_tokens": cache_write,
        "reasoning_tokens": output_details.get("reasoning") or 0,
        "audio_input_tokens": input_details.get("audio") or 0,
        "audio_output_tokens": output_details.get("audio") or 0,
    }


def _tokens_only(normalized: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in normalized.items() if k not in ("system", "model")}


def _tokens_from_llm_output(llm_output: Dict[str, Any], system: str) -> Dict[str, Any]:
    """Last resort for a message that carried no ``usage_metadata``.

    Anthropic is the one shape that must be recognised by system rather than by
    key, because its three counts are disjoint and reading them the OpenAI way
    would subtract cached input that was never in the total.

    Everything else takes the OpenAI-compatible reading. That is not a guess:
    ``usage_metadata`` is recent, and the integrations that predate it — the
    community models on Bedrock, Vertex, LiteLLM and friends — report through
    ``llm_output`` or not at all. Those are precisely the providers we do not
    patch, so returning ``{}`` for them threw away the only counts this handler
    was ever going to see.
    """
    if system == "anthropic":
        usage = llm_output.get("usage")
        return _tokens_only(from_anthropic(usage)) if usage else {}
    # ``LLMResult.flatten()`` blanks ``token_usage`` on every run but the first
    # when one request answered several prompts. An empty one present means
    # "already counted", so it must not fall through to another key.
    if "token_usage" in llm_output:
        usage = llm_output["token_usage"]
    else:
        usage = llm_output.get("usage")
    return _tokens_only(from_openai(usage)) if usage else {}


def _final_generation(response: Any) -> Any:
    try:
        return response.generations[0][0]
    except (AttributeError, IndexError, TypeError):
        return None


def _usage_and_model(
    response: Any, system: str
) -> Tuple[Optional[str], Dict[str, Any]]:
    """Read tokens and the resolved model id out of an ``LLMResult``.

    ``generations[0][0].message.usage_metadata`` first, always: it is the one
    place that is populated on every provider *and* on the streaming path,
    where ``llm_output`` is ``None`` because core builds the terminal result
    without it. The per-chunk counts are summed for us before we see them.

    A non-chat ``Generation`` has no ``.message`` at all, which is why the
    attribute is probed rather than assumed.
    """
    if response is None:
        return None, {}

    message = getattr(_final_generation(response), "message", None)
    usage = getattr(message, "usage_metadata", None)
    model = (getattr(message, "response_metadata", None) or {}).get("model_name")

    llm_output = getattr(response, "llm_output", None) or {}
    model = model or llm_output.get("model_name")

    if usage:
        return model, _tokens_from_usage_metadata(usage)
    return model, _tokens_from_llm_output(llm_output, system)


# ---------------------------------------------------------------------------
# Identifying the call
# ---------------------------------------------------------------------------


def _system_of(metadata: Dict[str, Any], serialized: Dict[str, Any]) -> str:
    """Which ``gen_ai.system`` this run belongs to.

    ``ls_provider`` is set by core for every model it dispatches, so the
    serialized fallback only matters when something other than core's own
    callback managers drove the run. It matches on substrings because the lc
    namespace does not name the pip package: ``ChatOpenAI`` serializes as
    ``["langchain", "chat_models", "openai", "ChatOpenAI"]``.
    """
    provider = (metadata.get("ls_provider") or "").lower()
    if not provider:
        path = "/".join(str(p) for p in (serialized.get("id") or ())).lower()
        provider = next((s for s in ("openai", "anthropic") if s in path), "")
    return _SYSTEM_ALIASES.get(provider, provider) or _UNKNOWN_SYSTEM


def _tool_result(output: Any) -> Tuple[Any, Optional[ToolFailure]]:
    """Split ``on_tool_end``'s payload into a result and a failure.

    A tool invoked with a ``ToolCall`` — which is every tool an agent calls —
    has its return value wrapped in a ``ToolMessage``, and a tool with
    ``handle_tool_error`` set reports its *failure* through the same wrapper
    with ``status="error"``. Recording the envelope would put a pydantic repr
    into ``agentsight.tool.response``, the field the transcript renders, and
    would file every handled failure as a success.

    Duck-typed on ``tool_call_id`` so the module keeps working without
    LangChain imported.
    """
    if getattr(output, "tool_call_id", None) is None:
        return output, None
    content = getattr(output, "content", output)
    if getattr(output, "status", None) == "error":
        return None, ToolFailure(to_text(content))
    return content, None


def _tool_name(serialized: Dict[str, Any], kwargs: Dict[str, Any]) -> str:
    """``serialized`` for a tool is ``{"name", "description"}``.

    Not the lc_id shape every other callback receives — there is no ``["id"]``
    to fall back on, and reaching for one raises on every tool call. The
    ``name`` kwarg is the *run* name and is usually None.
    """
    return serialized.get("name") or kwargs.get("name") or "tool"


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------


class _PendingLLMRun:
    """What ``on_llm_end`` needs but is not told."""

    __slots__ = ("start_time_ns", "system", "model", "operation", "streaming")

    def __init__(
        self, start_time_ns: int, system: str, model: Optional[str], operation: str
    ):
        self.start_time_ns = start_time_ns
        self.system = system
        self.model = model
        self.operation = operation
        self.streaming = False


def _guarded(method):
    """No callback may raise. ``raise_error = False`` is not enough.

    LangChain does swallow the exception, but it also logs a warning naming our
    class on every single event — user-visible noise that reads like a bug in
    their chain. Failures belong at debug level on our own logger.
    """

    @functools.wraps(method)
    def guarded(self, *args, **kwargs):
        try:
            return method(self, *args, **kwargs)
        except Exception:
            _logger.debug(
                "agentsight: langchain %s failed", method.__name__, exc_info=True
            )

    return guarded


class AgentSightCallbackHandler(BaseCallbackHandler):
    """Emits tool spans always, LLM spans only for systems we do not patch."""

    #: An exception in a callback is re-raised into the user's program when
    #: this is True. It is the one setting on this class that can break a
    #: chain, so it stays False whatever else changes.
    raise_error = False

    #: Async dispatch otherwise ships every sync callback to a thread pool.
    #: These callbacks are a dict write and a span emit; the executor hop costs
    #: more than the work.
    run_inline = True

    _instance: Optional["AgentSightCallbackHandler"] = None
    _instance_lock = threading.Lock()

    def __new__(cls) -> "AgentSightCallbackHandler":
        # One instance, because LangChain de-duplicates an identity-registered
        # handler by pointer: a user who also passes AgentSightCallbackHandler()
        # in callbacks= gets the same object back and one set of spans, where a
        # second instance would double every span it saw.
        with cls._instance_lock:
            if cls._instance is None:
                handler = super().__new__(cls)
                handler._lock = threading.Lock()
                handler._llm_runs = OrderedDict()
                handler._tool_spans = OrderedDict()
                cls._instance = handler
            return cls._instance

    # A singleton holding a threading.Lock is unpicklable, so the default
    # deepcopy raises TypeError — into the user's program, from a copy they
    # made of a config or a model that happened to carry this handler.
    # LangChain's own stateful handlers define both of these for the same
    # reason.

    def __copy__(self) -> "AgentSightCallbackHandler":
        return self

    def __deepcopy__(self, memo: Dict[int, Any]) -> "AgentSightCallbackHandler":
        return self

    # -- events we never look at ---------------------------------------------
    #
    # Skips dispatch entirely for chain, retriever and retry events, which in
    # an LCEL app outnumber the ones we want several times over. `ignore_agent`
    # is conspicuously absent: it gates the *tool* callbacks, not just agent
    # actions, and setting it would silently remove every tool span.

    @property
    def ignore_chain(self) -> bool:
        return True

    @property
    def ignore_retriever(self) -> bool:
        return True

    @property
    def ignore_retry(self) -> bool:
        return True

    @property
    def ignore_custom_event(self) -> bool:
        return True

    # -- pending-run bookkeeping ---------------------------------------------
    #
    # A run's start and end can land on different threads: the async path
    # dispatches through an executor, and .batch() spreads runs over a pool.

    def _remember(self, pending: "OrderedDict", key: Any, value: Any) -> None:
        with self._lock:
            pending[key] = value
            while len(pending) > _MAX_PENDING_RUNS:
                pending.popitem(last=False)

    def _forget(self, pending: "OrderedDict", key: Any) -> Any:
        with self._lock:
            return pending.pop(key, None)

    # -- LLM -----------------------------------------------------------------

    @_guarded
    def on_chat_model_start(self, serialized, messages, *, run_id, parent_run_id=None,
                            tags=None, metadata=None, **kwargs) -> None:
        # Must not raise NotImplementedError — LangChain reads that as "this
        # handler is chat-unaware" and re-dispatches the same run to
        # on_llm_start, opening it twice. @_guarded makes that impossible.
        self._open_llm_run(run_id, serialized, metadata, "chat")

    @_guarded
    def on_llm_start(self, serialized, prompts, *, run_id, parent_run_id=None,
                     tags=None, metadata=None, **kwargs) -> None:
        self._open_llm_run(run_id, serialized, metadata, "text_completion")

    def _open_llm_run(self, run_id, serialized, metadata, operation: str) -> None:
        if not capturing():
            return
        metadata = metadata or {}
        system = _system_of(metadata, serialized or {})
        if provider_patch_covers(_COVERED_BY.get(system, system)):
            # The patch reads the provider's own response object; we would read
            # whatever LangChain chose to surface. Nothing is stored, so the
            # matching end callback finds no run and emits nothing.
            return
        self._remember(
            self._llm_runs,
            run_id,
            _PendingLLMRun(now_ns(), system, metadata.get("ls_model_name"), operation),
        )

    @_guarded
    def on_llm_new_token(self, token, *, chunk=None, run_id, parent_run_id=None,
                         **kwargs) -> None:
        # The only honest streaming signal. `llm_output is None` at the end
        # would misclassify cache hits, which look identical there, and the
        # terminal generation is folded back into a non-chunk type on the
        # astream_events path.
        with self._lock:
            run = self._llm_runs.get(run_id)
            if run is not None:
                run.streaming = True

    @_guarded
    def on_llm_end(self, response, *, run_id, parent_run_id=None, **kwargs) -> None:
        self._close_llm_run(run_id, response)

    @_guarded
    def on_llm_error(self, error, *, run_id, parent_run_id=None, **kwargs) -> None:
        # Two different things land here and they are not the same signal:
        #
        # * A GeneratorExit from a half-consumed .stream() — the consumer
        #   walked away; the call itself did not fail. Recorded only if
        #   tokens were billed (they were really spent), never as an error:
        #   disconnects in an error-rate metric would be noise.
        # * A real exception — the call failed. Always recorded, through
        #   record_llm_call's failure channel, tokens or none: a call that
        #   raised is a call that happened, and hiding it either inflates
        #   the success rate or (for retries) undercounts real attempts.
        failure = None if isinstance(error, GeneratorExit) else error
        self._close_llm_run(
            run_id,
            kwargs.get("response"),
            only_if_billed=failure is None,
            error=failure,
        )

    def _close_llm_run(
        self,
        run_id,
        response,
        only_if_billed: bool = False,
        error: Optional[BaseException] = None,
    ) -> None:
        run = self._forget(self._llm_runs, run_id)
        if run is None:
            return
        model, tokens = _usage_and_model(response, run.system)
        if only_if_billed and not any(tokens.values()):
            return
        record_llm_call(
            run.system,
            model or run.model,
            operation=run.operation,
            start_time_ns=run.start_time_ns,
            end_time_ns=now_ns(),
            extra={LLMAttributes.STREAMING: True} if run.streaming else None,
            error=error,
            **tokens,
        )

    # -- tools ---------------------------------------------------------------

    @_guarded
    def on_tool_start(self, serialized, input_str, *, run_id, parent_run_id=None,
                      tags=None, metadata=None, inputs=None, **kwargs) -> None:
        span = start_tool_span(
            _tool_name(serialized or {}, kwargs),
            # `inputs` is the call as the tool actually received it; `input_str`
            # is str() of the same thing and loses the structure.
            inputs if inputs is not None else input_str,
            start_time_ns=now_ns(),
        )
        if span is not None:
            self._remember(self._tool_spans, run_id, span)

    @_guarded
    def on_tool_end(self, output, *, run_id, parent_run_id=None, **kwargs) -> None:
        # Only unhandled errors reach on_tool_error. A tool with
        # handle_tool_error set finishes *here*, carrying an error-status
        # ToolMessage — so this end is not necessarily a success.
        result, failure = _tool_result(output)
        end_tool_span(
            self._forget(self._tool_spans, run_id),
            result=result,
            error=failure,
            end_time_ns=now_ns(),
        )

    @_guarded
    def on_tool_error(self, error, *, run_id, parent_run_id=None, **kwargs) -> None:
        end_tool_span(
            self._forget(self._tool_spans, run_id), error=error, end_time_ns=now_ns()
        )


# ---------------------------------------------------------------------------
# Install
# ---------------------------------------------------------------------------


class _AlwaysOn:
    """A ContextVar-shaped hook whose value is the same handler everywhere.

    ``register_configure_hook`` is documented to take a ``ContextVar``, and a
    ContextVar is thread-scoped: a thread the user starts — a Flask worker, a
    Celery task, anything behind ``threading.Thread`` — begins with a fresh
    empty context where ``get()`` returns None, so not one callback fires and
    the app silently records nothing. LangChain only ever calls ``get()`` on
    what it was given, so returning the handler unconditionally makes the
    registration global in the way users assume it already is.
    """

    __slots__ = ("_handler",)

    def __init__(self, handler: AgentSightCallbackHandler):
        self._handler = handler

    def get(self) -> AgentSightCallbackHandler:
        return self._handler


_registered = False
_register_lock = threading.Lock()


def install_langchain(logger: Any) -> None:
    """Register the handler with LangChain's global hook list.

    Raises when ``langchain-core`` is not installed; the registry logs that and
    moves on to the next target.

    There is no callable to wrap here, so ``already_patched()`` has nothing to
    mark — the module flag is what keeps a second ``init()`` from appending a
    second hook, which would put a second handler on every run and double every
    count.
    """
    from langchain_core.tracers.context import register_configure_hook

    global _logger, _registered

    with _register_lock:
        _logger = logger
        if _registered:
            return
        # inheritable=True: an LLM or tool nested inside a chain gets its
        # handlers from the parent run's manager, not from a fresh configure.
        register_configure_hook(
            _AlwaysOn(AgentSightCallbackHandler()), inheritable=True
        )
        _registered = True
