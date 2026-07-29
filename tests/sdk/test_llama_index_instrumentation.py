"""Adversarial verification of the LlamaIndex handler.

Everything here drives the *real* dispatcher — a real ``CustomLLM`` subclass, a
real ``FunctionTool``, real ``dispatcher.span`` brackets. Asserting against
hand-built events would only prove that the handler agrees with this file's
guess about LlamaIndex, and the expensive mistakes in an integration like this
one are always in the guess.

There is no network and no key: the LLM's response object is a stand-in for the
provider's, which is all the handler ever reads.
"""

import asyncio
import logging
from typing import Any, Sequence

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

import agentsight.sdk as ags
from agentsight.sdk import core
from agentsight.sdk.instrumentation import llama_index_handler as lih
from agentsight.sdk.processors import TurnBufferingProcessor
from agentsight.sdk.semconv import (
    LLMAttributes,
    SpanAttributes,
    SpanKind,
    ToolAttributes,
)

pytest.importorskip("llama_index.core")

from llama_index.core.base.llms.types import (  # noqa: E402
    ChatMessage,
    ChatResponse,
    ChatResponseAsyncGen,
    ChatResponseGen,
    CompletionResponse,
    CompletionResponseGen,
    LLMMetadata,
)
from llama_index.core.instrumentation import get_dispatcher  # noqa: E402
from llama_index.core.llms.callbacks import (  # noqa: E402
    llm_chat_callback,
    llm_completion_callback,
)
from llama_index.core.llms.custom import CustomLLM  # noqa: E402
from llama_index.core.tools import FunctionTool  # noqa: E402
from llama_index.core.tools.types import (  # noqa: E402
    AsyncBaseTool,
    ToolMetadata,
    ToolOutput,
)

logger = logging.getLogger("agentsight-test")


# ---------------------------------------------------------------------------
# A provider that never leaves the process
# ---------------------------------------------------------------------------


class Detail:
    def __init__(self, **fields: int):
        self.__dict__.update(fields)


#: OpenAI's shape: ``prompt_tokens`` INCLUDES the 40 cached ones, and
#: ``reasoning_tokens`` is a slice of ``completion_tokens``, not an addition.
USAGE = Detail(
    prompt_tokens=100,
    completion_tokens=40,
    total_tokens=140,
    prompt_tokens_details=Detail(cached_tokens=40, audio_tokens=0),
    completion_tokens_details=Detail(reasoning_tokens=5, audio_tokens=0),
)


class Raw:
    """Stands in for ``openai.types.chat.ChatCompletion`` and friends."""

    def __init__(self, model: str = "fake-1", usage: Any = USAGE):
        self.model = model
        self.usage = usage


def response(content: str = "hello", raw: Any = None) -> ChatResponse:
    # ``delta`` as well as ``message``: a streaming chunk carries both, and the
    # transparency tests compare deltas because that is what a caller reads.
    return ChatResponse(
        message=ChatMessage(role="assistant", content=content),
        delta=content,
        raw=Raw() if raw is None else raw,
    )


class FakeLLM(CustomLLM):
    """Implements every entry point itself, so nothing is derived."""

    fails: bool = False
    vendor: str = "fakevendor_llm"

    @classmethod
    def class_name(cls) -> str:
        # Instance-level, so a test can claim to be a vendor we patch.
        return "fakevendor_llm"

    def to_dict(self, **kwargs: Any) -> dict:
        return {"class_name": self.vendor, "model": "fake-1"}

    @property
    def metadata(self) -> LLMMetadata:
        return LLMMetadata(model_name="fake-1")

    @llm_chat_callback()
    def chat(self, messages: Sequence[ChatMessage], **kwargs: Any) -> ChatResponse:
        if self.fails:
            raise RuntimeError("provider down")
        return response()

    @llm_chat_callback()
    def stream_chat(
        self, messages: Sequence[ChatMessage], **kwargs: Any
    ) -> ChatResponseGen:
        def generate() -> ChatResponseGen:
            yield response("he", raw=Raw(usage=None))
            yield response("hello")

        return generate()

    @llm_chat_callback()
    async def achat(
        self, messages: Sequence[ChatMessage], **kwargs: Any
    ) -> ChatResponse:
        if self.fails:
            raise RuntimeError("provider down")
        return response()

    @llm_chat_callback()
    async def astream_chat(
        self, messages: Sequence[ChatMessage], **kwargs: Any
    ) -> ChatResponseAsyncGen:
        async def generate() -> ChatResponseAsyncGen:
            yield response("he", raw=Raw(usage=None))
            yield response("hello")

        return generate()

    @llm_completion_callback()
    def complete(
        self, prompt: str, formatted: bool = False, **kwargs: Any
    ) -> CompletionResponse:
        return CompletionResponse(text="hello", raw=Raw())

    @llm_completion_callback()
    def stream_complete(
        self, prompt: str, formatted: bool = False, **kwargs: Any
    ) -> CompletionResponseGen:
        def generate() -> CompletionResponseGen:
            yield CompletionResponse(text="hello", delta="hello", raw=Raw())

        return generate()


