"""The span-emitting core every integration goes through.

Four provider integrations (OpenAI, Anthropic, LangChain, LlamaIndex) all end
up calling :func:`record_llm_call`. That is deliberate: ingest gets exactly one
code path for tokens regardless of where they came from, so a bug in the token
maths is one bug in one place rather than four that disagree.

The same holds for tool spans. ``@tool`` uses a context manager because it
brackets a call; framework handlers cannot, because they are told about the
start and the end in two separate callbacks — hence the explicit
:func:`start_tool_span` / :func:`end_tool_span` pair.
"""

import asyncio
import time
from typing import Any, Dict, Optional

from opentelemetry.trace import Status, StatusCode

from agentsight.sdk import context as ags_context
from agentsight.sdk.instrumentation.pricing import estimate_cost
from agentsight.sdk.semconv import (
    LLMAttributes,
    SpanAttributes,
    SpanKind,
    ToolAttributes,
)
from agentsight.sdk.serialization import to_json, to_text

#: Marker set on a patched callable so a second ``init()`` is a no-op rather
#: than a patch stacked on a patch — which would double every token count.
PATCH_MARKER = "_agentsight_patched"


def already_patched(target: Any) -> bool:
    return bool(getattr(target, PATCH_MARKER, False))


def mark_patched(wrapper: Any, original: Any = None) -> Any:
    """Tag a wrapper, and remember what it replaced so it can be undone."""
    setattr(wrapper, PATCH_MARKER, True)
    if original is not None:
        setattr(wrapper, "_agentsight_original", original)
    return wrapper


def capturing() -> bool:
    """Whether a span emitted right now would be kept.

    Both halves matter: ``is_enabled()`` is the process-wide switch, and
    ``tracking_enabled()`` is the per-conversation one — an LLM call made
    outside any conversation, or inside one opened ``enabled=False``, is not
    ours to record.
    """
    from agentsight.sdk.core import is_enabled

    return is_enabled() and ags_context.tracking_enabled()


def now_ns() -> int:
    return time.time_ns()


def provider_patch_covers(system: Optional[str]) -> bool:
    """True when a provider patch is already recording this system's calls.

    A LangChain app on OpenAI has two things watching the same call: the
    patched ``openai`` method and the LangChain callback handler. Both emitting
    an ``llm`` span would double every token count and every dollar.

    The patch wins, for one reason — it reads the provider's own response
    object, while a framework handler reads whatever the framework chose to
    surface, which is a lossy subset (LlamaIndex, for instance, does not
    propagate cache counters at all). The handler falls back to emitting the
    span itself for any system we do not patch, so an app on Bedrock, Vertex,
    Ollama or Cohere still gets its tokens.
    """
    if not system:
        return False
    from agentsight.sdk.instrumentation import PROVIDER_PATCHES, installed_targets

    # Only a provider patch can cover a call. Without this test an app that
    # reports its system as "langchain" or "llama_index" would silence itself
    # the moment that framework's *handler* was installed — the handler being
    # the very thing that was going to record it.
    if system not in PROVIDER_PATCHES:
        return False
    return bool(installed_targets().get(system))


# ---------------------------------------------------------------------------
# LLM spans
# ---------------------------------------------------------------------------


