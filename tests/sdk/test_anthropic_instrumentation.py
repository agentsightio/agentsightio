"""Adversarial verification of ``anthropic_patch``.

``anthropic`` is not installed here, so these run against a fake module tree
built in ``sys.modules``. The fake is deliberately more faithful than a mock in
the two places the patch reaches into private internals — ``Stream._iterator``
and the ``MessageStreamManager`` -> ``MessageStream`` -> ``Stream`` chain — and
in one place the patch's own docstring does not consider: ``MessageStream.
close()`` closes the HTTP response, not the raw stream underneath it. That is
what ``__exit__`` calls, so it decides whether a half-read ``with client.
messages.stream(...)`` block ever produces a span.

Every test here is written to fail loudly if the patch stops being invisible.
"""

import asyncio
import gc
import logging
import sys
import types
import weakref
from types import SimpleNamespace

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

import agentsight.sdk as ags
from agentsight.sdk import core
from agentsight.sdk.instrumentation import anthropic_patch
from agentsight.sdk.instrumentation.anthropic_patch import install_anthropic
from agentsight.sdk.semconv import LLMAttributes, SpanAttributes, SpanKind

LOGGER = logging.getLogger("agentsight-adversarial")


# ---------------------------------------------------------------------------
# A fake `anthropic`
# ---------------------------------------------------------------------------


def usage(input_tokens, output_tokens, **extra):
    """A ``Usage``. Cache counters are ``Optional[int] = None`` on the real one,
    so a call that touched no cache simply does not carry them."""
    return SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens, **extra)


def message_start(model="claude-sonnet-5", **counters):
    return SimpleNamespace(
        type="message_start",
        message=SimpleNamespace(model=model, usage=usage(**counters)),
    )


def message_delta(**counters):
    """A ``MessageDeltaUsage``: every counter is a running total, never an
    increment."""
    return SimpleNamespace(type="message_delta", usage=SimpleNamespace(**counters))


def text_delta(text="hi"):
    return SimpleNamespace(type="content_block_delta", delta=SimpleNamespace(text=text))


EVENTS = [
    message_start(
        model="claude-sonnet-5-20250101",
        input_tokens=100,
        output_tokens=1,  # priming count, replaced by the first delta
        cache_read_input_tokens=30,
        cache_creation_input_tokens=20,
    ),
    text_delta("hel"),
    message_delta(output_tokens=5),
    text_delta("lo"),
    message_delta(output_tokens=42),
    SimpleNamespace(type="message_stop"),
]

STREAMED = {
    "model": "claude-sonnet-5-20250101",
    "input": 100,
    "output": 42,
    "cache_read": 30,
    "cache_write": 20,
    "streaming": True,
}


