"""Adversarial verification of the LangChain callback handler.

No network and no key: the models are real ``BaseChatModel`` subclasses driven
through LangChain's own callback managers, so every span here was produced by
the same dispatch path a live ``ChatBedrock`` or ``ChatOpenAI`` goes through.

The token assertions matter. The transparency ones matter more — a wrong count
is a bug report, a chain that raises because a callback did is an outage in
someone else's product.
"""

import copy
import logging
import uuid
from typing import Any, List, Optional

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode

import agentsight.sdk as ags
from agentsight.sdk import core, instrumentation
from agentsight.sdk.instrumentation import langchain_handler
from agentsight.sdk.instrumentation.langchain_handler import (
    AgentSightCallbackHandler,
    install_langchain,
)
from agentsight.sdk.processors import TurnBufferingProcessor
from agentsight.sdk.semconv import (
    LLMAttributes,
    SpanAttributes,
    SpanKind,
    ToolAttributes,
)

pytest.importorskip("langchain_core")

from langchain_core.language_models.chat_models import BaseChatModel  # noqa: E402
from langchain_core.language_models.llms import LLM  # noqa: E402
from langchain_core.messages import AIMessage, AIMessageChunk  # noqa: E402
from langchain_core.outputs import (  # noqa: E402
    ChatGeneration,
    ChatGenerationChunk,
    ChatResult,
)
from langchain_core.runnables import RunnableLambda  # noqa: E402
from langchain_core.tools import StructuredTool, ToolException, tool  # noqa: E402
from langchain_core.tracers.context import _configure_hooks  # noqa: E402

logger = logging.getLogger("agentsight-test")


# ---------------------------------------------------------------------------
# Fake providers
# ---------------------------------------------------------------------------


class FakeChat(BaseChatModel):
    """A chat model whose provider, usage and failure mode the test picks.

    ``provider`` lands in ``metadata["ls_provider"]`` exactly as a real
    integration's ``_get_ls_params`` puts it there, which is the input
    ``_system_of`` reads.
    """

    provider: str = "bedrock"
    model_name: str = "fake-1"
    #: What the response reports it actually ran, which outranks the requested
    #: model. None for the providers that report nothing.
    reported_model: Optional[str] = "fake-1"
    usage: Optional[dict] = None
    output: Optional[dict] = None
    chunks: Optional[List[Any]] = None
    boom: Optional[Any] = None

    @property
    def _llm_type(self) -> str:
        return "fake"

    def _get_ls_params(self, stop=None, **kwargs):
        params = super()._get_ls_params(stop=stop, **kwargs)
        params["ls_provider"] = self.provider
        return params

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        if self.boom is not None:
            raise self.boom
        message = AIMessage(
            content="hello",
            usage_metadata=self.usage,
            response_metadata=(
                {"model_name": self.reported_model} if self.reported_model else {}
            ),
        )
        return ChatResult(
            generations=[ChatGeneration(message=message)], llm_output=self.output
        )

    def _stream(self, messages, stop=None, run_manager=None, **kwargs):
        for chunk in self.chunks or []:
            yield chunk
        if self.boom is not None:
            raise self.boom


class FakeLLM(LLM):
    @property
    def _llm_type(self) -> str:
        return "fake_completion"

    def _call(self, prompt, stop=None, run_manager=None, **kwargs):
        return "completed"


def chunk(content: str, **usage) -> ChatGenerationChunk:
    return ChatGenerationChunk(
        message=AIMessageChunk(content=content, usage_metadata=usage or None)
    )


#: LangChain's own convention: ``input_tokens`` is the sum of every input
#: category, cache included — the opposite of raw Anthropic.
LC_USAGE = {
    "input_tokens": 1000,
    "output_tokens": 50,
    "total_tokens": 1050,
    "input_token_details": {"cache_read": 300, "cache_creation": 100, "audio": 7},
    "output_token_details": {"reasoning": 20, "audio": 3},
}


