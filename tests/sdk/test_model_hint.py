"""``agentsight.model_hint`` — the user's name for a call we cannot name.

The contract under test: strictly a last resort. A call that resolves any
model of its own keeps it, whatever hint blocks it ran inside; the hint fills
the hole only when detection came up empty, and the span it fills is stamped
``model_declared`` so the archive can tell an assertion from a measurement.

The scope reads at *call start*: a stream created inside the block is covered
even when it drains after the block exits, which is how ``wrap()``-shaped
handlers actually run. The recorder tests at the bottom pin that mechanism for
the provider patches without a fake provider in sight.
"""

import asyncio
import logging

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

import agentsight.sdk as ags
from agentsight.sdk import context as ags_context
from agentsight.sdk import core
from agentsight.sdk.instrumentation import record_llm_call
from agentsight.sdk.instrumentation.base import now_ns
from agentsight.sdk.processors import TurnBufferingProcessor
from agentsight.sdk.semconv import LLMAttributes, SpanAttributes, SpanKind

logger = logging.getLogger("agentsight-test")


@pytest.fixture
def spans():
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(TurnBufferingProcessor(SimpleSpanProcessor(exporter)))

    previous = (core._state.enabled, core._state.provider, core._state.tracer)
    core._state.provider = provider
    core._state.tracer = provider.get_tracer("agentsight-test")
    core._state.enabled = True
    try:
        yield exporter
    finally:
        core._state.enabled, core._state.provider, core._state.tracer = previous


def llm_spans(exporter):
    return [
        s
        for s in exporter.get_finished_spans()
        if (s.attributes or {}).get(SpanAttributes.KIND) == SpanKind.LLM
    ]


# ---------------------------------------------------------------------------
# 1. The fallback, and its precedence
# ---------------------------------------------------------------------------


def test_the_hint_names_a_call_nothing_else_could(spans):
    with ags.conversation("c-hint"):
        with ags.model_hint("llama3.1:8b"):
            record_llm_call("customvendor", None, input_tokens=7, output_tokens=3)

    (llm,) = llm_spans(spans)
    assert llm.name == "llama3.1:8b"
    assert llm.attributes[LLMAttributes.REQUEST_MODEL] == "llama3.1:8b"
    assert llm.attributes[SpanAttributes.ENTITY_NAME] == "llama3.1:8b"
    assert llm.attributes[LLMAttributes.MODEL_DECLARED] is True


def test_a_resolved_model_is_never_overridden(spans):
    """The whole safety argument: at worst the hint names a nameless call,
    never one that was resolved — so a broad hint over a two-model app cannot
    corrupt the model that detection got right."""
    with ags.conversation("c-hint-resolved"):
        with ags.model_hint("wrong-model"):
            record_llm_call("openai", "gpt-4o-2024-08-06", input_tokens=7)

    (llm,) = llm_spans(spans)
    assert llm.attributes[LLMAttributes.REQUEST_MODEL] == "gpt-4o-2024-08-06"
    assert LLMAttributes.MODEL_DECLARED not in llm.attributes


def test_the_callers_own_model_argument_also_outranks_it(spans):
    """Integrations fold the requested id into ``model`` when nothing resolved
    — that fold outranks the hint too: what the caller passed to the provider
    beats what they declared to us."""
    with ags.conversation("c-hint-requested"):
        with ags.model_hint("wrong-model"):
            record_llm_call(
                "openai", "gpt-4o-mini", input_tokens=7, requested_model="gpt-4o-mini"
            )

    (llm,) = llm_spans(spans)
    assert llm.attributes[LLMAttributes.REQUEST_MODEL] == "gpt-4o-mini"
    assert LLMAttributes.MODEL_DECLARED not in llm.attributes


def test_without_a_hint_a_nameless_call_stays_nameless(spans):
    with ags.conversation("c-no-hint"):
        record_llm_call("customvendor", None, input_tokens=7)

    (llm,) = llm_spans(spans)
    assert LLMAttributes.REQUEST_MODEL not in llm.attributes
    assert LLMAttributes.MODEL_DECLARED not in llm.attributes
    assert llm.attributes[SpanAttributes.ENTITY_NAME] == "customvendor"


# ---------------------------------------------------------------------------
# 2. Scope mechanics
# ---------------------------------------------------------------------------