def record_llm_call(
    system: str,
    model: Optional[str],
    input_tokens: int = 0,
    output_tokens: int = 0,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
    reasoning_tokens: int = 0,
    audio_input_tokens: int = 0,
    audio_output_tokens: int = 0,
    embedding_tokens: int = 0,
    *,
    operation: Optional[str] = None,
    requested_model: Optional[str] = None,
    start_time_ns: Optional[int] = None,
    end_time_ns: Optional[int] = None,
    extra: Optional[Dict[str, Any]] = None,
    error: Optional[BaseException] = None,
) -> None:
    """Emit an ``llm`` span. The single entry point every integration uses.

    ``input_tokens`` must be the **uncached** input — see :func:`from_openai`
    for why that needs normalizing on one provider and not the other.

    ``start_time_ns``/``end_time_ns`` make the span cover the real call rather
    than being an instant. Without them "how much of the turn was the LLM" —
    the question §4.2 of the design promises is answerable for free — has no
    answer, because every LLM span would have zero duration.

    ``model`` is the *resolved* id when the provider reported one, because
    that is what was billed and what cost is keyed on. Pass the id the caller
    asked for as ``requested_model`` and it is recorded alongside whenever the
    two differ — otherwise the alias people actually write in their code is
    lost the moment a provider answers with a dated snapshot.

    ``error`` is the failure channel (design §13, question 5 — closed): a
    call that raised is recorded as an ERROR span rather than dropped or
    disguised as success, which is what makes an error-rate metric possible
    and a failed call distinguishable from one that never happened. Pass any
    tokens that were billed before the failure — a stream that died halfway
    still spent them.

    Disconnects are normalized away *here*, at the one choke point every
    integration shares, rather than at each of the eight-and-counting call
    sites: ``GeneratorExit`` (a sync consumer walking away) and
    ``asyncio.CancelledError`` (the async form of the same thing) are not
    the call failing — someone stopped listening. Recording them as errors
    would make an error-rate metric measure user behaviour instead of
    provider health. The span still goes out with whatever tokens were
    billed; it just carries no error marker.
    """
    from agentsight.sdk.core import get_tracer

    if not capturing():
        return

    if error is not None and isinstance(error, (GeneratorExit, asyncio.CancelledError)):
        error = None

    attributes = dict(ags_context.conversation_attributes())
    attributes.update(
        {
            SpanAttributes.KIND: SpanKind.LLM,
            SpanAttributes.ENTITY_NAME: model or system,
            LLMAttributes.SYSTEM: system,
            LLMAttributes.INPUT_TOKENS: input_tokens,
            LLMAttributes.OUTPUT_TOKENS: output_tokens,
        }
    )
    if model:
        attributes[LLMAttributes.REQUEST_MODEL] = model
    if requested_model and requested_model != model:
        # Only on the difference. ``model`` is the resolved id, which is what
        # cost and usage are keyed on and must not move; this preserves the
        # alias the caller actually typed, which the resolved id overwrites.
        attributes[LLMAttributes.REQUESTED_MODEL] = requested_model
    if operation:
        attributes[LLMAttributes.OPERATION] = operation
    if error is not None:
        # `str(exc)` is empty for bare exceptions; an ERROR span whose marker
        # is falsy would slip past any truthiness filter downstream, so fall
        # back to the class name — always non-empty, always meaningful.
        attributes[LLMAttributes.ERROR] = to_text(error) or type(error).__name__

    # Only set what actually occurred — a zero here is indistinguishable from
    # "this provider doesn't report it", and the archive should preserve that
    # difference.
    for attribute, value in (
        (LLMAttributes.CACHE_READ_TOKENS, cache_read_tokens),
        (LLMAttributes.CACHE_WRITE_TOKENS, cache_write_tokens),
        (LLMAttributes.REASONING_TOKENS, reasoning_tokens),
        (LLMAttributes.AUDIO_INPUT_TOKENS, audio_input_tokens),
        (LLMAttributes.AUDIO_OUTPUT_TOKENS, audio_output_tokens),
        (LLMAttributes.EMBEDDING_TOKENS, embedding_tokens),
    ):
        if value:
            attributes[attribute] = value

    if extra:
        attributes.update({k: v for k, v in extra.items() if v is not None})

    cost = estimate_cost(
        model,
        input_tokens,
        output_tokens,
        cache_read_tokens,
        cache_write_tokens,
        embedding_tokens,
    )
    if cost is not None:
        attributes[LLMAttributes.COST_USD] = cost

    tracer = get_tracer()
    if tracer is None:
        return
    try:
        span = tracer.start_span(
            model or system, attributes=attributes, start_time=start_time_ns
        )
        if error is not None:
            try:
                # The span is emitted after the fact, so "now" is already past
                # the measured end — dating the event there would put the
                # exception after the call it ended.
                span.record_exception(error, timestamp=end_time_ns)
            except Exception:
                pass
            span.set_status(
                Status(StatusCode.ERROR, str(error) or type(error).__name__)
            )
        span.end(end_time=end_time_ns)
    except Exception:
        # Called from inside a patched provider method, so raising here would
        # break the user's LLM call over a telemetry problem.
        pass


# ---------------------------------------------------------------------------
# Tool spans, for handlers that get start and end separately
# ---------------------------------------------------------------------------


def start_tool_span(
    name: str,
    arguments: Any = None,
    kind: str = SpanKind.TOOL,
    start_time_ns: Optional[int] = None,
):
    """Open a tool span without making it current.

    Deliberately *not* ``start_as_current_span``: a framework callback returns
    immediately, so there is no block for the span to be current inside, and
    attaching it to the context would leak — every later span in that context
    would nest under a tool that has already finished.

    Returns ``None`` when there is nothing to record, so callers can treat the
    disabled path as "no span" without a second check.
    """
    from agentsight.sdk.core import get_tracer

    if not capturing():
        return None
    tracer = get_tracer()
    if tracer is None:
        return None

    attributes = dict(ags_context.conversation_attributes())
    attributes[SpanAttributes.KIND] = kind
    attributes[SpanAttributes.ENTITY_NAME] = name
    attributes[ToolAttributes.NAME] = name
    if arguments is not None:
        attributes[ToolAttributes.ARGUMENTS] = to_json(arguments)

    try:
        return tracer.start_span(name, attributes=attributes, start_time=start_time_ns)
    except Exception:
        return None