class CompletionOnlyLLM(CustomLLM):
    """The documented way to add a model: implement completion, get chat free.

    LlamaIndex derives ``chat`` from ``complete`` here, and both halves announce
    themselves with the same response object.
    """

    @classmethod
    def class_name(cls) -> str:
        return "fakevendor_llm"

    @property
    def metadata(self) -> LLMMetadata:
        return LLMMetadata(model_name="fake-1")

    @llm_completion_callback()
    def complete(
        self, prompt: str, formatted: bool = False, **kwargs: Any
    ) -> CompletionResponse:
        return CompletionResponse(text="hello", raw=Raw())

    @llm_completion_callback()
    def stream_complete(
        self, prompt: str, formatted: bool = False, **kwargs: Any
    ) -> CompletionResponseGen:
        def generate() -> CompletionResponseGen:
            yield CompletionResponse(text="hello", delta="hello", raw=Raw())

        return generate()


class AnthropicishLLM(CustomLLM):
    """Anthropic's shape: the three input counts are disjoint."""

    @classmethod
    def class_name(cls) -> str:
        return "anthropic_llm"

    @property
    def metadata(self) -> LLMMetadata:
        return LLMMetadata(model_name="claude-sonnet-4-5")

    @llm_chat_callback()
    def chat(self, messages: Sequence[ChatMessage], **kwargs: Any) -> ChatResponse:
        return ChatResponse(
            message=ChatMessage(role="assistant", content="hello"),
            raw={
                "model": "claude-sonnet-4-5",
                "usage": {
                    "input_tokens": 60,
                    "output_tokens": 40,
                    "cache_read_input_tokens": 40,
                    "cache_creation_input_tokens": 10,
                },
            },
        )

    @llm_completion_callback()
    def complete(self, prompt: str, formatted: bool = False, **kwargs: Any) -> Any:
        raise NotImplementedError

    @llm_completion_callback()
    def stream_complete(self, prompt: str, formatted: bool = False, **kwargs: Any):
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


def greet(name: str) -> str:
    """Greet somebody."""
    return "hi " + name


def detonate(name: str) -> str:
    """Always raises."""
    raise ValueError("tool blew up")


class ReportsFailureTool(AsyncBaseTool):
    """A tool that returns its failure instead of raising it."""

    @property
    def metadata(self) -> ToolMetadata:
        return ToolMetadata(description="fails politely", name="polite")

    def call(self, **kwargs: Any) -> ToolOutput:
        return ToolOutput(
            content="could not do it",
            tool_name="polite",
            raw_input=kwargs,
            raw_output=None,
            is_error=True,
        )

    async def acall(self, **kwargs: Any) -> ToolOutput:
        return self.call(**kwargs)


# ---------------------------------------------------------------------------
# Harness
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session", autouse=True)
def installed():
    """Installing twice is the point: the dispatcher appends with no dedup."""
    lih.install_llama_index(logger)
    lih.install_llama_index(logger)


@pytest.fixture(scope="session")
def handlers(installed):
    dispatcher = get_dispatcher()
    event = [
        h
        for h in dispatcher.event_handlers
        if type(h).__name__ == "AgentSightEventHandler"
    ]
    span = [
        h
        for h in dispatcher.span_handlers
        if type(h).__name__ == "AgentSightSpanHandler"
    ]
    return event, span