def test_the_innermost_hint_wins_and_exiting_restores(spans):
    with ags.conversation("c-nest"):
        with ags.model_hint("outer"):
            record_llm_call("v", None, input_tokens=1)
            with ags.model_hint("inner"):
                record_llm_call("v", None, input_tokens=1)
            record_llm_call("v", None, input_tokens=1)
        record_llm_call("v", None, input_tokens=1)

    names = [s.attributes.get(LLMAttributes.REQUEST_MODEL) for s in llm_spans(spans)]
    assert names == ["outer", "inner", "outer", None]


def test_the_decorator_form_covers_sync_and_async(spans):
    @ags.model_hint("decorated-model")
    def handler():
        record_llm_call("v", None, input_tokens=1)

    @ags.model_hint("decorated-model")
    async def async_handler():
        record_llm_call("v", None, input_tokens=1)

    with ags.conversation("c-decorated"):
        handler()
        asyncio.run(async_handler())

    names = [s.attributes.get(LLMAttributes.REQUEST_MODEL) for s in llm_spans(spans)]
    assert names == ["decorated-model", "decorated-model"]


def test_a_non_string_hint_is_its_str_form(spans):
    """Model ids arrive as enums and config objects often enough; dropping a
    hint over its type would defeat the one job it has."""

    class ModelName:
        def __str__(self) -> str:
            return "my-model-v2"

    with ags.conversation("c-str"):
        with ags.model_hint(ModelName()):
            record_llm_call("v", None, input_tokens=1)

    (llm,) = llm_spans(spans)
    assert llm.attributes[LLMAttributes.REQUEST_MODEL] == "my-model-v2"


@pytest.mark.parametrize("empty", [None, ""])
def test_an_empty_hint_is_inert(spans, empty):
    with ags.conversation("c-empty"):
        with ags.model_hint(empty):
            record_llm_call("v", None, input_tokens=1)

    (llm,) = llm_spans(spans)
    assert LLMAttributes.REQUEST_MODEL not in llm.attributes
    assert LLMAttributes.MODEL_DECLARED not in llm.attributes


# ---------------------------------------------------------------------------
# 3. Read at call start — the deferred-record paths
# ---------------------------------------------------------------------------
#
# Streams record when they drain, and with ``wrap()`` that is after the hint
# block has exited. Each deferred recorder snapshots the hint when the call
# starts; these tests build the recorder inside the block and finish it
# outside, which is exactly that timeline.


def test_the_snapshot_outranks_whatever_is_ambient_at_record_time(spans):
    with ags.conversation("c-snapshot"):
        with ags.model_hint("at-record-time"):
            record_llm_call("v", None, input_tokens=1, model_hint="at-call-start")

    (llm,) = llm_spans(spans)
    assert llm.attributes[LLMAttributes.REQUEST_MODEL] == "at-call-start"


def test_an_openai_stream_drained_after_the_block_keeps_the_hint(spans):
    from agentsight.sdk.instrumentation.openai_patch import _CHAT, _StreamRecorder

    with ags.conversation("c-openai-drain"):
        with ags.model_hint("stream-model"):
            recorder = _StreamRecorder(_CHAT, None, now_ns(), logger)
        recorder.finish()  # the block is gone; the snapshot is not

    (llm,) = llm_spans(spans)
    assert llm.attributes[LLMAttributes.REQUEST_MODEL] == "stream-model"
    assert llm.attributes[LLMAttributes.MODEL_DECLARED] is True
    assert llm.attributes[LLMAttributes.STREAMING] is True


def test_an_anthropic_stream_drained_after_the_block_keeps_the_hint(spans):
    from agentsight.sdk.instrumentation.anthropic_patch import _StreamRecorder

    with ags.conversation("c-anthropic-drain"):
        with ags.model_hint("stream-model"):
            recorder = _StreamRecorder(None, now_ns(), logger)
        recorder.finish()

    (llm,) = llm_spans(spans)
    assert llm.attributes[LLMAttributes.REQUEST_MODEL] == "stream-model"
    assert llm.attributes[LLMAttributes.MODEL_DECLARED] is True


def test_the_contextvar_is_clean_after_an_exception():
    with pytest.raises(RuntimeError):
        with ags.model_hint("leaky"):
            raise RuntimeError("boom")

    assert ags_context.current_model_hint() is None