def build_kit(stream_via_create=False):
    """The subset of the class tree ``install_anthropic`` imports and patches.

    ``stream_via_create`` builds the one variant the patch's docstring rules
    out: a ``.stream()`` whose manager fires the request through ``create``.
    Nothing in this repo can confirm which shape the installed anthropic has,
    and if it is this one the two patch points see the same stream.
    """

    class Response:
        def __init__(self):
            self.closed = False

        def close(self):
            self.closed = True

    class Stream:
        """``anthropic._streaming.Stream``. ``__iter__``/``__next__`` both read
        ``_iterator``; ``close()`` closes the response, not the iterator."""

        def __init__(self, events):
            self.response = Response()
            self._iterator = iter(events)

        def __iter__(self):
            for item in self._iterator:
                yield item

        def __next__(self):
            return next(self._iterator)

        def close(self):
            self.response.close()
            return "closed"

    class AsyncStream:
        def __init__(self, events):
            self.response = Response()
            self._iterator = self._stream(events)

        async def _stream(self, events):
            for item in events:
                yield item

        async def __aiter__(self):
            async for item in self._iterator:
                yield item

        async def close(self):
            self.response.close()
            return "closed"

    class MessageStream:
        """``anthropic.lib.streaming.MessageStream``: wraps the raw stream and
        keeps its own ``_iterator`` over it. ``close()`` releases the HTTP
        response — it does **not** close the raw stream."""

        def __init__(self, raw_stream):
            self._raw_stream = raw_stream
            self.response = raw_stream.response
            self._iterator = self.__stream__()

        def __stream__(self):
            for event in self._raw_stream:
                yield event

        def __iter__(self):
            for item in self._iterator:
                yield item

        def __next__(self):
            return next(self._iterator)

        def close(self):
            self.response.close()

    class AsyncMessageStream:
        def __init__(self, raw_stream):
            self._raw_stream = raw_stream
            self.response = raw_stream.response
            self._iterator = self.__stream__()

        async def __stream__(self):
            async for event in self._raw_stream:
                yield event

        async def __aiter__(self):
            async for item in self._iterator:
                yield item

        async def close(self):
            self.response.close()

    class MessageStreamManager:
        def __init__(self, api_request):
            self.__api_request = api_request
            self.__stream = None

        def __enter__(self):
            self.__stream = MessageStream(self.__api_request())
            return self.__stream

        def __exit__(self, *exc_info):
            if self.__stream is not None:
                self.__stream.close()

    class AsyncMessageStreamManager:
        def __init__(self, api_request):
            self.__api_request = api_request
            self.__stream = None

        async def __aenter__(self):
            self.__stream = AsyncMessageStream(await self.__api_request())
            return self.__stream

        async def __aexit__(self, *exc_info):
            if self.__stream is not None:
                await self.__stream.close()

    class Messages:
        """Records what it was called with, replies with whatever it was given."""

        def __init__(self):
            self.calls = []
            self.reply = None

        def create(self, *, model, **kwargs):
            self.calls.append(dict(kwargs, model=model))
            if isinstance(self.reply, BaseException):
                raise self.reply
            return self.reply() if callable(self.reply) else self.reply

        def parse(self, *, model, **kwargs):
            # Posts directly, exactly as the patch's docstring claims the real
            # one does. See the report for the risk if that claim is wrong.
            self.calls.append(dict(kwargs, model=model))
            if isinstance(self.reply, BaseException):
                raise self.reply
            return self.reply() if callable(self.reply) else self.reply

        def stream(self, *, model, **kwargs):
            self.calls.append(dict(kwargs, model=model))
            if stream_via_create:
                return MessageStreamManager(
                    lambda: self.create(model=model, stream=True, **kwargs)
                )
            return MessageStreamManager(self.reply)

    class AsyncMessages:
        def __init__(self):
            self.calls = []
            self.reply = None

        async def create(self, *, model, **kwargs):
            self.calls.append(dict(kwargs, model=model))
            if isinstance(self.reply, BaseException):
                raise self.reply
            return self.reply() if callable(self.reply) else self.reply

        async def parse(self, *, model, **kwargs):
            self.calls.append(dict(kwargs, model=model))
            if isinstance(self.reply, BaseException):
                raise self.reply
            return self.reply() if callable(self.reply) else self.reply

        def stream(self, *, model, **kwargs):
            # A plain `def`, as in the real SDK.
            self.calls.append(dict(kwargs, model=model))

            async def api_request():
                if stream_via_create:
                    return await self.create(model=model, stream=True, **kwargs)
                return self.reply()

            return AsyncMessageStreamManager(api_request)

    return SimpleNamespace(
        Stream=Stream,
        AsyncStream=AsyncStream,
        MessageStream=MessageStream,
        AsyncMessageStream=AsyncMessageStream,
        MessageStreamManager=MessageStreamManager,
        AsyncMessageStreamManager=AsyncMessageStreamManager,
        Messages=Messages,
        AsyncMessages=AsyncMessages,
    )


def register(kit):
    """Publish a kit (plus an independent beta twin) as ``anthropic``."""
    beta = build_kit()

    def module(name, **attributes):
        mod = types.ModuleType(name)
        mod.__path__ = []
        for key, value in attributes.items():
            setattr(mod, key, value)
        sys.modules[name] = mod

    module("anthropic")
    module("anthropic.lib")
    module(
        "anthropic.lib.streaming",
        MessageStreamManager=kit.MessageStreamManager,
        AsyncMessageStreamManager=kit.AsyncMessageStreamManager,
        BetaMessageStreamManager=beta.MessageStreamManager,
        BetaAsyncMessageStreamManager=beta.AsyncMessageStreamManager,
    )
    module("anthropic.resources")
    module(
        "anthropic.resources.messages",
        Messages=kit.Messages,
        AsyncMessages=kit.AsyncMessages,
    )
    module("anthropic.resources.beta")
    module(
        "anthropic.resources.beta.messages",
        Messages=beta.Messages,
        AsyncMessages=beta.AsyncMessages,
    )
    kit.beta = beta
    return kit


@pytest.fixture
def anthropic_module():
    """Fresh classes per test, so a patch from one test cannot be mistaken for
    idempotency in the next."""
    from agentsight.sdk.instrumentation import _reset_for_tests

    saved = {n: m for n, m in sys.modules.items() if n.split(".")[0] == "anthropic"}
    kit = register(build_kit())
    _reset_for_tests()
    try:
        yield kit
    finally:
        for name in [n for n in sys.modules if n.split(".")[0] == "anthropic"]:
            del sys.modules[name]
        sys.modules.update(saved)
        _reset_for_tests()


