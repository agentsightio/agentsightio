"""What the Anthropic patch records, and what it must never disturb.

``anthropic`` is not installed here, so every test runs against a fake module
tree registered in ``sys.modules`` — same class hierarchy, same attribute names
(``Stream._iterator``, ``MessageStream._raw_stream``, ``MessageStreamManager.
__enter__``) as the real SDK, since those are exactly what the patch reaches
for. A fake also buys something a real client could not: the ability to assert
that the user's arguments, return value, exceptions and iteration order come
back byte-identical.
"""

import asyncio
import logging
import sys
import types
from types import SimpleNamespace

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

import agentsight.sdk as ags
from agentsight.sdk import core
from agentsight.sdk.instrumentation import anthropic_patch
from agentsight.sdk.instrumentation.anthropic_patch import install_anthropic
from agentsight.sdk.instrumentation.base import already_patched
from agentsight.sdk.semconv import LLMAttributes, SpanAttributes, SpanKind

LOGGER = logging.getLogger("agentsight-test")


# ---------------------------------------------------------------------------
# A fake `anthropic`
# ---------------------------------------------------------------------------


def usage(input_tokens, output_tokens, **cache):
    """A ``Usage``. The cache counters are ``Optional[int] = None`` on the real
    one, so a call that used no cache simply does not carry them."""
    return SimpleNamespace(
        input_tokens=input_tokens, output_tokens=output_tokens, **cache
    )


def message_start(model="claude-sonnet-5", **counters):
    return SimpleNamespace(
        type="message_start",
        message=SimpleNamespace(model=model, usage=usage(**counters)),
    )


def message_delta(**counters):
    """A ``MessageDeltaUsage``: every counter is a running total, never an
    increment, and every one but ``output_tokens`` is absent when unchanged."""
    return SimpleNamespace(type="message_delta", usage=SimpleNamespace(**counters))


def content_delta(text="hi"):
    return SimpleNamespace(type="content_block_delta", delta=SimpleNamespace(text=text))


def build_fake_anthropic():
    """The subset of the class tree ``install_anthropic`` imports and patches."""

    class Stream:
        def __init__(self, events):
            self.closed = False
            # The real Stream stores a generator here and both __iter__ and
            # __next__ read it; that is the seam the patch replaces.
            self._iterator = iter(events)

        def __iter__(self):
            for item in self._iterator:
                yield item

        def __next__(self):
            return next(self._iterator)

        def close(self):
            self.closed = True

    class AsyncStream:
        def __init__(self, events):
            self.closed = False
            self._iterator = self._stream(events)

        async def _stream(self, events):
            for item in events:
                yield item

        async def __aiter__(self):
            async for item in self._iterator:
                yield item

        async def close(self):
            self.closed = True

    class MessageStream:
        def __init__(self, raw_stream):
            self._raw_stream = raw_stream
            self._iterator = self.__stream__()

        def __stream__(self):
            for event in self._raw_stream:
                yield event

        def __iter__(self):
            for item in self._iterator:
                yield item

        def close(self):
            self._raw_stream.close()

    class AsyncMessageStream:
        def __init__(self, raw_stream):
            self._raw_stream = raw_stream
            self._iterator = self.__stream__()

        async def __stream__(self):
            async for event in self._raw_stream:
                yield event

        async def __aiter__(self):
            async for item in self._iterator:
                yield item

        async def close(self):
            await self._raw_stream.close()

    class MessageStreamManager:
        def __init__(self, make_request):
            self._make_request = make_request
            self._stream = None

        def __enter__(self):
            self._stream = MessageStream(self._make_request())
            return self._stream

        def __exit__(self, *exc_info):
            if self._stream is not None:
                self._stream.close()

    class AsyncMessageStreamManager:
        def __init__(self, make_request):
            self._make_request = make_request
            self._stream = None

        async def __aenter__(self):
            self._stream = AsyncMessageStream(await self._make_request())
            return self._stream

        async def __aexit__(self, *exc_info):
            if self._stream is not None:
                await self._stream.close()

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

        parse = create

        def stream(self, *, model, **kwargs):
            self.calls.append(dict(kwargs, model=model))
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

        parse = create

        def stream(self, *, model, **kwargs):
            # Deliberately a plain `def`, as in the real SDK.
            self.calls.append(dict(kwargs, model=model))

            async def make_request():
                return self.reply()

            return AsyncMessageStreamManager(make_request)

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


