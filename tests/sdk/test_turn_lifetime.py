"""Turns whose lifetime is not the block that started them.

``with`` is the primary scoping construct (design decision 13), and the one
real objection to it is that a block ends when the function returns while the
work often does not. ``turn.wrap()`` is the answer, so these tests are the ones
that decide whether that answer holds.
"""

import asyncio
import threading
import time

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

import agentsight.sdk as ags
from agentsight.sdk import context as ags_context
from agentsight.sdk import core, watchdog
from agentsight.sdk.processors import TurnBufferingProcessor
from agentsight.sdk.semconv import (
    MessageAttributes,
    SpanAttributes,
    SpanKind,
    TurnAttributes,
)


@pytest.fixture
def spans():
    """A live SDK whose spans land in memory instead of on the network.

    Wired the same way ``init()`` wires production — buffering above batching —
    so the discard-an-unfinished-turn behaviour under test is the real one and
    not a simplified stand-in.
    """
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(TurnBufferingProcessor(SimpleSpanProcessor(exporter)))

    previous = (core._state.enabled, core._state.provider, core._state.tracer)
    core._state.provider = provider
    core._state.tracer = provider.get_tracer("agentsight-test")
    core._state.turn_timeout_ms = watchdog.DEFAULT_TIMEOUT_MS
    core._state.enabled = True
    try:
        yield exporter
    finally:
        core._state.enabled, core._state.provider, core._state.tracer = previous


def turns(exporter):
    return [
        s
        for s in exporter.get_finished_spans()
        if (s.attributes or {}).get(SpanAttributes.KIND) == SpanKind.TURN
    ]


def messages(span):
    return [
        (
            e.attributes[MessageAttributes.SENDER],
            e.attributes[MessageAttributes.CONTENT],
        )
        for e in span.events
        if e.name == MessageAttributes.EVENT_NAME
    ]


# ---------------------------------------------------------------------------
# The case the whole design turns on
# ---------------------------------------------------------------------------


def test_generator_keeps_the_turn_open_past_the_block(spans):
    """The block exits at `return`; the work happens afterwards."""

    def handler():
        with ags.conversation("c-1"):
            with ags.turn():
                ags.user_message("how do I reset my password?")

                def body():
                    for chunk in ["Click ", "forgot ", "password."]:
                        time.sleep(0.01)
                        yield chunk
                    ags.agent_message("Click forgot password.")

                return ags.wrap(body())

    stream = handler()
    assert turns(spans) == [], "the turn must not close when the handler returns"

    assert "".join(stream) == "Click forgot password."

    (turn,) = turns(spans)
    assert turn.attributes[TurnAttributes.COMPLETE] is True
    assert messages(turn) == [
        ("end_user", "how do I reset my password?"),
        ("agent", "Click forgot password."),
    ]
    # The whole point: latency covers the streaming, not the return.
    assert (turn.end_time - turn.start_time) / 1e6 >= 30


def test_agent_message_from_a_different_thread_still_lands(spans):
    """Generators resume in the consumer's context, not the producer's.

    Without re-attaching the scope around each step this silently records
    nothing — the failure mode is missing data, with no error anywhere.
    """

    def handler():
        with ags.conversation("c-thread"):
            with ags.turn():

                def body():
                    yield "a"
                    ags.agent_message("from another thread")

                return ags.wrap(body())

    stream = handler()
    drained = []
    consumer = threading.Thread(target=lambda: drained.extend(stream))
    consumer.start()
    consumer.join()

    (turn,) = turns(spans)
    assert drained == ["a"]
    assert messages(turn) == [("agent", "from another thread")]


def test_wrapping_does_not_leak_scope_into_the_consumer(spans):
    def handler():
        with ags.conversation("c-leak"):
            with ags.turn():
                return ags.wrap(iter(["x", "y"]))

    for _ in handler():
        assert ags_context.current_conversation() is None
        assert ags_context.current_turn() is None