@tool
def add(a: int, b: int) -> int:
    """Add two numbers."""
    return a + b


@tool
def explode(a: int) -> int:
    """Always raises."""
    raise ValueError("tool blew up")


def _raise_tool_exception(a: int) -> int:
    raise ToolException("upstream refused")


handled = StructuredTool.from_function(
    func=_raise_tool_exception,
    name="handled",
    description="Fails, but the agent keeps going.",
    handle_tool_error=True,
)


# ---------------------------------------------------------------------------
# SDK harness
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session", autouse=True)
def installed():
    """Registration is global and idempotent; installing it twice is the point."""
    install_langchain(logger)
    install_langchain(logger)


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


@pytest.fixture(autouse=True)
def clean_handler():
    """The handler is a process-wide singleton; one test must not seed the next."""
    handler = AgentSightCallbackHandler()
    handler._llm_runs.clear()
    handler._tool_spans.clear()
    yield handler
    handler._llm_runs.clear()
    handler._tool_spans.clear()


def of_kind(exporter, kind):
    return [
        s
        for s in exporter.get_finished_spans()
        if (s.attributes or {}).get(SpanAttributes.KIND) == kind
    ]


def llm_spans(exporter):
    return of_kind(exporter, SpanKind.LLM)


def tool_spans(exporter):
    return of_kind(exporter, SpanKind.TOOL)


# ---------------------------------------------------------------------------
# 1. Double counting
# ---------------------------------------------------------------------------


def test_installing_twice_appends_one_hook(spans):
    before = len(_configure_hooks)
    install_langchain(logger)
    install_langchain(logger)
    assert len(_configure_hooks) == before


def test_installing_twice_still_records_one_llm_span(spans):
    model = FakeChat(usage=LC_USAGE)

    with ags.conversation("c-double"):
        with ags.turn():
            model.invoke("hi")

    assert len(llm_spans(spans)) == 1


def test_installing_twice_still_records_one_tool_span(spans):
    with ags.conversation("c-double-tool"):
        with ags.turn():
            add.invoke({"a": 1, "b": 2})

    assert len(tool_spans(spans)) == 1


def test_a_user_supplied_handler_is_the_same_object(spans, clean_handler):
    """The singleton is what makes LangChain's identity de-dupe work."""
    assert AgentSightCallbackHandler() is clean_handler

    with ags.conversation("c-explicit"):
        with ags.turn():
            add.invoke({"a": 1, "b": 2}, config={"callbacks": [clean_handler]})

    assert len(tool_spans(spans)) == 1


def test_a_handler_on_the_model_does_not_double_the_span(spans, clean_handler):
    model = FakeChat(usage=LC_USAGE, callbacks=[clean_handler])

    with ags.conversation("c-model-callbacks"):
        with ags.turn():
            model.invoke("hi")

    assert len(llm_spans(spans)) == 1


def test_a_tool_nested_in_a_chain_is_recorded_once(spans):
    chain = RunnableLambda(lambda value: {"a": value, "b": 1}) | add

    with ags.conversation("c-lcel"):
        with ags.turn():
            assert chain.invoke(3) == 4

    assert len(tool_spans(spans)) == 1


def test_a_batch_records_one_span_per_call(spans):
    model = FakeChat(usage=LC_USAGE)

    with ags.conversation("c-batch"):
        with ags.turn():
            model.batch(["a", "b", "c"])

    assert len(llm_spans(spans)) == 3


def test_a_patched_provider_suppresses_the_handlers_llm_span(spans, monkeypatch):
    """The patch reads the provider's own response; the handler stands down."""
    monkeypatch.setitem(instrumentation._installed, "openai", True)

    with ags.conversation("c-covered"):
        with ags.turn():
            FakeChat(provider="openai", usage=LC_USAGE).invoke("hi")
            FakeChat(provider="azure", usage=LC_USAGE).invoke("hi")
            FakeChat(provider="anthropic", usage=LC_USAGE).invoke("hi")
            FakeChat(provider="bedrock", usage=LC_USAGE).invoke("hi")

    systems = [s.attributes[LLMAttributes.SYSTEM] for s in llm_spans(spans)]
    assert systems == ["anthropic", "bedrock"]