@pytest.fixture
def fake_anthropic():
    """Install a throwaway `anthropic` package, then take it away again.

    Fresh classes per test, so a patch applied in one test cannot leak into the
    next and be mistaken for idempotency.
    """
    from agentsight.sdk.instrumentation import _reset_for_tests

    kit = build_fake_anthropic()
    # Built a second time rather than subclassed: `beta.messages.Messages` is a
    # wholly separate class that happens to share the name, which is the entire
    # reason it needs its own patch.
    kit.beta = build_fake_anthropic()
    saved = {name: mod for name, mod in sys.modules.items() if name.split(".")[0] == "anthropic"}

    def module(name, **attributes):
        mod = types.ModuleType(name)
        mod.__path__ = []
        for key, value in attributes.items():
            setattr(mod, key, value)
        sys.modules[name] = mod
        return mod

    module("anthropic")
    module("anthropic.lib")
    module(
        "anthropic.lib.streaming",
        MessageStreamManager=kit.MessageStreamManager,
        AsyncMessageStreamManager=kit.AsyncMessageStreamManager,
        BetaMessageStreamManager=kit.beta.MessageStreamManager,
        BetaAsyncMessageStreamManager=kit.beta.AsyncMessageStreamManager,
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
        Messages=kit.beta.Messages,
        AsyncMessages=kit.beta.AsyncMessages,
    )

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


# ---------------------------------------------------------------------------
# Attachment and idempotency
# ---------------------------------------------------------------------------


PATCHED = [
    ("anthropic.resources.messages", "Messages", "create"),
    ("anthropic.resources.messages", "Messages", "parse"),
    ("anthropic.resources.messages", "AsyncMessages", "create"),
    ("anthropic.resources.messages", "AsyncMessages", "parse"),
    ("anthropic.resources.beta.messages", "Messages", "create"),
    ("anthropic.resources.beta.messages", "Messages", "parse"),
    ("anthropic.resources.beta.messages", "AsyncMessages", "create"),
    ("anthropic.resources.beta.messages", "AsyncMessages", "parse"),
    ("anthropic.lib.streaming", "MessageStreamManager", "__enter__"),
    ("anthropic.lib.streaming", "AsyncMessageStreamManager", "__aenter__"),
    ("anthropic.lib.streaming", "BetaMessageStreamManager", "__enter__"),
    ("anthropic.lib.streaming", "BetaAsyncMessageStreamManager", "__aenter__"),
]


@pytest.mark.parametrize("module_name,class_name,method", PATCHED)
def test_every_surface_is_patched(fake_anthropic, module_name, class_name, method):
    install_anthropic(LOGGER)

    owner = getattr(sys.modules[module_name], class_name)
    assert already_patched(owner.__dict__[method])


def test_beta_is_a_separate_patch(fake_anthropic):
    install_anthropic(LOGGER)

    stable = sys.modules["anthropic.resources.messages"].Messages
    beta = sys.modules["anthropic.resources.beta.messages"].Messages
    assert beta.__dict__["create"] is not stable.__dict__["create"]


def test_install_twice_does_not_stack(fake_anthropic, spans):
    install_anthropic(LOGGER)
    wrapper = sys.modules["anthropic.resources.messages"].Messages.create
    install_anthropic(LOGGER)
    assert sys.modules["anthropic.resources.messages"].Messages.create is wrapper

    client = sys.modules["anthropic.resources.messages"].Messages()
    client.reply = SimpleNamespace(model="claude-sonnet-5", usage=usage(10, 5))
    with ags.conversation("c"):
        client.create(model="claude-sonnet-5", max_tokens=1, messages=[])

    assert len(llm_spans(spans)) == 1
    assert tokens(llm_spans(spans)[0])["output"] == 5


def test_missing_method_is_skipped(fake_anthropic):
    """A release that drops one method must not cost the others their patch."""
    del sys.modules["anthropic.resources.messages"].Messages.parse
    install_anthropic(LOGGER)

    messages = sys.modules["anthropic.resources.messages"].Messages
    assert already_patched(messages.create)
    assert already_patched(
        sys.modules["anthropic.lib.streaming"].MessageStreamManager.__enter__
    )