@pytest.fixture
def spans():
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))

    previous = (core._state.enabled, core._state.provider, core._state.tracer)
    core._state.provider = provider
    core._state.tracer = provider.get_tracer("agentsight-adversarial")
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


def tokens(span):
    attributes = span.attributes or {}
    return {
        "model": attributes.get(LLMAttributes.REQUEST_MODEL),
        "input": attributes.get(LLMAttributes.INPUT_TOKENS),
        "output": attributes.get(LLMAttributes.OUTPUT_TOKENS),
        "cache_read": attributes.get(LLMAttributes.CACHE_READ_TOKENS),
        "cache_write": attributes.get(LLMAttributes.CACHE_WRITE_TOKENS),
        "streaming": attributes.get(LLMAttributes.STREAMING),
    }


def call(**overrides):
    return dict({"model": "claude-sonnet-5", "max_tokens": 64, "messages": []}, **overrides)


#: What ``with_raw_response`` stamps on the request before calling ``create``.
#: A literal rather than the patch's constant on purpose: it is the wire name
#: that has to match, not two copies of one variable agreeing with each other.
RAW_HEADER = {"X-Stainless-Raw-Response": "true"}


class RawResponse:
    """``LegacyAPIResponse``, reduced to the two properties the patch relies
    on: ``parse()`` memoises, and on a ``stream=True`` request it reads no
    bytes — the body is built lazily on the first call."""

    def __init__(self, build):
        self._build = build
        self._parsed = None

    def parse(self):
        if self._parsed is None:
            self._parsed = self._build()
        return self._parsed


# ---------------------------------------------------------------------------
# 1. Double counting
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("method", ["create", "parse"])
def test_two_installs_emit_exactly_one_span(anthropic_module, spans, method):
    install_anthropic(LOGGER)
    install_anthropic(LOGGER)

    client = anthropic_module.Messages()
    client.reply = SimpleNamespace(model="claude-sonnet-5", usage=usage(10, 5))
    with ags.conversation("c"):
        getattr(client, method)(**call())

    assert len(llm_spans(spans)) == 1
    assert tokens(llm_spans(spans)[0])["output"] == 5


def test_two_installs_do_not_double_streamed_tokens(anthropic_module, spans):
    install_anthropic(LOGGER)
    install_anthropic(LOGGER)

    client = anthropic_module.Messages()
    client.reply = lambda: anthropic_module.Stream(EVENTS)
    with ags.conversation("c"):
        assert list(client.create(**call(stream=True))) == EVENTS

    assert len(llm_spans(spans)) == 1
    assert tokens(llm_spans(spans)[0]) == STREAMED


def test_a_stream_reached_by_two_patch_points_is_recorded_once(spans):
    """``.stream()`` and ``create()`` are patched independently.

    If a release routes ``.stream()`` through ``create(stream=True)`` — the
    shape ``openai_patch`` documents for its own SDK — both wrappers hand the
    same ``Stream`` to ``_watch_stream`` and one call mints two spans with the
    full token count each. Nothing in ``already_patched`` covers this: it
    guards callables, and the thing being instrumented twice is an object.
    """
    from agentsight.sdk.instrumentation import _reset_for_tests

    saved = {n: m for n, m in sys.modules.items() if n.split(".")[0] == "anthropic"}
    kit = register(build_kit(stream_via_create=True))
    _reset_for_tests()
    try:
        install_anthropic(LOGGER)
        client = kit.Messages()
        client.reply = lambda: kit.Stream(EVENTS)

        with ags.conversation("c"):
            with client.stream(**call()) as stream:
                assert list(stream) == EVENTS

        assert len(llm_spans(spans)) == 1
        assert tokens(llm_spans(spans)[0]) == STREAMED
    finally:
        for name in [n for n in sys.modules if n.split(".")[0] == "anthropic"]:
            del sys.modules[name]
        sys.modules.update(saved)
        _reset_for_tests()


# ---------------------------------------------------------------------------
# 2. Token maths
# ---------------------------------------------------------------------------