def test_a_streaming_decorator_does_not_follow_the_handler_home(spans):
    """A worker loop calls the handler again; the last call must be gone."""

    @ags.turn(id_from="session_id")
    def handler(session_id):
        def body():
            yield "chunk"
            ags.agent_message(f"answered {session_id}")

        return body()

    first = handler(session_id="wa-1")
    assert ags_context.current_conversation() is None, (
        "the scope must not outlive the call that opened it"
    )
    assert ags_context.current_turn() is None

    second = handler(session_id="wa-2")
    list(first)
    list(second)

    recorded = {
        s.attributes["agentsight.conversation.id"]: messages(s) for s in turns(spans)
    }
    assert recorded == {
        "wa-1": [("agent", "answered wa-1")],
        "wa-2": [("agent", "answered wa-2")],
    }


# ---------------------------------------------------------------------------
# Abandonment
# ---------------------------------------------------------------------------


def test_abandoned_stream_is_discarded_with_its_children(spans):
    """A client that disconnects mid-answer produces no half-exchange."""

    @ags.tool
    def lookup(user_id):
        return "found"

    def handler():
        with ags.conversation("c-abandon"):
            with ags.turn():
                ags.user_message("hello")

                def body():
                    lookup(user_id="u-1")
                    yield "partial"
                    yield "never reached"

                return ags.wrap(body())

    stream = handler()
    assert next(stream) == "partial"
    stream.close()  # GeneratorExit — what a disconnect looks like

    assert spans.get_finished_spans() == (), (
        "an unfinished turn must take its tool spans down with it"
    )


def test_exception_mid_stream_discards_the_turn(spans):
    def handler():
        with ags.conversation("c-boom"):
            with ags.turn():

                def body():
                    yield "ok"
                    raise RuntimeError("upstream died")

                return ags.wrap(body())

    stream = handler()
    assert next(stream) == "ok"
    with pytest.raises(RuntimeError):
        next(stream)
    assert spans.get_finished_spans() == ()


# ---------------------------------------------------------------------------
# Shapes other than generators
# ---------------------------------------------------------------------------


def test_streaming_response_object(spans):
    class FakeStreamingResponse:
        """Starlette is recognised by ``body_iterator``, never imported."""

        def __init__(self, iterator):
            self.body_iterator = iterator
            self.status_code = 200

    def handler():
        with ags.conversation("c-sse"):
            with ags.turn():
                return ags.wrap(FakeStreamingResponse(iter(["data: 1", "data: 2"])))

    response = handler()
    assert response.status_code == 200, "wrap must return the response itself"
    assert list(response.body_iterator) == ["data: 1", "data: 2"]
    assert len(turns(spans)) == 1


@pytest.mark.asyncio
async def test_async_generator(spans):
    async def handler():
        with ags.conversation("c-async"):
            with ags.turn():

                async def body():
                    for chunk in ["a", "b"]:
                        await asyncio.sleep(0.005)
                        yield chunk
                    ags.agent_message("ab")

                return ags.wrap(body())

    stream = await handler()
    assert turns(spans) == []

    collected = [chunk async for chunk in stream]
    assert collected == ["a", "b"]

    (turn,) = turns(spans)
    assert messages(turn) == [("agent", "ab")]


@pytest.mark.asyncio
async def test_task(spans):
    """A handler that schedules the work and returns the task."""

    async def work():
        await asyncio.sleep(0.01)
        ags.agent_message("done later")

    async def handler():
        with ags.conversation("c-task"):
            with ags.turn():
                return ags.wrap(asyncio.create_task(work()))

    task = handler_result = await handler()
    assert asyncio.isfuture(handler_result), "the task itself must come back"
    assert turns(spans) == []

    await task
    await asyncio.sleep(0)  # let the done-callback run

    (turn,) = turns(spans)
    assert turn.attributes[TurnAttributes.COMPLETE] is True


@pytest.mark.asyncio
async def test_cancelled_task_discards_the_turn(spans):
    async def work():
        await asyncio.sleep(5)

    async def handler():
        with ags.conversation("c-cancel"):
            with ags.turn():
                return ags.wrap(asyncio.create_task(work()))

    task = await handler()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await asyncio.sleep(0)

    assert turns(spans) == []