@pytest.fixture
def pending(handlers):
    """The in-flight map, reachable only through the handler's closure."""
    (event_handler,), _ = handlers
    for cell in event_handler.handle.__func__.__closure__ or ():
        if isinstance(cell.cell_contents, lih._PendingCalls):
            return cell.cell_contents
    raise AssertionError("_PendingCalls not found in the handler's closure")


@pytest.fixture
def open_tool_spans(handlers):
    _, (span_handler,) = handlers
    return span_handler.open_spans


@pytest.fixture(autouse=True)
def clean_state(pending, open_tool_spans):
    """Both maps are process-wide; one test's leak must not become another's."""
    pending._entries.clear()
    pending._parents.clear()
    open_tool_spans.clear()
    yield


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


HI = [ChatMessage(role="user", content="hi")]


# ---------------------------------------------------------------------------
# 1. Double counting
# ---------------------------------------------------------------------------


def test_installing_twice_attaches_one_handler_of_each_kind(handlers):
    event, span = handlers
    assert len(event) == 1
    assert len(span) == 1


def test_installing_twice_records_one_span_per_call(spans):
    llm = FakeLLM()

    with ags.conversation("c-double"):
        with ags.turn():
            llm.chat(HI)

    assert len(llm_spans(spans)) == 1


def test_installing_twice_records_one_tool_span_per_call(spans):
    tool = FunctionTool.from_defaults(fn=greet)

    with ags.conversation("c-double-tool"):
        with ags.turn():
            tool.call(name="bob")

    assert len(tool_spans(spans)) == 1


def test_calling_a_tool_directly_does_not_nest_two_spans(spans):
    """``FunctionTool.__call__`` delegates to ``call`` and both carry a span."""
    tool = FunctionTool.from_defaults(fn=greet)

    with ags.conversation("c-call"):
        with ags.turn():
            assert tool(name="bob").content == "hi bob"

    assert len(tool_spans(spans)) == 1


def test_a_chat_derived_from_a_completion_is_billed_once(spans):
    """One API call, two LlamaIndex events, the same usage object on both.

    Every ``CustomLLM`` gets its ``chat`` synthesised out of its ``complete``,
    and recording both halves doubles the tokens and the dollars for a call the
    provider only ever saw once.
    """
    llm = CompletionOnlyLLM()

    with ags.conversation("c-derived"):
        with ags.turn():
            assert llm.chat(HI).message.content == "hello"

    (llm_span,) = llm_spans(spans)
    assert llm_span.attributes[LLMAttributes.INPUT_TOKENS] == 60
    assert llm_span.attributes[LLMAttributes.OPERATION] == "chat"


def test_a_derived_streaming_chat_is_billed_once(spans):
    llm = CompletionOnlyLLM()

    with ags.conversation("c-derived-stream"):
        with ags.turn():
            assert [c.delta for c in llm.stream_chat(HI)] == ["hello"]

    (llm_span,) = llm_spans(spans)
    assert llm_span.attributes[LLMAttributes.INPUT_TOKENS] == 60


def test_a_derived_call_leaves_nothing_behind(spans, pending):
    llm = CompletionOnlyLLM()

    with ags.conversation("c-derived-clean"):
        with ags.turn():
            llm.chat(HI)

    assert pending._entries == {}
    assert pending._parents == {}


def test_two_independent_calls_are_two_spans(spans):
    """The nesting guard must not swallow a second, unrelated call."""
    llm = FakeLLM()

    with ags.conversation("c-two"):
        with ags.turn():
            llm.chat(HI)
            llm.chat(HI)

    assert len(llm_spans(spans)) == 2


def test_a_tool_calling_an_llm_does_not_suppress_it(spans):
    """A nested LLM call that is not a derived half is still its own call."""
    llm = FakeLLM()

    def ask(question: str) -> str:
        """Ask the model."""
        return str(llm.chat([ChatMessage(role="user", content=question)]))

    tool = FunctionTool.from_defaults(fn=ask)

    with ags.conversation("c-tool-llm"):
        with ags.turn():
            tool.call(question="why")

    assert len(llm_spans(spans)) == 1
    assert len(tool_spans(spans)) == 1