def test_anthropic_cache_counters_are_disjoint_from_input(anthropic_module, spans):
    """The mirror image of OpenAI, and the reason ``from_anthropic`` exists.

    OpenAI's ``prompt_tokens`` contains its cached tokens, so they are
    subtracted out. Anthropic's ``input_tokens`` already excludes both cache
    counts, so subtracting again would under-report billable input by the whole
    cache read.
    """
    install_anthropic(LOGGER)
    client = anthropic_module.Messages()
    client.reply = SimpleNamespace(
        model="claude-sonnet-5",
        usage=usage(
            input_tokens=100,
            output_tokens=42,
            cache_read_input_tokens=30,
            cache_creation_input_tokens=20,
        ),
    )

    with ags.conversation("c"):
        client.create(**call())

    recorded = tokens(llm_spans(spans)[0])
    assert recorded["input"] == 100
    assert recorded["cache_read"] == 30
    assert recorded["cache_write"] == 20
    # The three are disjoint billable lines: 150 tokens were paid for, and the
    # uncached input is not 70.
    assert recorded["input"] + recorded["cache_read"] + recorded["cache_write"] == 150


def test_thinking_tokens_are_never_folded_into_output(anthropic_module, spans):
    """Reasoning is a *subset* of output, so it must never be added to it.

    Current anthropic carries ``usage.output_tokens_details.thinking_tokens``.
    It is not recorded, because ``from_anthropic`` in base.py hardcodes
    ``reasoning_tokens=0`` and base.py is another engineer's file — reported
    rather than patched around here. What this test pins down is the invariant
    that must hold either way: whatever happens to the breakdown, the billable
    output count stays exactly what the provider reported.
    """
    install_anthropic(LOGGER)
    client = anthropic_module.Messages()
    client.reply = SimpleNamespace(
        model="claude-sonnet-5",
        usage=usage(
            input_tokens=100,
            output_tokens=42,
            output_tokens_details=SimpleNamespace(thinking_tokens=30),
        ),
    )

    with ags.conversation("c"):
        client.create(**call())

    attributes = llm_spans(spans)[0].attributes
    assert attributes[LLMAttributes.OUTPUT_TOKENS] == 42
    assert attributes.get(LLMAttributes.REASONING_TOKENS, 0) <= 42


def test_streamed_output_is_overwritten_not_summed(anthropic_module, spans):
    install_anthropic(LOGGER)
    client = anthropic_module.Messages()
    client.reply = lambda: anthropic_module.Stream(EVENTS)

    with ags.conversation("c"):
        list(client.create(**call(stream=True)))

    # deltas of 5 then 42 are cumulative totals: not 47, and not 1+5+42.
    assert tokens(llm_spans(spans)[0])["output"] == 42


def test_a_stream_that_never_reported_usage_is_marked_unknown(anthropic_module, spans):
    """0/0 on a stream that carried no usage event is an *unknown*, not a zero.

    A stream can end without one — it died before ``message_start``, or was
    closed before anything was read. The recorder's accumulator is a dict, so
    the "nothing arrived" case is an empty dict rather than None, and the
    marker has to survive that: without it the backend prices the row as an
    authoritative $0 and ``unreported_calls`` stays at zero, which is the one
    number that would have said the counts are not to be trusted.
    """
    install_anthropic(LOGGER)
    client = anthropic_module.Messages()
    client.reply = lambda: anthropic_module.Stream([text_delta("hi")])

    with ags.conversation("c"):
        assert [e.delta.text for e in client.create(**call(stream=True))] == ["hi"]

    attributes = llm_spans(spans)[0].attributes
    assert attributes[LLMAttributes.INPUT_TOKENS] == 0
    assert attributes[LLMAttributes.OUTPUT_TOKENS] == 0
    assert attributes[LLMAttributes.USAGE_REPORTED] is False


def test_a_stream_that_reported_usage_carries_no_unknown_marker(anthropic_module, spans):
    """The marker's absence is the statement that the counts are real."""
    install_anthropic(LOGGER)
    client = anthropic_module.Messages()
    client.reply = lambda: anthropic_module.Stream(EVENTS)

    with ags.conversation("c"):
        list(client.create(**call(stream=True)))

    assert LLMAttributes.USAGE_REPORTED not in llm_spans(spans)[0].attributes


def test_a_streamed_call_keeps_the_alias_the_caller_asked_for(anthropic_module, spans):
    """``message_start`` overwrites the model with the dated snapshot that ran.

    That id is the one cost is keyed on and must not move — but overwriting it
    used to be the end of the alias the caller actually typed, on every
    streamed call. "Which of my model aliases is expensive" is unanswerable
    without it, and streaming is most of an agent's traffic.
    """
    install_anthropic(LOGGER)
    client = anthropic_module.Messages()
    client.reply = lambda: anthropic_module.Stream(EVENTS)

    with ags.conversation("c"):
        list(client.create(**call(model="claude-sonnet-5", stream=True)))

    attributes = llm_spans(spans)[0].attributes
    assert attributes[LLMAttributes.REQUEST_MODEL] == "claude-sonnet-5-20250101"
    assert attributes[LLMAttributes.REQUESTED_MODEL] == "claude-sonnet-5"