def test_older_sdk_without_beta_still_gets_the_stable_patch(fake_anthropic):
    del sys.modules["anthropic.resources.beta.messages"]
    install_anthropic(LOGGER)

    assert already_patched(sys.modules["anthropic.resources.messages"].Messages.create)


# ---------------------------------------------------------------------------
# Non-streaming
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("method", ["create", "parse"])
def test_non_streaming_tokens(fake_anthropic, spans, method):
    install_anthropic(LOGGER)
    client = fake_anthropic.Messages()
    client.reply = SimpleNamespace(
        model="claude-sonnet-5-20250101",
        usage=usage(
            input_tokens=100,
            output_tokens=42,
            cache_read_input_tokens=30,
            cache_creation_input_tokens=20,
        ),
    )

    with ags.conversation("c"):
        result = getattr(client, method)(model="claude-sonnet-5", max_tokens=1, messages=[])

    assert result is client.reply
    assert tokens(llm_spans(spans)[0]) == {
        # Anthropic's input_tokens already excludes both cache counts.
        "model": "claude-sonnet-5-20250101",
        "input": 100,
        "output": 42,
        "cache_read": 30,
        "cache_write": 20,
        "streaming": None,
    }


def test_span_covers_the_call_not_an_instant(fake_anthropic, spans):
    install_anthropic(LOGGER)
    client = fake_anthropic.Messages()

    def slow():
        import time

        time.sleep(0.01)
        return SimpleNamespace(model="claude-sonnet-5", usage=usage(1, 1))

    client.reply = slow
    with ags.conversation("c"):
        client.create(model="claude-sonnet-5", max_tokens=1, messages=[])

    span = llm_spans(spans)[0]
    assert span.end_time - span.start_time >= 10_000_000


def test_absent_counters_are_absent_from_the_span(fake_anthropic, spans):
    """A zero cache counter and 'this call used no cache' are different facts."""
    install_anthropic(LOGGER)
    client = fake_anthropic.Messages()
    client.reply = SimpleNamespace(model="claude-sonnet-5", usage=usage(7, 3))

    with ags.conversation("c"):
        client.create(model="claude-sonnet-5", max_tokens=1, messages=[])

    attributes = llm_spans(spans)[0].attributes
    assert LLMAttributes.CACHE_READ_TOKENS not in attributes
    assert LLMAttributes.CACHE_WRITE_TOKENS not in attributes


def test_cost_is_priced_from_the_resolved_model(fake_anthropic, spans):
    install_anthropic(LOGGER)
    client = fake_anthropic.Messages()
    client.reply = SimpleNamespace(
        model="claude-sonnet-5", usage=usage(1_000_000, 1_000_000)
    )

    with ags.conversation("c"):
        client.create(model="claude-sonnet-5", max_tokens=1, messages=[])

    assert llm_spans(spans)[0].attributes[LLMAttributes.COST_USD] == pytest.approx(18.0)


# ---------------------------------------------------------------------------
# Streaming — the numbers
# ---------------------------------------------------------------------------