def test_a_covered_provider_still_gets_its_tool_spans(spans, monkeypatch):
    monkeypatch.setitem(instrumentation._installed, "openai", True)

    with ags.conversation("c-covered-tool"):
        with ags.turn():
            add.invoke({"a": 1, "b": 2})

    assert len(tool_spans(spans)) == 1


# ---------------------------------------------------------------------------
# 2. Token maths
# ---------------------------------------------------------------------------


def test_cache_read_and_cache_creation_are_subtracted_from_input(spans):
    """LangChain folds every input category into ``input_tokens``."""
    with ags.conversation("c-tokens"):
        with ags.turn():
            FakeChat(usage=LC_USAGE).invoke("hi")

    (llm,) = llm_spans(spans)
    assert llm.attributes[LLMAttributes.INPUT_TOKENS] == 600
    assert llm.attributes[LLMAttributes.CACHE_READ_TOKENS] == 300
    assert llm.attributes[LLMAttributes.CACHE_WRITE_TOKENS] == 100
    assert llm.attributes[LLMAttributes.OPERATION] == "chat"
    assert llm.attributes[LLMAttributes.SYSTEM] == "bedrock"


def test_reasoning_and_audio_are_reported_but_not_added_to_the_total(spans):
    with ags.conversation("c-subsets"):
        with ags.turn():
            FakeChat(usage=LC_USAGE).invoke("hi")

    (llm,) = llm_spans(spans)
    assert llm.attributes[LLMAttributes.REASONING_TOKENS] == 20
    assert llm.attributes[LLMAttributes.AUDIO_INPUT_TOKENS] == 7
    assert llm.attributes[LLMAttributes.AUDIO_OUTPUT_TOKENS] == 3
    assert llm.attributes[LLMAttributes.OUTPUT_TOKENS] == 50
    billable = sum(llm.attributes.get(name, 0) for name in LLMAttributes.BILLABLE)
    assert billable == 600 + 50 + 300 + 100


def test_an_openai_shaped_llm_output_has_its_cache_subtracted(spans):
    """OpenAI folds cached tokens into ``prompt_tokens``."""
    model = FakeChat(
        provider="openai",
        reported_model=None,
        output={
            "token_usage": {
                "prompt_tokens": 100,
                "completion_tokens": 40,
                "prompt_tokens_details": {"cached_tokens": 40},
            },
            "model_name": "gpt-4o",
        },
    )

    with ags.conversation("c-openai-output"):
        with ags.turn():
            model.invoke("hi")

    (llm,) = llm_spans(spans)
    assert llm.attributes[LLMAttributes.INPUT_TOKENS] == 60
    assert llm.attributes[LLMAttributes.CACHE_READ_TOKENS] == 40
    assert llm.attributes[LLMAttributes.REQUEST_MODEL] == "gpt-4o"


def test_an_anthropic_shaped_llm_output_keeps_its_input_intact(spans):
    """Anthropic's three counts are disjoint; subtracting would lose 300."""
    model = FakeChat(
        provider="anthropic",
        output={
            "usage": {
                "input_tokens": 700,
                "output_tokens": 40,
                "cache_read_input_tokens": 300,
                "cache_creation_input_tokens": 100,
            }
        },
    )

    with ags.conversation("c-anthropic-output"):
        with ags.turn():
            model.invoke("hi")

    (llm,) = llm_spans(spans)
    assert llm.attributes[LLMAttributes.INPUT_TOKENS] == 700
    assert llm.attributes[LLMAttributes.CACHE_READ_TOKENS] == 300
    assert llm.attributes[LLMAttributes.CACHE_WRITE_TOKENS] == 100