def test_no_requested_model_on_a_stream_when_the_two_agree(anthropic_module, spans):
    """Present only on the difference, exactly as on the non-streamed path."""
    install_anthropic(LOGGER)
    client = anthropic_module.Messages()
    client.reply = lambda: anthropic_module.Stream(
        [message_start(model="claude-sonnet-5", input_tokens=10, output_tokens=1)]
    )

    with ags.conversation("c"):
        list(client.create(**call(model="claude-sonnet-5", stream=True)))

    assert LLMAttributes.REQUESTED_MODEL not in llm_spans(spans)[0].attributes


# ---------------------------------------------------------------------------
# 3. Leaks — a stream that is closed rather than exhausted
# ---------------------------------------------------------------------------


def test_half_read_stream_block_records_before_the_conversation_ends(
    anthropic_module, spans
):
    """``with client.messages.stream(...)`` + ``break`` is the common shape.

    ``__exit__`` closes the stream, which leaves the instrumented generator
    suspended. Nothing runs its ``finally`` until the collector reaches it, and
    the manager is still referenced by the caller's frame — so the span is not
    emitted here. In a real app the collector gets there after the conversation
    scope has closed, and ``capturing()`` then drops the span entirely: the
    tokens are not late, they are gone.
    """
    install_anthropic(LOGGER)
    client = anthropic_module.Messages()
    client.reply = lambda: anthropic_module.Stream(EVENTS)

    with ags.conversation("c"):
        manager = client.stream(**call())
        with manager as stream:
            for event in stream:
                if getattr(event, "type", None) == "message_delta":
                    break

        assert len(llm_spans(spans)) == 1
        assert tokens(llm_spans(spans)[0]) == dict(STREAMED, output=5)


def test_half_read_async_stream_block_records_before_the_conversation_ends(
    anthropic_module, spans
):
    """Async is the worse half of the same bug.

    An async generator is finalized by a task the loop schedules, normally
    during shutdown and in a context that no longer carries the conversation —
    so the span is not merely late, it is discarded by ``capturing()``.
    """
    install_anthropic(LOGGER)
    client = anthropic_module.AsyncMessages()
    client.reply = lambda: anthropic_module.AsyncStream(EVENTS)

    async def go():
        with ags.conversation("c"):
            async with client.stream(**call()) as stream:
                async for event in stream:
                    if getattr(event, "type", None) == "message_delta":
                        break
            return len(llm_spans(spans)), tokens(llm_spans(spans)[0]) if llm_spans(
                spans
            ) else None

    count, recorded = asyncio.run(go())
    assert count == 1
    assert recorded == dict(STREAMED, output=5)


def test_abandoned_streamed_create_records_on_close(anthropic_module, spans):
    install_anthropic(LOGGER)
    client = anthropic_module.AsyncMessages()
    client.reply = lambda: anthropic_module.AsyncStream(EVENTS)

    async def go():
        with ags.conversation("c"):
            stream = await client.create(**call(stream=True))
            async for event in stream:
                if getattr(event, "type", None) == "message_delta":
                    break
            await stream.close()
            return len(llm_spans(spans))

    assert asyncio.run(go()) == 1
    assert tokens(llm_spans(spans)[0])["output"] == 5


def test_closing_twice_does_not_double_the_span(anthropic_module, spans):
    install_anthropic(LOGGER)
    client = anthropic_module.Messages()
    client.reply = lambda: anthropic_module.Stream(EVENTS)

    with ags.conversation("c"):
        with client.stream(**call()) as stream:
            for _ in stream:
                break
            stream.close()  # the user closes, then __exit__ closes again

    assert len(llm_spans(spans)) == 1


def test_exhausted_stream_then_close_records_once(anthropic_module, spans):
    install_anthropic(LOGGER)
    client = anthropic_module.Messages()
    client.reply = lambda: anthropic_module.Stream(EVENTS)

    with ags.conversation("c"):
        with client.stream(**call()) as stream:
            assert list(stream) == EVENTS

    assert len(llm_spans(spans)) == 1
    assert tokens(llm_spans(spans)[0]) == STREAMED