STREAM_EVENTS = [
    message_start(
        model="claude-sonnet-5-20250101",
        input_tokens=100,
        output_tokens=1,  # a priming count, not the total
        cache_read_input_tokens=30,
        cache_creation_input_tokens=20,
    ),
    content_delta("hel"),
    message_delta(output_tokens=5),
    content_delta("lo"),
    message_delta(output_tokens=42),  # cumulative, not an increment
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


def test_streamed_create_emits_one_span_with_cumulative_totals(fake_anthropic, spans):
    install_anthropic(LOGGER)
    client = fake_anthropic.Messages()
    client.reply = lambda: fake_anthropic.Stream(STREAM_EVENTS)

    with ags.conversation("c"):
        stream = client.create(model="claude-sonnet-5", max_tokens=1, messages=[], stream=True)
        assert llm_spans(spans) == []  # nothing generated yet
        seen = list(stream)

    assert seen == STREAM_EVENTS
    assert len(llm_spans(spans)) == 1
    assert tokens(llm_spans(spans)[0]) == STREAMED


def test_streamed_create_via_next(fake_anthropic, spans):
    """`__next__` reads the same `_iterator`, so it must be instrumented too."""
    install_anthropic(LOGGER)
    client = fake_anthropic.Messages()
    client.reply = lambda: fake_anthropic.Stream(STREAM_EVENTS)

    with ags.conversation("c"):
        stream = client.create(model="claude-sonnet-5", max_tokens=1, messages=[], stream=True)
        seen = []
        while True:
            try:
                seen.append(next(stream))
            except StopIteration:
                break

    assert seen == STREAM_EVENTS
    assert tokens(llm_spans(spans)[0]) == STREAMED


def test_stream_helper_emits_one_span(fake_anthropic, spans):
    """`.stream()` never calls `create()`; it is instrumented at __enter__."""
    install_anthropic(LOGGER)
    client = fake_anthropic.Messages()
    client.reply = lambda: fake_anthropic.Stream(STREAM_EVENTS)

    with ags.conversation("c"):
        with client.stream(model="claude-sonnet-5", max_tokens=1, messages=[]) as stream:
            seen = list(stream)

    assert seen == STREAM_EVENTS
    assert len(llm_spans(spans)) == 1
    assert tokens(llm_spans(spans)[0]) == STREAMED


def test_beta_stream_helper_is_instrumented_separately(fake_anthropic, spans):
    install_anthropic(LOGGER)
    client = fake_anthropic.beta.Messages()
    client.reply = lambda: fake_anthropic.Stream(STREAM_EVENTS)
    manager = fake_anthropic.beta.MessageStreamManager(client.reply)

    with ags.conversation("c"):
        with manager as stream:
            list(stream)

    assert tokens(llm_spans(spans)[0]) == STREAMED


def test_abandoned_stream_records_what_was_seen(fake_anthropic, spans):
    install_anthropic(LOGGER)
    client = fake_anthropic.Messages()
    client.reply = lambda: fake_anthropic.Stream(STREAM_EVENTS)

    with ags.conversation("c"):
        stream = client.create(model="claude-sonnet-5", max_tokens=1, messages=[], stream=True)
        for event in stream:
            if getattr(event, "type", None) == "message_delta":
                break
        del stream, event

    assert tokens(llm_spans(spans)[0]) == dict(STREAMED, output=5)


def test_stream_that_raises_still_records(fake_anthropic, spans):
    install_anthropic(LOGGER)
    boom = RuntimeError("connection reset")

    def events():
        yield STREAM_EVENTS[0]
        yield STREAM_EVENTS[2]
        raise boom

    client = fake_anthropic.Messages()
    client.reply = lambda: fake_anthropic.Stream(events())

    with ags.conversation("c"):
        stream = client.create(model="claude-sonnet-5", max_tokens=1, messages=[], stream=True)
        with pytest.raises(RuntimeError, match="connection reset"):
            list(stream)

    assert tokens(llm_spans(spans)[0])["output"] == 5


def test_stream_internals_renamed(fake_anthropic, spans):
    """A future release renaming `_iterator` must cost telemetry, not the user.

    And it must cost the whole span: one reporting zero tokens is
    indistinguishable from a real call that cost nothing.
    """
    install_anthropic(LOGGER)
    client = fake_anthropic.Messages()
    opaque = SimpleNamespace()
    client.reply = lambda: opaque

    with ags.conversation("c"):
        result = client.create(model="claude-sonnet-5", max_tokens=1, messages=[], stream=True)

    assert result is opaque
    assert llm_spans(spans) == []


# ---------------------------------------------------------------------------
# Async
# ---------------------------------------------------------------------------


def test_async_non_streaming(fake_anthropic, spans):
    install_anthropic(LOGGER)
    client = fake_anthropic.AsyncMessages()
    client.reply = SimpleNamespace(model="claude-opus-5", usage=usage(11, 22))

    async def go():
        with ags.conversation("c"):
            return await client.create(model="claude-opus-5", max_tokens=1, messages=[])

    assert asyncio.run(go()) is client.reply
    assert tokens(llm_spans(spans)[0])["output"] == 22


def test_async_streamed_create(fake_anthropic, spans):
    install_anthropic(LOGGER)
    client = fake_anthropic.AsyncMessages()
    client.reply = lambda: fake_anthropic.AsyncStream(STREAM_EVENTS)

    async def go():
        with ags.conversation("c"):
            stream = await client.create(
                model="claude-sonnet-5", max_tokens=1, messages=[], stream=True
            )
            return [event async for event in stream]

    assert asyncio.run(go()) == STREAM_EVENTS
    assert tokens(llm_spans(spans)[0]) == STREAMED


def test_async_stream_helper_is_not_awaited(fake_anthropic, spans):
    """`AsyncMessages.stream` is a plain `def`; `async with` must still work."""
    install_anthropic(LOGGER)
    client = fake_anthropic.AsyncMessages()
    client.reply = lambda: fake_anthropic.AsyncStream(STREAM_EVENTS)

    async def go():
        with ags.conversation("c"):
            manager = client.stream(model="claude-sonnet-5", max_tokens=1, messages=[])
            async with manager as stream:
                return [event async for event in stream]

    assert asyncio.run(go()) == STREAM_EVENTS
    assert len(llm_spans(spans)) == 1
    assert tokens(llm_spans(spans)[0]) == STREAMED


# ---------------------------------------------------------------------------
# The invariant: identical behaviour with and without AgentSight
# ---------------------------------------------------------------------------


def test_arguments_pass_through_untouched(fake_anthropic, spans):
    install_anthropic(LOGGER)
    client = fake_anthropic.Messages()
    client.reply = SimpleNamespace(model="claude-sonnet-5", usage=usage(1, 1))
    call = {
        "model": "claude-sonnet-5",
        "max_tokens": 512,
        "messages": [{"role": "user", "content": "hi"}],
        "system": "be brief",
        "temperature": 0.0,
    }

    with ags.conversation("c"):
        client.create(**call)

    assert client.calls == [call]


def test_exceptions_propagate(fake_anthropic, spans):
    install_anthropic(LOGGER)
    client = fake_anthropic.Messages()
    client.reply = ValueError("bad request")

    with ags.conversation("c"):
        with pytest.raises(ValueError, match="bad request"):
            client.create(model="claude-sonnet-5", max_tokens=1, messages=[])

    assert llm_spans(spans) == []


@pytest.mark.parametrize(
    "scope",
    [
        pytest.param(lambda: ags.conversation("c"), id="in-conversation"),
        pytest.param(lambda: ags.conversation("c", enabled=False), id="tracking-off"),
    ],
)
def test_recording_failure_is_invisible(fake_anthropic, spans, monkeypatch, scope):
    """The user's call must be byte-identical whether or not capture works."""
    install_anthropic(LOGGER)

    def explode(*args, **kwargs):
        raise RuntimeError("telemetry is broken")

    monkeypatch.setattr(anthropic_patch, "record_llm_call", explode)
    monkeypatch.setattr(anthropic_patch, "capturing", explode)

    client = fake_anthropic.Messages()
    client.reply = lambda: fake_anthropic.Stream(STREAM_EVENTS)

    with scope():
        stream = client.create(model="claude-sonnet-5", max_tokens=1, messages=[], stream=True)
        assert list(stream) == STREAM_EVENTS

    assert llm_spans(spans) == []


def test_nothing_recorded_outside_a_conversation(fake_anthropic, spans):
    install_anthropic(LOGGER)
    client = fake_anthropic.Messages()
    client.reply = SimpleNamespace(model="claude-sonnet-5", usage=usage(9, 9))

    assert client.create(model="claude-sonnet-5", max_tokens=1, messages=[]) is client.reply
    assert llm_spans(spans) == []


def test_disabled_tracking_records_nothing(fake_anthropic, spans):
    install_anthropic(LOGGER)
    client = fake_anthropic.Messages()
    client.reply = lambda: fake_anthropic.Stream(STREAM_EVENTS)

    with ags.conversation("c", enabled=False):
        stream = client.create(model="claude-sonnet-5", max_tokens=1, messages=[], stream=True)
        assert list(stream) == STREAM_EVENTS

    assert llm_spans(spans) == []


def test_raw_response_wrapper_is_left_alone(fake_anthropic, spans):
    """An APIResponse has neither a usage nor an iterator; reading it would
    consume the body the user has not read yet."""
    install_anthropic(LOGGER)
    client = fake_anthropic.Messages()
    client.reply = SimpleNamespace(status_code=200, headers={})

    with ags.conversation("c"):
        result = client.create(model="claude-sonnet-5", max_tokens=1, messages=[])

    assert result is client.reply
    assert not hasattr(result, "_iterator")
    assert llm_spans(spans) == []