def test_an_unpatched_provider_keeps_the_tokens_in_its_llm_output(spans):
    """The systems we do not patch are the whole reason this handler emits
    LLM spans at all, and plenty of them report usage only in ``llm_output``."""
    model = FakeChat(
        provider="litellm",
        output={"token_usage": {"prompt_tokens": 100, "completion_tokens": 40}},
    )

    with ags.conversation("c-community-output"):
        with ags.turn():
            model.invoke("hi")

    (llm,) = llm_spans(spans)
    assert llm.attributes[LLMAttributes.INPUT_TOKENS] == 100
    assert llm.attributes[LLMAttributes.OUTPUT_TOKENS] == 40


def test_usage_metadata_wins_over_llm_output(spans):
    model = FakeChat(
        usage={"input_tokens": 11, "output_tokens": 3, "total_tokens": 14},
        output={"token_usage": {"prompt_tokens": 999, "completion_tokens": 999}},
    )

    with ags.conversation("c-precedence"):
        with ags.turn():
            model.invoke("hi")

    (llm,) = llm_spans(spans)
    assert llm.attributes[LLMAttributes.INPUT_TOKENS] == 11
    assert llm.attributes[LLMAttributes.OUTPUT_TOKENS] == 3


def test_a_span_covers_the_call_rather_than_an_instant(spans):
    with ags.conversation("c-duration"):
        with ags.turn():
            FakeChat(usage=LC_USAGE).invoke("hi")

    (llm,) = llm_spans(spans)
    assert llm.end_time > llm.start_time


def test_a_completion_model_is_a_different_operation(spans):
    with ags.conversation("c-completion"):
        with ags.turn():
            assert FakeLLM().invoke("hi") == "completed"

    (llm,) = llm_spans(spans)
    assert llm.attributes[LLMAttributes.OPERATION] == "text_completion"


def test_a_streamed_call_is_flagged_and_sums_its_chunks(spans):
    model = FakeChat(
        chunks=[
            chunk("a", input_tokens=10, output_tokens=1, total_tokens=11),
            chunk("b", input_tokens=0, output_tokens=2, total_tokens=2),
        ]
    )

    with ags.conversation("c-stream"):
        with ags.turn():
            assert [c.content for c in model.stream("hi")] == ["a", "b"]

    (llm,) = llm_spans(spans)
    assert llm.attributes[LLMAttributes.STREAMING] is True
    assert llm.attributes[LLMAttributes.INPUT_TOKENS] == 10
    assert llm.attributes[LLMAttributes.OUTPUT_TOKENS] == 3


def test_a_non_streamed_call_is_not_flagged_as_streaming(spans):
    with ags.conversation("c-not-stream"):
        with ags.turn():
            FakeChat(usage=LC_USAGE).invoke("hi")

    (llm,) = llm_spans(spans)
    assert LLMAttributes.STREAMING not in llm.attributes


# ---------------------------------------------------------------------------
# 3. Transparency
# ---------------------------------------------------------------------------


def test_the_returned_message_is_the_same_with_and_without_a_conversation(spans):
    model = FakeChat(usage=LC_USAGE)

    untracked = model.invoke("hi")
    with ags.conversation("c-identity"):
        with ags.turn():
            tracked = model.invoke("hi")

    assert tracked.content == untracked.content
    assert tracked.usage_metadata == untracked.usage_metadata
    assert type(tracked) is type(untracked)


def test_a_stream_yields_exactly_the_same_chunks(spans):
    def fresh():
        return FakeChat(
            chunks=[
                chunk("a", input_tokens=10, output_tokens=1, total_tokens=11),
                chunk("b", input_tokens=0, output_tokens=2, total_tokens=2),
            ]
        )

    untracked = [(type(c), c.content) for c in fresh().stream("hi")]
    with ags.conversation("c-stream-identity"):
        with ags.turn():
            tracked = [(type(c), c.content) for c in fresh().stream("hi")]

    assert tracked == untracked