def end_tool_span(
    span,
    result: Any = None,
    error: Optional[BaseException] = None,
    end_time_ns: Optional[int] = None,
) -> None:
    """Close a span from :func:`start_tool_span`. Never raises."""
    if span is None:
        return
    try:
        if error is not None:
            span.set_attribute(ToolAttributes.ERROR, to_text(error))
            try:
                # ``None`` falls through to "now", which is right for a span
                # being closed live; an explicit end keeps the event inside it.
                span.record_exception(error, timestamp=end_time_ns)
            except Exception:
                pass
            span.set_status(Status(StatusCode.ERROR, str(error)))
        else:
            if result is not None:
                span.set_attribute(ToolAttributes.RESPONSE, to_text(result))
            span.set_status(Status(StatusCode.OK))
    except Exception:
        pass
    finally:
        try:
            span.end(end_time=end_time_ns)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Provider normalizers
# ---------------------------------------------------------------------------
#
# The two providers disagree about whether cached tokens are part of the input
# count, and normalizing that is the whole reason these exist:
#
#   OpenAI      prompt_tokens INCLUDES cached_tokens  -> subtract to get uncached
#   Anthropic   input_tokens EXCLUDES both cache counts -> already uncached
#
# Getting this backwards double-counts cached input on one provider and, since
# cache reads are ~10x cheaper, produces a materially wrong cost.


def _get(source: Any, name: str, default: int = 0) -> int:
    """Read a field whether the payload is an object or a dict.

    Both shapes occur: the provider SDKs return pydantic models, while
    framework callbacks hand over plain dicts they built themselves.
    """
    if source is None:
        return default
    if isinstance(source, dict):
        value = source.get(name, default)
    else:
        value = getattr(source, name, default)
    return value if value is not None else default


def _sub(source: Any, name: str) -> Any:
    if source is None:
        return None
    if isinstance(source, dict):
        return source.get(name)
    return getattr(source, name, None)


def from_openai(usage: Any, model: Optional[str] = None) -> Dict[str, Any]:
    """Normalize an OpenAI ``usage`` object.

    Covers all three shapes the SDK produces: Chat Completions
    (``prompt_tokens``/``completion_tokens``), the Responses API
    (``input_tokens``/``output_tokens``), and Embeddings (prompt only).
    """
    # Responses API names them input/output; Chat Completions prompt/completion.
    prompt = _get(usage, "prompt_tokens") or _get(usage, "input_tokens")
    completion = _get(usage, "completion_tokens") or _get(usage, "output_tokens")

    prompt_details = _sub(usage, "prompt_tokens_details") or _sub(
        usage, "input_tokens_details"
    )
    completion_details = _sub(usage, "completion_tokens_details") or _sub(
        usage, "output_tokens_details"
    )

    cached = _get(prompt_details, "cached_tokens")
    audio_in = _get(prompt_details, "audio_tokens")
    reasoning = _get(completion_details, "reasoning_tokens")
    audio_out = _get(completion_details, "audio_tokens")

    return {
        "system": "openai",
        "model": model,
        # cached is part of prompt_tokens on OpenAI — subtract it out.
        "input_tokens": max(prompt - cached, 0),
        "output_tokens": completion,
        "cache_read_tokens": cached,
        "cache_write_tokens": 0,  # OpenAI caching is automatic; writes are free
        "reasoning_tokens": reasoning,
        "audio_input_tokens": audio_in,
        "audio_output_tokens": audio_out,
    }


def from_anthropic(usage: Any, model: Optional[str] = None) -> Dict[str, Any]:
    """Normalize an Anthropic ``usage`` object.

    ``reasoning_tokens`` is 0 in practice: extended thinking is billed inside
    ``output_tokens`` and the API exposes no breakdown, regardless of the
    ``thinking.display`` setting. Reporting a fabricated split would be worse
    than reporting none.

    It is read rather than hardcoded so that the day a breakdown does appear,
    it is captured without a release. Absent, the read yields 0, which is what
    hardcoding would have produced anyway — the difference costs one attribute
    lookup and removes a reason to touch this file later.
    """
    return {
        "system": "anthropic",
        "model": model,
        # Already the uncached remainder — the three counts are disjoint.
        "input_tokens": _get(usage, "input_tokens"),
        "output_tokens": _get(usage, "output_tokens"),
        "cache_read_tokens": _get(usage, "cache_read_input_tokens"),
        "cache_write_tokens": _get(usage, "cache_creation_input_tokens"),
        "reasoning_tokens": _get(_sub(usage, "output_tokens_details"), "thinking_tokens"),
    }