def test_a_dropped_stream_records_without_waiting_for_the_cyclic_collector(
    anthropic_module, spans
):
    """Dropping a half-read stream must still record on the spot.

    Instrumenting a stream must not put it in a reference cycle: a cycle
    survives the refcount drop and waits for a collector pass that, in a real
    app, lands after the conversation scope has closed — at which point the
    span is discarded rather than merely late. No ``gc.collect()`` here on
    purpose; that is the whole assertion.
    """
    install_anthropic(LOGGER)
    client = anthropic_module.Messages()
    client.reply = lambda: anthropic_module.Stream(EVENTS)

    with ags.conversation("c"):
        stream = client.create(**call(stream=True))
        for event in stream:
            if getattr(event, "type", None) == "message_delta":
                break
        del stream, event

        assert len(llm_spans(spans)) == 1
        assert tokens(llm_spans(spans)[0]) == dict(STREAMED, output=5)


def test_instrumented_stream_is_not_retained_after_the_call(anthropic_module, spans):
    """Nothing here may hold a stream alive — no registry, no module-level dict."""
    install_anthropic(LOGGER)
    client = anthropic_module.Messages()
    client.reply = lambda: anthropic_module.Stream(EVENTS)

    with ags.conversation("c"):
        stream = client.create(**call(stream=True))
        for _ in stream:
            break
        dead = weakref.ref(stream)
        del stream

    gc.collect()
    assert dead() is None


# ---------------------------------------------------------------------------
# 4. Transparency
# ---------------------------------------------------------------------------


def test_streamed_events_are_byte_identical_with_and_without_the_sdk(
    anthropic_module, spans
):
    """Not just equal — the same objects, in the same order, with nothing
    swallowed and nothing injected."""
    client = anthropic_module.Messages()
    client.reply = lambda: anthropic_module.Stream(EVENTS)
    before = list(client.create(**call(stream=True)))

    install_anthropic(LOGGER)
    with ags.conversation("c"):
        after = list(client.create(**call(stream=True)))

    assert len(after) == len(before) == len(EVENTS)
    assert all(a is b for a, b in zip(after, EVENTS))


def test_the_request_is_forwarded_verbatim(anthropic_module, spans):
    install_anthropic(LOGGER)
    client = anthropic_module.Messages()
    client.reply = SimpleNamespace(model="claude-sonnet-5", usage=usage(1, 1))
    request = call(
        messages=[{"role": "user", "content": "hi"}],
        system="be brief",
        stream=False,
        extra_headers={"x-trace": "1"},
    )

    with ags.conversation("c"):
        client.create(**request)

    assert client.calls == [request]


def test_close_returns_what_the_original_returned(anthropic_module, spans):
    install_anthropic(LOGGER)
    client = anthropic_module.Messages()
    raw = anthropic_module.Stream(EVENTS)
    client.reply = lambda: raw

    with ags.conversation("c"):
        stream = client.create(**call(stream=True))
        for _ in stream:
            break
        assert stream.close() == "closed"

    assert raw.response.closed is True


def test_an_exception_from_close_still_propagates(anthropic_module, spans):
    install_anthropic(LOGGER)
    client = anthropic_module.Messages()
    raw = anthropic_module.Stream(EVENTS)
    boom = RuntimeError("socket already gone")

    def explode():
        raise boom

    client.reply = lambda: raw

    with ags.conversation("c"):
        stream = client.create(**call(stream=True))
        for _ in stream:
            break
        stream.close = explode
        with pytest.raises(RuntimeError, match="socket already gone"):
            stream.close()


def test_exceptions_propagate_unchanged_and_are_recorded(anthropic_module, spans):
    install_anthropic(LOGGER)
    client = anthropic_module.Messages()
    client.reply = ValueError("bad request")

    with ags.conversation("c"):
        with pytest.raises(ValueError, match="bad request"):
            client.create(**call())

    (llm,) = llm_spans(spans)
    assert LLMAttributes.ERROR in llm.attributes
    assert llm.status.status_code.name == "ERROR"
    assert llm.attributes[LLMAttributes.INPUT_TOKENS] == 0


def test_mid_stream_exception_propagates_and_still_records(anthropic_module, spans):
    install_anthropic(LOGGER)
    boom = RuntimeError("connection reset")

    def events():
        yield EVENTS[0]
        yield EVENTS[2]
        raise boom

    client = anthropic_module.Messages()
    client.reply = lambda: anthropic_module.Stream(events())

    with ags.conversation("c"):
        stream = client.create(**call(stream=True))
        with pytest.raises(RuntimeError, match="connection reset"):
            list(stream)

    (llm,) = llm_spans(spans)
    assert tokens(llm)["output"] == 5
    # Both facts on one span: the tokens billed before the failure, and the
    # failure itself.
    assert llm.attributes[LLMAttributes.ERROR] == "connection reset"
    assert llm.status.status_code.name == "ERROR"