def test_a_model_error_is_raised_unchanged(spans):
    failure = RuntimeError("provider down")
    model = FakeChat(boom=failure)

    with ags.conversation("c-model-error"):
        with ags.turn():
            with pytest.raises(RuntimeError) as raised:
                model.invoke("hi")

    assert raised.value is failure


def test_a_tool_error_is_raised_unchanged(spans):
    with ags.conversation("c-tool-error"):
        with ags.turn():
            with pytest.raises(ValueError, match="tool blew up"):
                explode.invoke({"a": 1})


def test_the_handler_survives_being_copied(spans, clean_handler):
    """A singleton holding a lock must not blow up when a config carrying it is
    copied — LangChain's own stateful handlers define both of these."""
    assert copy.copy(clean_handler) is clean_handler
    assert copy.deepcopy(clean_handler) is clean_handler
    assert copy.deepcopy({"callbacks": [clean_handler]})["callbacks"][0] is clean_handler


def test_a_callback_that_raises_does_not_reach_the_user(spans, monkeypatch, caplog):
    """``raise_error = False`` alone would log a warning naming our class."""

    def explode_now(*args, **kwargs):
        raise RuntimeError("telemetry is on fire")

    monkeypatch.setattr(langchain_handler, "start_tool_span", explode_now)

    with caplog.at_level(logging.WARNING):
        with ags.conversation("c-quiet"):
            with ags.turn():
                assert add.invoke({"a": 1, "b": 2}) == 3

    assert "AgentSightCallbackHandler" not in caplog.text


# ---------------------------------------------------------------------------
# 4. Failure isolation
# ---------------------------------------------------------------------------


def _explode(*args, **kwargs):
    raise RuntimeError("telemetry is on fire")


def test_a_broken_recorder_cannot_break_a_model_call(spans, monkeypatch):
    monkeypatch.setattr(langchain_handler, "record_llm_call", _explode)

    with ags.conversation("c-broken-llm"):
        with ags.turn():
            assert FakeChat(usage=LC_USAGE).invoke("hi").content == "hello"


def test_a_broken_recorder_cannot_break_a_stream(spans, monkeypatch):
    monkeypatch.setattr(langchain_handler, "record_llm_call", _explode)
    model = FakeChat(chunks=[chunk("a"), chunk("b")])

    with ags.conversation("c-broken-stream"):
        with ags.turn():
            assert [c.content for c in model.stream("hi")] == ["a", "b"]


def test_a_broken_tool_span_cannot_break_a_tool(spans, monkeypatch):
    monkeypatch.setattr(langchain_handler, "start_tool_span", _explode)
    monkeypatch.setattr(langchain_handler, "end_tool_span", _explode)

    with ags.conversation("c-broken-tool"):
        with ags.turn():
            assert add.invoke({"a": 1, "b": 2}) == 3


def test_a_broken_capturing_check_cannot_break_anything(spans, monkeypatch):
    monkeypatch.setattr(langchain_handler, "capturing", _explode)

    with ags.conversation("c-broken-check"):
        with ags.turn():
            assert FakeChat(usage=LC_USAGE).invoke("hi").content == "hello"
            assert add.invoke({"a": 1, "b": 2}) == 3


@pytest.mark.asyncio
async def test_a_broken_recorder_cannot_break_an_async_call(spans, monkeypatch):
    monkeypatch.setattr(langchain_handler, "record_llm_call", _explode)

    with ags.conversation("c-broken-async"):
        with ags.turn():
            result = await FakeChat(usage=LC_USAGE).ainvoke("hi")

    assert result.content == "hello"


# ---------------------------------------------------------------------------
# 5. Leaks
# ---------------------------------------------------------------------------


def test_an_abandoned_stream_records_the_tokens_it_was_billed_and_nothing_more(
    spans, clean_handler
):
    model = FakeChat(
        chunks=[
            chunk("a", input_tokens=10, output_tokens=1, total_tokens=11),
            chunk("b", input_tokens=0, output_tokens=2, total_tokens=2),
        ]
    )

    with ags.conversation("c-abandon"):
        with ags.turn():
            stream = model.stream("hi")
            assert next(stream).content == "a"
            stream.close()

    (llm,) = llm_spans(spans)
    assert llm.attributes[LLMAttributes.OUTPUT_TOKENS] == 1
    assert llm.attributes[LLMAttributes.STREAMING] is True
    assert clean_handler._llm_runs == {}