# ---------------------------------------------------------------------------
# 2. Token maths
# ---------------------------------------------------------------------------


def test_openai_cached_tokens_are_subtracted_from_the_input(spans):
    llm = FakeLLM()

    with ags.conversation("c-tokens"):
        with ags.turn():
            llm.chat(HI)

    (llm_span,) = llm_spans(spans)
    assert llm_span.attributes[LLMAttributes.INPUT_TOKENS] == 60
    assert llm_span.attributes[LLMAttributes.CACHE_READ_TOKENS] == 40
    assert llm_span.attributes[LLMAttributes.OUTPUT_TOKENS] == 40


def test_anthropic_cache_counts_are_left_disjoint(spans):
    """Anthropic's ``input_tokens`` already excludes both cache counters."""
    llm = AnthropicishLLM()

    with ags.conversation("c-anthropic"):
        with ags.turn():
            llm.chat(HI)

    (llm_span,) = llm_spans(spans)
    assert llm_span.attributes[LLMAttributes.SYSTEM] == "anthropic"
    assert llm_span.attributes[LLMAttributes.INPUT_TOKENS] == 60
    assert llm_span.attributes[LLMAttributes.CACHE_READ_TOKENS] == 40
    assert llm_span.attributes[LLMAttributes.CACHE_WRITE_TOKENS] == 10


def test_reasoning_tokens_are_reported_but_not_added_to_the_total(spans):
    llm = FakeLLM()

    with ags.conversation("c-reasoning"):
        with ags.turn():
            llm.chat(HI)

    (llm_span,) = llm_spans(spans)
    assert llm_span.attributes[LLMAttributes.REASONING_TOKENS] == 5
    billable = sum(llm_span.attributes.get(n, 0) for n in LLMAttributes.BILLABLE)
    assert billable == 60 + 40 + 40


def test_a_completion_is_its_own_operation(spans):
    llm = FakeLLM()

    with ags.conversation("c-completion"):
        with ags.turn():
            llm.complete("hi")

    (llm_span,) = llm_spans(spans)
    assert llm_span.attributes[LLMAttributes.OPERATION] == "text_completion"


def test_a_streamed_call_is_marked_and_timed(spans):
    llm = FakeLLM()

    with ags.conversation("c-stream"):
        with ags.turn():
            assert [c.delta for c in llm.stream_chat(HI)] == ["he", "hello"]

    (llm_span,) = llm_spans(spans)
    assert llm_span.attributes[LLMAttributes.STREAMING] is True
    assert llm_span.end_time > llm_span.start_time


def test_a_span_covers_the_call_rather_than_an_instant(spans):
    llm = FakeLLM()

    with ags.conversation("c-duration"):
        with ags.turn():
            llm.chat(HI)

    (llm_span,) = llm_spans(spans)
    assert llm_span.end_time > llm_span.start_time


def test_a_system_we_already_patch_is_left_to_its_patch(spans, monkeypatch):
    """Two watchers on one call is two copies of every token."""
    monkeypatch.setattr(lih, "provider_patch_covers", lambda system: system == "openai")
    llm = FakeLLM(vendor="openai_llm")

    with ags.conversation("c-covered"):
        with ags.turn():
            llm.chat(HI)

    assert llm_spans(spans) == []


def test_an_unidentified_vendor_is_not_mistaken_for_an_installed_target(spans):
    """``provider_patch_covers`` keys on the registry's own names, so a
    fallback of "llama_index" would silence every call we cannot identify."""
    assert lih._UNKNOWN_SYSTEM == "unknown"
    from agentsight.sdk.instrumentation import ALL_TARGETS

    assert lih._UNKNOWN_SYSTEM not in ALL_TARGETS


# ---------------------------------------------------------------------------
# 3. Transparency
# ---------------------------------------------------------------------------


def test_a_chat_returns_the_same_object_installed_or_not(spans):
    llm = FakeLLM()

    outside = llm.chat(HI)
    with ags.conversation("c-transparent"):
        with ags.turn():
            inside = llm.chat(HI)

    assert type(inside) is type(outside)
    assert inside.message.content == outside.message.content
    assert type(inside.raw) is Raw