def test_a_stream_dead_before_message_start_still_names_the_model(
    anthropic_module, spans
):
    """The manager path's failure span used to carry no model at all.

    The kwargs are gone by ``__enter__`` — the manager holds the request
    privately — and ``message_start``, the usual source, never arrives on a
    stream that dies first. The accounting row built from this span keys on
    the model, so ``.stream()`` stashes the requested id for exactly this
    case. A stream that *does* deliver ``message_start`` still reports the
    resolved id (the half-read tests above pin that precedence).
    """
    install_anthropic(LOGGER)
    boom = RuntimeError("died on connect")

    def events():
        raise boom
        yield  # pragma: no cover

    client = anthropic_module.Messages()
    client.reply = lambda: anthropic_module.Stream(events())

    with ags.conversation("c"):
        with pytest.raises(RuntimeError, match="died on connect"):
            with client.stream(**call()) as stream:
                list(stream)

    (llm,) = llm_spans(spans)
    assert tokens(llm)["model"] == "claude-sonnet-5"
    assert llm.attributes[LLMAttributes.ERROR] == "died on connect"
    assert llm.status.status_code.name == "ERROR"


def test_an_async_stream_dead_before_message_start_still_names_the_model(
    anthropic_module, spans
):
    install_anthropic(LOGGER)
    boom = RuntimeError("died on connect")

    def events():
        raise boom
        yield  # pragma: no cover

    client = anthropic_module.AsyncMessages()
    # The fake AsyncStream iterates its events synchronously, so a sync
    # generator that raises on first pull models the dead connection.
    client.reply = lambda: anthropic_module.AsyncStream(events())

    async def go():
        with ags.conversation("c"):
            with pytest.raises(RuntimeError, match="died on connect"):
                async with client.stream(**call()) as stream:
                    async for _ in stream:
                        pass

    asyncio.run(go())
    (llm,) = llm_spans(spans)
    assert tokens(llm)["model"] == "claude-sonnet-5"
    assert llm.attributes[LLMAttributes.ERROR] == "died on connect"


# ---------------------------------------------------------------------------
# 5. Failure isolation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("victim", ["record_llm_call", "capturing", "from_anthropic"])
def test_a_broken_capture_path_is_invisible(anthropic_module, spans, monkeypatch, victim):
    install_anthropic(LOGGER)

    def explode(*args, **kwargs):
        raise RuntimeError("telemetry is broken")

    monkeypatch.setattr(anthropic_patch, victim, explode)

    client = anthropic_module.Messages()
    reply = SimpleNamespace(model="claude-sonnet-5", usage=usage(10, 5))
    client.reply = reply

    with ags.conversation("c"):
        assert client.create(**call()) is reply

        client.reply = lambda: anthropic_module.Stream(EVENTS)
        with client.stream(**call()) as stream:
            assert list(stream) == EVENTS

    assert llm_spans(spans) == []


def test_an_event_that_cannot_be_read_does_not_break_iteration(anthropic_module, spans):
    class Hostile:
        type = "message_delta"

        @property
        def usage(self):
            raise RuntimeError("pydantic exploded")

    install_anthropic(LOGGER)
    hostile = Hostile()
    events = [EVENTS[0], hostile, EVENTS[4]]
    client = anthropic_module.Messages()
    client.reply = lambda: anthropic_module.Stream(events)

    with ags.conversation("c"):
        stream = client.create(**call(stream=True))
        assert list(stream) == events

    assert tokens(llm_spans(spans)[0])["output"] == 42


def test_an_unrecognised_result_produces_no_span_and_is_returned_intact(
    anthropic_module, spans
):
    """No raw marker, no usage, no iterator: a result from a release this
    patch does not know. It records nothing rather than zero — a zero-token
    span would be indistinguishable from a real call that cost nothing."""
    install_anthropic(LOGGER)
    client = anthropic_module.Messages()
    opaque = SimpleNamespace(status_code=200, headers={})
    client.reply = opaque

    with ags.conversation("c"):
        assert client.create(**call()) is opaque

    assert llm_spans(spans) == []
    assert not hasattr(opaque, "_iterator")


# ---------------------------------------------------------------------------
# 5b. Raw response wrappers
# ---------------------------------------------------------------------------


def test_a_raw_response_is_recorded_and_the_caller_keeps_the_wrapper(
    anthropic_module, spans
):
    """``with_raw_response`` marks the call with a header and hands back an
    APIResponse with neither usage nor iterator — which used to record nothing
    at all: no span, no tokens, no cost. The patch now opens it with the
    memoising ``parse()``, so ours and the caller's are one read of one body,
    and what the caller receives is still the wrapper they asked for."""
    install_anthropic(LOGGER)
    client = anthropic_module.Messages()
    message = SimpleNamespace(model="claude-sonnet-5-20250101", usage=usage(10, 5))
    wrapper = RawResponse(lambda: message)
    client.reply = wrapper

    with ags.conversation("c"):
        result = client.create(**call(extra_headers=dict(RAW_HEADER)))

    assert result is wrapper
    assert result.parse() is message
    (llm,) = llm_spans(spans)
    assert tokens(llm)["model"] == "claude-sonnet-5-20250101"
    assert tokens(llm)["input"] == 10
    assert tokens(llm)["output"] == 5