def test_a_failed_call_that_billed_nothing_records_no_span(spans, clean_handler):
    """A provider error is not an LLM call. The OpenAI and Anthropic patches
    emit nothing here, and a 0-token span carries no error marker to tell it
    apart from a real one."""
    with ags.conversation("c-failed"):
        with ags.turn():
            with pytest.raises(RuntimeError):
                FakeChat(boom=RuntimeError("provider down")).invoke("hi")

    assert llm_spans(spans) == []
    assert clean_handler._llm_runs == {}


def test_a_stream_that_dies_mid_flight_keeps_the_tokens_it_produced(
    spans, clean_handler
):
    model = FakeChat(
        chunks=[chunk("a", input_tokens=10, output_tokens=1, total_tokens=11)],
        boom=RuntimeError("connection reset"),
    )

    with ags.conversation("c-stream-died"):
        with ags.turn():
            with pytest.raises(RuntimeError):
                list(model.stream("hi"))

    (llm,) = llm_spans(spans)
    assert llm.attributes[LLMAttributes.INPUT_TOKENS] == 10
    assert clean_handler._llm_runs == {}


def test_a_tool_whose_end_never_fires_does_not_grow_forever(spans, clean_handler):
    with ags.conversation("c-unbounded"):
        with ags.turn():
            for _ in range(langchain_handler._MAX_PENDING_RUNS + 500):
                clean_handler.on_tool_start(
                    {"name": "never-ends"}, "x", run_id=uuid.uuid4()
                )
                clean_handler.on_chat_model_start(
                    {}, [[]], run_id=uuid.uuid4(), metadata={"ls_provider": "bedrock"}
                )

    assert len(clean_handler._tool_spans) == langchain_handler._MAX_PENDING_RUNS
    assert len(clean_handler._llm_runs) == langchain_handler._MAX_PENDING_RUNS


def test_an_end_without_a_start_is_a_no_op(spans, clean_handler):
    with ags.conversation("c-orphan"):
        with ags.turn():
            clean_handler.on_llm_end(None, run_id=uuid.uuid4())
            clean_handler.on_tool_end("x", run_id=uuid.uuid4())

    assert llm_spans(spans) == []
    assert tool_spans(spans) == []


def test_a_completed_call_leaves_nothing_pending(spans, clean_handler):
    with ags.conversation("c-pending"):
        with ags.turn():
            FakeChat(usage=LC_USAGE).invoke("hi")
            add.invoke({"a": 1, "b": 2})

    assert clean_handler._llm_runs == {}
    assert clean_handler._tool_spans == {}


# ---------------------------------------------------------------------------
# 6. No conversation scope
# ---------------------------------------------------------------------------


def test_a_call_outside_a_conversation_records_nothing(spans, clean_handler):
    assert FakeChat(usage=LC_USAGE).invoke("hi").content == "hello"
    assert add.invoke({"a": 1, "b": 2}) == 3

    assert spans.get_finished_spans() == ()
    assert clean_handler._llm_runs == {}
    assert clean_handler._tool_spans == {}


def test_a_disabled_conversation_records_nothing(spans):
    with ags.conversation("c-off", enabled=False):
        with ags.turn():
            FakeChat(usage=LC_USAGE).invoke("hi")
            add.invoke({"a": 1, "b": 2})

    assert spans.get_finished_spans() == ()


def test_a_stream_outside_a_conversation_is_untouched(spans):
    model = FakeChat(chunks=[chunk("a"), chunk("b")])

    assert [c.content for c in model.stream("hi")] == ["a", "b"]
    assert spans.get_finished_spans() == ()