def test_a_stream_yields_the_same_chunks_installed_or_not(spans):
    llm = FakeLLM()

    outside = [c.delta for c in llm.stream_chat(HI)]
    with ags.conversation("c-chunks"):
        with ags.turn():
            inside = [c.delta for c in llm.stream_chat(HI)]

    assert inside == outside == ["he", "hello"]


def test_a_provider_error_is_raised_unchanged(spans):
    llm = FakeLLM(fails=True)

    with ags.conversation("c-error"):
        with ags.turn():
            with pytest.raises(RuntimeError, match="provider down"):
                llm.chat(HI)

    assert llm_spans(spans) == []


def test_a_tool_error_is_raised_unchanged(spans):
    tool = FunctionTool.from_defaults(fn=detonate)

    with ags.conversation("c-tool-error"):
        with ags.turn():
            with pytest.raises(ValueError, match="tool blew up"):
                tool.call(name="bob")

    (tool_span,) = tool_spans(spans)
    assert tool_span.attributes[ToolAttributes.ERROR] == "tool blew up"


def test_a_tool_that_reports_its_failure_is_an_error_span(spans):
    with ags.conversation("c-tool-is-error"):
        with ags.turn():
            out = ReportsFailureTool().call(x=1)

    assert out.is_error is True
    (tool_span,) = tool_spans(spans)
    assert ToolAttributes.ERROR in tool_span.attributes
    assert ToolAttributes.RESPONSE not in tool_span.attributes


def test_tool_arguments_are_the_ones_the_model_chose(spans):
    """``*args, **kwargs`` binding wraps them in ``{"kwargs": {...}}``."""
    tool = FunctionTool.from_defaults(fn=greet)

    with ags.conversation("c-args"):
        with ags.turn():
            tool.call(name="bob")

    (tool_span,) = tool_spans(spans)
    assert tool_span.attributes[ToolAttributes.ARGUMENTS] == '{"name": "bob"}'
    assert tool_span.attributes[ToolAttributes.RESPONSE] == "hi bob"


def test_tools_registered_through_a_tool_spec_are_captured(spans):
    """The shape this whole integration exists for.

    ``webtasy`` registers its tools as ``BaseToolSpec`` methods turned into
    tools by ``to_tool_list()``, which introspects each method's signature and
    docstring to build the schema the model sees. Decorating them with
    ``@agentsight.tool`` would mean editing 15+ classes *and* changing what the
    model is shown — so if the handler does not capture these, a real LlamaIndex
    agent has no tool tracking at all.
    """
    from llama_index.core.tools.tool_spec.base import BaseToolSpec

    class AccountToolSpec(BaseToolSpec):
        spec_functions = ["lookup_account", "escalate"]

        def lookup_account(self, user_id: str) -> str:
            """Find an account by id."""
            return f"account {user_id}: active"

        def escalate(self, reason: str) -> str:
            """Hand the conversation to a human."""
            return f"escalated: {reason}"

    tools = {tool.metadata.name: tool for tool in AccountToolSpec().to_tool_list()}
    assert set(tools) == {"lookup_account", "escalate"}

    with ags.conversation("c-toolspec"):
        with ags.turn():
            tools["lookup_account"].call(user_id="user-12345")
            tools["escalate"].call(reason="explicit user request")

    recorded = {
        span.attributes[ToolAttributes.NAME]: span.attributes
        for span in tool_spans(spans)
    }
    assert set(recorded) == {"lookup_account", "escalate"}
    assert recorded["lookup_account"][ToolAttributes.ARGUMENTS] == (
        '{"user_id": "user-12345"}'
    ), "the bound `self` must not reach ActionLog.tools_used"
    assert "active" in recorded["lookup_account"][ToolAttributes.RESPONSE]
    # Human Escalation Rate keys off this exact action name.
    assert recorded["escalate"][ToolAttributes.NAME] == "escalate"


@pytest.mark.asyncio
async def test_the_async_paths_record_the_same_thing(spans):
    llm = FakeLLM()
    tool = FunctionTool.from_defaults(fn=greet)

    with ags.conversation("c-async"):
        with ags.turn():
            await llm.achat(HI)
            await tool.acall(name="ann")
            stream = await llm.astream_chat(HI)
            assert [c.delta async for c in stream] == ["he", "hello"]

    assert len(llm_spans(spans)) == 2
    assert len(tool_spans(spans)) == 1
    assert llm_spans(spans)[-1].attributes[LLMAttributes.STREAMING] is True