def test_a_raw_wrapped_stream_is_watched_through_the_callers_own_parse(
    anthropic_module, spans
):
    """On a ``stream=True`` raw call ``parse()`` reads no bytes — it builds
    the lazy Stream, memoised, so the object the caller eventually iterates is
    the one the patch already instrumented."""
    install_anthropic(LOGGER)
    client = anthropic_module.Messages()
    wrapper = RawResponse(lambda: anthropic_module.Stream(EVENTS))
    client.reply = wrapper

    with ags.conversation("c"):
        result = client.create(**call(stream=True, extra_headers=dict(RAW_HEADER)))
        assert result is wrapper
        assert result.parse() is result.parse()
        assert list(result.parse()) == EVENTS

    assert tokens(llm_spans(spans)[0]) == STREAMED


def test_an_async_raw_wrapped_stream_is_watched_too(anthropic_module, spans):
    install_anthropic(LOGGER)
    client = anthropic_module.AsyncMessages()
    wrapper = RawResponse(lambda: anthropic_module.AsyncStream(EVENTS))
    client.reply = wrapper

    async def go():
        with ags.conversation("c"):
            result = await client.create(
                **call(stream=True, extra_headers=dict(RAW_HEADER))
            )
            assert result is wrapper
            assert [event async for event in result.parse()] == EVENTS

    asyncio.run(go())
    assert tokens(llm_spans(spans)[0]) == STREAMED


def test_a_raw_wrapper_that_will_not_open_costs_only_the_telemetry(
    anthropic_module, spans
):
    """A ``parse()`` that raises must never break the user's call."""
    install_anthropic(LOGGER)

    class Sealed:
        def parse(self):
            raise RuntimeError("no body yet")

    client = anthropic_module.Messages()
    sealed = Sealed()
    client.reply = sealed

    with ags.conversation("c"):
        assert client.create(**call(extra_headers=dict(RAW_HEADER))) is sealed

    assert llm_spans(spans) == []


def test_a_streaming_response_wrapper_is_never_opened(anthropic_module, spans):
    """Marker ``"stream"`` is ``with_streaming_response``: reading that body
    belongs to the user, so it stays the one raw surface left alone."""
    install_anthropic(LOGGER)
    opened = []
    wrapper = RawResponse(lambda: opened.append("opened"))
    client = anthropic_module.Messages()
    client.reply = wrapper

    with ags.conversation("c"):
        marker = {"X-Stainless-Raw-Response": "stream"}
        assert client.create(**call(extra_headers=marker)) is wrapper

    assert opened == []
    assert llm_spans(spans) == []


# ---------------------------------------------------------------------------
# 6. No conversation scope
# ---------------------------------------------------------------------------


def test_outside_a_conversation_nothing_is_recorded(anthropic_module, spans):
    install_anthropic(LOGGER)
    client = anthropic_module.Messages()
    reply = SimpleNamespace(model="claude-sonnet-5", usage=usage(9, 9))
    client.reply = reply

    assert client.create(**call()) is reply

    client.reply = lambda: anthropic_module.Stream(EVENTS)
    with client.stream(**call()) as stream:
        assert list(stream) == EVENTS

    assert llm_spans(spans) == []


def test_a_conversation_opened_disabled_records_nothing(anthropic_module, spans):
    install_anthropic(LOGGER)
    client = anthropic_module.AsyncMessages()
    client.reply = lambda: anthropic_module.AsyncStream(EVENTS)

    async def go():
        with ags.conversation("c", enabled=False):
            async with client.stream(**call()) as stream:
                return [event async for event in stream]

    assert asyncio.run(go()) == EVENTS
    assert llm_spans(spans) == []


def test_a_stream_opened_outside_a_conversation_is_left_alone(anthropic_module, spans):
    """The close hook must not be attached either — an un-instrumented stream
    keeps its own ``close``."""
    install_anthropic(LOGGER)
    client = anthropic_module.Messages()
    raw = anthropic_module.Stream(EVENTS)
    client.reply = lambda: raw

    stream = client.create(**call(stream=True))
    assert stream.close() == "closed"
    assert llm_spans(spans) == []