def test_a_run_that_starts_before_its_conversation_records_nothing(
    spans, clean_handler
):
    run_id = uuid.uuid4()
    clean_handler.on_chat_model_start(
        {}, [[]], run_id=run_id, metadata={"ls_provider": "bedrock"}
    )

    with ags.conversation("c-late"):
        with ags.turn():
            clean_handler.on_llm_end(None, run_id=run_id)

    assert llm_spans(spans) == []


# ---------------------------------------------------------------------------
# 7. Tool payloads
# ---------------------------------------------------------------------------


def test_tool_arguments_keep_their_structure(spans):
    with ags.conversation("c-args"):
        with ags.turn():
            add.invoke({"a": 1, "b": 2})

    (span,) = tool_spans(spans)
    assert span.attributes[ToolAttributes.NAME] == "add"
    assert span.attributes[ToolAttributes.ARGUMENTS] == '{"a": 1, "b": 2}'
    assert span.attributes[ToolAttributes.RESPONSE] == "3"


def test_an_agent_driven_call_records_the_result_not_its_envelope(spans):
    """Every agent invokes tools with a ToolCall, and LangChain then wraps the
    result in a ToolMessage. ``agentsight.tool.response`` is client-facing."""
    call = {"name": "add", "args": {"a": 1, "b": 2}, "id": "call_1", "type": "tool_call"}

    with ags.conversation("c-agent-tool"):
        with ags.turn():
            add.invoke(call)

    (span,) = tool_spans(spans)
    assert span.attributes[ToolAttributes.ARGUMENTS] == '{"a": 1, "b": 2}'
    assert span.attributes[ToolAttributes.RESPONSE] == "3"


def test_a_handled_tool_failure_is_recorded_as_a_failure(spans):
    """``handle_tool_error`` is how an agent keeps going after a tool fails;
    the run ends through ``on_tool_end`` carrying ``status="error"``."""
    call = {"name": "handled", "args": {"a": 1}, "id": "call_2", "type": "tool_call"}

    with ags.conversation("c-handled-error"):
        with ags.turn():
            handled.invoke(call)

    (span,) = tool_spans(spans)
    assert span.status.status_code is StatusCode.ERROR
    assert "upstream refused" in span.attributes[ToolAttributes.ERROR]
    assert ToolAttributes.RESPONSE not in span.attributes


def test_an_unhandled_tool_failure_is_recorded_as_a_failure(spans):
    with ags.conversation("c-unhandled-error"):
        with ags.turn():
            with pytest.raises(ValueError):
                explode.invoke({"a": 1})

    (span,) = tool_spans(spans)
    assert span.status.status_code is StatusCode.ERROR
    assert "tool blew up" in span.attributes[ToolAttributes.ERROR]


# ---------------------------------------------------------------------------
# 8. Async and threads
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_async_calls_are_recorded_once(spans):
    with ags.conversation("c-async"):
        with ags.turn():
            await FakeChat(usage=LC_USAGE).ainvoke("hi")
            assert await add.ainvoke({"a": 1, "b": 2}) == 3

    assert len(llm_spans(spans)) == 1
    assert len(tool_spans(spans)) == 1


@pytest.mark.asyncio
async def test_an_async_stream_is_recorded_once(spans):
    model = FakeChat(chunks=[chunk("a", input_tokens=10, output_tokens=1, total_tokens=11)])

    with ags.conversation("c-astream"):
        with ags.turn():
            seen = [c.content async for c in model.astream("hi")]

    assert seen == ["a"]
    (llm,) = llm_spans(spans)
    assert llm.attributes[LLMAttributes.STREAMING] is True


def test_a_user_started_thread_still_produces_spans(spans):
    """A real ContextVar hook would be empty here and fire nothing."""
    import threading

    def worker():
        with ags.conversation("c-thread"):
            with ags.turn():
                add.invoke({"a": 1, "b": 2})

    thread = threading.Thread(target=worker)
    thread.start()
    thread.join()

    assert len(tool_spans(spans)) == 1