# ---------------------------------------------------------------------------
# 4. Failure isolation
# ---------------------------------------------------------------------------


def explode(*args: Any, **kwargs: Any):
    raise RuntimeError("telemetry is on fire")


def test_a_broken_recorder_cannot_break_a_chat(spans, monkeypatch):
    monkeypatch.setattr(lih, "record_llm_call", explode)
    llm = FakeLLM()

    with ags.conversation("c-broken"):
        with ags.turn():
            assert llm.chat(HI).message.content == "hello"


def test_a_broken_recorder_cannot_break_a_stream(spans, monkeypatch):
    monkeypatch.setattr(lih, "record_llm_call", explode)
    llm = FakeLLM()

    with ags.conversation("c-broken-stream"):
        with ags.turn():
            assert [c.delta for c in llm.stream_chat(HI)] == ["he", "hello"]


def test_a_broken_span_opener_cannot_break_a_tool(spans, monkeypatch):
    monkeypatch.setattr(lih, "start_tool_span", explode)
    tool = FunctionTool.from_defaults(fn=greet)

    with ags.conversation("c-broken-start"):
        with ags.turn():
            assert tool.call(name="bob").content == "hi bob"

    assert tool_spans(spans) == []


def test_a_broken_span_closer_cannot_break_a_tool(spans, monkeypatch):
    monkeypatch.setattr(lih, "end_tool_span", explode)
    tool = FunctionTool.from_defaults(fn=greet)

    with ags.conversation("c-broken-end"):
        with ags.turn():
            assert tool.call(name="bob").content == "hi bob"


def test_a_broken_span_closer_does_not_leak_an_open_span(
    spans, monkeypatch, open_tool_spans
):
    """``prepare_to_exit_span`` returning the span is the only thing that makes
    the dispatcher forget it, so it has to return one even when ending failed."""
    monkeypatch.setattr(lih, "end_tool_span", explode)
    tool = FunctionTool.from_defaults(fn=greet)

    with ags.conversation("c-broken-end-leak"):
        with ags.turn():
            for _ in range(3):
                tool.call(name="bob")

    assert open_tool_spans == {}


def test_a_broken_capturing_check_cannot_break_a_chat(spans, monkeypatch):
    monkeypatch.setattr(lih, "capturing", explode)
    llm = FakeLLM()

    with ags.conversation("c-broken-check"):
        with ags.turn():
            assert llm.chat(HI).message.content == "hello"


# ---------------------------------------------------------------------------
# 5. Leaks
# ---------------------------------------------------------------------------


def test_a_failed_chat_does_not_leak_a_pending_call(spans, pending):
    """No End event, and no ExceptionEvent either — the non-streaming path
    reports a failure only as a dropped span."""
    llm = FakeLLM(fails=True)

    with ags.conversation("c-leak-error"):
        with ags.turn():
            with pytest.raises(RuntimeError):
                llm.chat(HI)

    assert pending._entries == {}


@pytest.mark.asyncio
async def test_a_failed_async_chat_does_not_leak_a_pending_call(spans, pending):
    llm = FakeLLM(fails=True)

    with ags.conversation("c-leak-async-error"):
        with ags.turn():
            with pytest.raises(RuntimeError):
                await llm.achat(HI)

    assert pending._entries == {}


def test_an_abandoned_stream_leaks_nothing_and_records_nothing(spans, pending):
    llm = FakeLLM()

    with ags.conversation("c-abandon"):
        with ags.turn():
            stream = llm.stream_chat(HI)
            next(stream)
            stream.close()

    assert pending._entries == {}
    assert llm_spans(spans) == []


def test_a_failed_tool_does_not_leak_an_open_span(spans, open_tool_spans):
    tool = FunctionTool.from_defaults(fn=detonate)

    with ags.conversation("c-leak-tool"):
        with ags.turn():
            with pytest.raises(ValueError):
                tool.call(name="bob")

    assert open_tool_spans == {}