# ---------------------------------------------------------------------------
# The backstop
# ---------------------------------------------------------------------------


def test_a_stream_that_is_never_drained_is_eventually_closed(spans):
    """Open question 3, answered: a held-but-never-read generator is bounded.

    Without the deadline this turn never ends, never exports, and holds its
    buffered children in memory for the life of the process — with nothing
    raised anywhere to say so.
    """
    core._state.turn_timeout_ms = 150

    def handler():
        with ags.conversation("c-forever"):
            with ags.turn() as scope:
                ags.user_message("hello?")

                def body():
                    yield "one"
                    yield "two"

                return ags.wrap(body()), scope

    stream, scope = handler()
    assert next(stream) == "one"  # then the consumer wanders off

    deadline = time.monotonic() + 3.0
    while not scope._ended and time.monotonic() < deadline:
        time.sleep(0.02)

    assert scope._ended, "the deadline must close a turn nobody is draining"
    # Decision 11: it is dropped in the SDK rather than exported and filtered,
    # so a half-drained stream never reaches the dashboard at all.
    assert spans.get_finished_spans() == ()


def test_the_deadline_is_cancelled_when_the_stream_ends_normally(spans):
    core._state.turn_timeout_ms = 100

    def handler():
        with ags.conversation("c-fast"):
            with ags.turn() as scope:
                held = scope
                return ags.wrap(iter(["x"])), held

    stream, scope = handler()
    assert list(stream) == ["x"]
    assert scope._watchdog is None

    time.sleep(0.2)  # past the deadline; nothing more may happen
    assert len(turns(spans)) == 1
    assert turns(spans)[0].attributes[TurnAttributes.COMPLETE] is True


def test_finish_is_idempotent_under_a_race(spans):
    """The watchdog fires on its own thread while the iterator is finishing."""

    def handler():
        with ags.conversation("c-race"):
            with ags.turn() as scope:
                return ags.wrap(iter(["x"])), scope

    stream, scope = handler()
    list(stream)

    barrier = threading.Barrier(4)

    def racer():
        barrier.wait()
        scope.finish(complete=True)

    threads = [threading.Thread(target=racer) for _ in range(3)]
    for thread in threads:
        thread.start()
    barrier.wait()
    for thread in threads:
        thread.join()

    assert len(turns(spans)) == 1


# ---------------------------------------------------------------------------
# keep_open / end_turn
# ---------------------------------------------------------------------------


def test_keep_open_and_end_turn(spans):
    """For work finished by a later callback, with no object to bind to."""
    core._state.turn_timeout_ms = 5_000

    with ags.conversation("c-ws"):
        with ags.turn() as scope:
            ags.user_message("ping")
            scope.keep_open()

        assert turns(spans) == []

        # Later, from the callback that actually finishes the exchange.
        token = ags_context.set_turn(scope)
        ags.agent_message("pong")
        ags.end_turn()
        ags_context.reset_turn(token)

    (turn,) = turns(spans)
    assert messages(turn) == [("end_user", "ping"), ("agent", "pong")]
    assert turn.attributes[TurnAttributes.COMPLETE] is True


# ---------------------------------------------------------------------------
# Transparency
# ---------------------------------------------------------------------------


def test_wrap_is_a_no_op_with_no_turn():
    source = iter(["a", "b"])
    assert ags.wrap(source) is source


def test_wrap_returns_unrecognised_objects_untouched(spans):
    marker = object()
    with ags.conversation("c-unknown"):
        with ags.turn():
            assert ags.wrap(marker) is marker
            ags.abandon_turn()


def test_wrap_survives_a_broken_turn(spans, monkeypatch):
    """Instrumentation failure must never reach the user's data path."""

    def explode(self, obj):
        raise RuntimeError("wrap is broken")

    monkeypatch.setattr("agentsight.sdk.scopes.TurnScope.wrap", explode)

    source = iter(["a", "b"])
    with ags.conversation("c-broken"):
        with ags.turn():
            assert ags.wrap(source) is source
    assert list(source) == ["a", "b"]