def test_pending_calls_are_bounded(pending):
    for i in range(lih._MAX_PENDING_CALLS * 2):
        pending.start(f"span-{i}", lih._PendingCall(0, None, None, False))
        pending.link(f"span-{i}", f"parent-{i}")

    assert len(pending._entries) == lih._MAX_PENDING_CALLS
    assert len(pending._parents) == lih._MAX_PENDING_CALLS


def test_open_tool_spans_are_bounded(spans, open_tool_spans):
    tool = FunctionTool.from_defaults(fn=greet)
    span_handler = None

    with ags.conversation("c-bounded"):
        with ags.turn():
            # Open spans the dispatcher will never be told about again.
            from llama_index.core.instrumentation import get_dispatcher

            (span_handler,) = [
                h
                for h in get_dispatcher().span_handlers
                if type(h).__name__ == "AgentSightSpanHandler"
            ]
            for i in range(lih._MAX_OPEN_TOOL_SPANS + 10):
                span_handler.span_enter(
                    id_=f"FunctionTool.call-{i}",
                    bound_args=_bound(name="bob"),
                    instance=tool,
                    parent_id=None,
                )

    assert len(open_tool_spans) <= lih._MAX_OPEN_TOOL_SPANS


def _bound(**kwargs: Any):
    import inspect

    def signature(*args: Any, **kw: Any) -> None: ...

    return inspect.signature(signature).bind(**kwargs)


def test_repeated_calls_accumulate_no_state(spans, pending, open_tool_spans):
    llm = FakeLLM()
    tool = FunctionTool.from_defaults(fn=greet)

    with ags.conversation("c-steady"):
        with ags.turn():
            for _ in range(20):
                llm.chat(HI)
                tool.call(name="bob")

    assert pending._entries == {}
    assert pending._parents == {}
    assert open_tool_spans == {}
    assert len(llm_spans(spans)) == 20
    assert len(tool_spans(spans)) == 20


# ---------------------------------------------------------------------------
# 6. No conversation scope
# ---------------------------------------------------------------------------


def test_calls_outside_a_conversation_record_nothing(spans, pending, open_tool_spans):
    llm = FakeLLM()
    tool = FunctionTool.from_defaults(fn=greet)

    assert llm.chat(HI).message.content == "hello"
    assert tool.call(name="bob").content == "hi bob"
    assert [c.delta for c in llm.stream_chat(HI)] == ["he", "hello"]

    assert spans.get_finished_spans() == ()
    assert pending._entries == {}
    assert open_tool_spans == {}


def test_a_disabled_conversation_records_nothing(spans):
    llm = FakeLLM()
    tool = FunctionTool.from_defaults(fn=greet)

    with ags.conversation("c-off", enabled=False):
        with ags.turn():
            llm.chat(HI)
            tool.call(name="bob")

    assert spans.get_finished_spans() == ()


def test_a_tool_that_fails_outside_a_conversation_does_not_crash(spans):
    tool = FunctionTool.from_defaults(fn=detonate)

    with pytest.raises(ValueError, match="tool blew up"):
        tool.call(name="bob")

    assert spans.get_finished_spans() == ()


def test_a_conversation_closing_mid_call_records_nothing_and_leaks_nothing(
    spans, pending
):
    """The turn ends while the stream is still open — a real shape for an
    agent handed off to a background task."""
    llm = FakeLLM()

    with ags.conversation("c-half"):
        with ags.turn():
            stream = llm.stream_chat(HI)
            next(stream)

    # The stream is the user's, and it is untouched: draining it after the
    # scope closed still yields every remaining chunk. An SDK that truncated it
    # would be corrupting an answer to record a metric.
    assert [chunk.delta for chunk in stream] == ["hello"]
    # But the call finished outside any conversation, so there is nothing to
    # attach it to and nothing is invented.
    assert llm_spans(spans) == []
    assert pending._entries == {}


def test_asyncio_run_inside_a_conversation_still_records(spans):
    """``asyncio.run`` copies no context, so the conversation has to survive
    on the contextvar it was set on, not on the dispatcher's."""
    tool = FunctionTool.from_defaults(fn=greet)

    with ags.conversation("c-loop"):
        with ags.turn():
            asyncio.run(tool.acall(name="ann"))

    assert len(tool_spans(spans)) == 1
