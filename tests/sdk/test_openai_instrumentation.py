"""Adversarial verification of the ``openai`` patch.

Every test here answers one question: is the user's program identical with the
patch installed and without it? The token assertions matter, but the
transparency ones matter more — a wrong number is a bug report, a changed
iteration sequence is an outage in someone else's product.

The provider is a ``httpx.MockTransport``: no network, no key beyond a fake
one, and full control over the exact bytes the SDK's stream decoder sees.
"""

import gc
import json
import logging
from typing import Any, Dict, List, Optional

import httpx
import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

import agentsight.sdk as ags
from agentsight.sdk import core
from agentsight.sdk.instrumentation import openai_patch
from agentsight.sdk.instrumentation.openai_patch import install_openai
from agentsight.sdk.processors import TurnBufferingProcessor
from agentsight.sdk.semconv import LLMAttributes, SpanAttributes, SpanKind

openai = pytest.importorskip("openai")

logger = logging.getLogger("agentsight-test")


# ---------------------------------------------------------------------------
# Fake provider
# ---------------------------------------------------------------------------


def sse(*payloads: Dict[str, Any]) -> bytes:
    body = "".join("data: %s\n\n" % json.dumps(p) for p in payloads)
    return (body + "data: [DONE]\n\n").encode()


def chat_chunk(content: Optional[str] = None, usage: Optional[dict] = None) -> dict:
    chunk = {
        "id": "chatcmpl-1",
        "object": "chat.completion.chunk",
        "created": 1,
        "model": "gpt-4o",
        "choices": (
            []
            if content is None
            else [{"index": 0, "delta": {"content": content}, "finish_reason": None}]
        ),
    }
    if usage is not None:
        chunk["usage"] = usage
    return chunk


CHAT_USAGE = {
    "prompt_tokens": 100,
    "completion_tokens": 40,
    "total_tokens": 140,
    "prompt_tokens_details": {"cached_tokens": 40},
    "completion_tokens_details": {"reasoning_tokens": 5},
}


def chat_completion(usage: Optional[dict] = None) -> dict:
    return {
        "id": "chatcmpl-1",
        "object": "chat.completion",
        "created": 1,
        "model": "gpt-4o",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": "hello"},
                "finish_reason": "stop",
            }
        ],
        "usage": CHAT_USAGE if usage is None else usage,
    }


def response_object(usage: Optional[dict] = None) -> dict:
    return {
        "id": "resp-1",
        "object": "response",
        "created_at": 1,
        "model": "gpt-4o",
        "status": "completed",
        "output": [
            {
                "id": "msg-1",
                "type": "message",
                "role": "assistant",
                "status": "completed",
                "content": [
                    {"type": "output_text", "text": "hello", "annotations": []}
                ],
            }
        ],
        "parallel_tool_calls": False,
        "tool_choice": "auto",
        "tools": [],
        "usage": usage
        or {
            "input_tokens": 100,
            "output_tokens": 40,
            "total_tokens": 140,
            "input_tokens_details": {"cached_tokens": 40},
            "output_tokens_details": {"reasoning_tokens": 5},
        },
    }


class FakeAPI:
    """Records every request and replies with whatever the test queued."""

    def __init__(self):
        self.requests: List[httpx.Request] = []
        self.reply = None

    def bodies(self) -> List[dict]:
        return [json.loads(r.content or b"{}") for r in self.requests]

    def __call__(self, request: httpx.Request) -> httpx.Response:
        request.read()
        self.requests.append(request)
        return self.reply(request)


def json_reply(payload):
    return lambda request: httpx.Response(200, json=payload)


def stream_reply(*payloads):
    return lambda request: httpx.Response(
        200,
        content=sse(*payloads),
        headers={"content-type": "text/event-stream"},
    )


def error_reply(status=500):
    return lambda request: httpx.Response(status, json={"error": {"message": "boom"}})


@pytest.fixture
def api():
    return FakeAPI()


@pytest.fixture
def client(api):
    return openai.OpenAI(
        api_key="sk-test",
        max_retries=0,
        http_client=httpx.Client(transport=httpx.MockTransport(api)),
    )


@pytest.fixture
def aclient(api):
    return openai.AsyncOpenAI(
        api_key="sk-test",
        max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(api)),
    )


# ---------------------------------------------------------------------------
# SDK harness
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session", autouse=True)
def patched():
    """The patch is global and idempotent; installing it twice is the point."""
    install_openai(logger)
    install_openai(logger)


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


@pytest.fixture(autouse=True)
def injection_safe():
    """``_INJECTION_SAFE`` is process-wide; one test tripping it must not
    silently disarm every later one."""
    openai_patch._INJECTION_SAFE = True
    yield
    openai_patch._INJECTION_SAFE = True


# ---------------------------------------------------------------------------
# 1. Double counting
# ---------------------------------------------------------------------------


def test_installing_twice_still_records_one_span(spans, client, api):
    api.reply = json_reply(chat_completion())

    with ags.conversation("c-double"):
        with ags.turn():
            client.chat.completions.create(
                model="gpt-4o", messages=[{"role": "user", "content": "hi"}]
            )

    assert len(llm_spans(spans)) == 1


def test_installing_twice_does_not_double_a_streamed_span(spans, client, api):
    api.reply = stream_reply(chat_chunk("a"), chat_chunk(usage=CHAT_USAGE))

    with ags.conversation("c-double-stream"):
        with ags.turn():
            stream = client.chat.completions.create(
                model="gpt-4o",
                messages=[{"role": "user", "content": "hi"}],
                stream=True,
            )
            list(stream)

    assert len(llm_spans(spans)) == 1


# ---------------------------------------------------------------------------
# 2. Token maths
# ---------------------------------------------------------------------------


def test_cached_tokens_are_subtracted_from_openai_input(spans, client, api):
    """OpenAI folds cached tokens into prompt_tokens; Anthropic does not."""
    api.reply = json_reply(chat_completion())

    with ags.conversation("c-tokens"):
        with ags.turn():
            client.chat.completions.create(
                model="gpt-4o", messages=[{"role": "user", "content": "hi"}]
            )

    (llm,) = llm_spans(spans)
    assert llm.attributes[LLMAttributes.INPUT_TOKENS] == 60
    assert llm.attributes[LLMAttributes.CACHE_READ_TOKENS] == 40
    assert llm.attributes[LLMAttributes.OPERATION] == "chat"
    assert llm.attributes[LLMAttributes.SYSTEM] == "openai"


def test_reasoning_tokens_are_reported_but_not_added_to_the_total(spans, client, api):
    api.reply = json_reply(chat_completion())

    with ags.conversation("c-reasoning"):
        with ags.turn():
            client.chat.completions.create(
                model="gpt-4o", messages=[{"role": "user", "content": "hi"}]
            )

    (llm,) = llm_spans(spans)
    assert llm.attributes[LLMAttributes.REASONING_TOKENS] == 5
    assert llm.attributes[LLMAttributes.OUTPUT_TOKENS] == 40
    billable = sum(llm.attributes.get(n, 0) for n in LLMAttributes.BILLABLE)
    assert billable == 60 + 40 + 40


def test_a_span_covers_the_call_rather_than_an_instant(spans, client, api):
    api.reply = json_reply(chat_completion())

    with ags.conversation("c-duration"):
        with ags.turn():
            client.chat.completions.create(
                model="gpt-4o", messages=[{"role": "user", "content": "hi"}]
            )

    (llm,) = llm_spans(spans)
    assert llm.end_time > llm.start_time


def test_embeddings_are_their_own_token_category(spans, client, api):
    api.reply = json_reply(
        {
            "object": "list",
            "model": "text-embedding-3-small",
            "data": [{"object": "embedding", "index": 0, "embedding": [0.1, 0.2]}],
            "usage": {"prompt_tokens": 8, "total_tokens": 8},
        }
    )

    with ags.conversation("c-embed"):
        with ags.turn():
            client.embeddings.create(model="text-embedding-3-small", input="hi")

    (llm,) = llm_spans(spans)
    assert llm.attributes[LLMAttributes.EMBEDDING_TOKENS] == 8
    assert llm.attributes[LLMAttributes.OPERATION] == "embeddings"
    assert llm.attributes[LLMAttributes.INPUT_TOKENS] == 0


def test_legacy_text_completions_are_a_different_operation(spans, client, api):
    api.reply = json_reply(
        {
            "id": "cmpl-1",
            "object": "text_completion",
            "created": 1,
            "model": "gpt-3.5-turbo-instruct",
            "choices": [
                {"index": 0, "text": "hi", "finish_reason": "stop", "logprobs": None}
            ],
            "usage": {"prompt_tokens": 7, "completion_tokens": 2, "total_tokens": 9},
        }
    )

    with ags.conversation("c-legacy"):
        with ags.turn():
            client.completions.create(model="gpt-3.5-turbo-instruct", prompt="hi")

    (llm,) = llm_spans(spans)
    assert llm.attributes[LLMAttributes.OPERATION] == "text_completion"
    assert llm.attributes[LLMAttributes.INPUT_TOKENS] == 7


def test_responses_api_usage_uses_the_input_output_names(spans, client, api):
    api.reply = json_reply(response_object())

    with ags.conversation("c-responses"):
        with ags.turn():
            client.responses.create(model="gpt-4o", input="hi")

    (llm,) = llm_spans(spans)
    assert llm.attributes[LLMAttributes.INPUT_TOKENS] == 60
    assert llm.attributes[LLMAttributes.CACHE_READ_TOKENS] == 40
    assert llm.attributes[LLMAttributes.REASONING_TOKENS] == 5


# ---------------------------------------------------------------------------
# 3. Transparency
# ---------------------------------------------------------------------------


def user_loop(stream):
    """The loop everybody writes. ``choices[0]`` is the whole point."""
    return [chunk.choices[0].delta.content for chunk in stream]


def test_the_injected_usage_chunk_never_reaches_the_user(spans, client, api):
    api.reply = stream_reply(
        chat_chunk("a"), chat_chunk("b"), chat_chunk(usage=CHAT_USAGE)
    )

    with ags.conversation("c-swallow"):
        with ags.turn():
            stream = client.chat.completions.create(
                model="gpt-4o",
                messages=[{"role": "user", "content": "hi"}],
                stream=True,
            )
            assert user_loop(stream) == ["a", "b"]

    assert api.bodies()[0]["stream_options"] == {"include_usage": True}
    (llm,) = llm_spans(spans)
    assert llm.attributes[LLMAttributes.INPUT_TOKENS] == 60
    assert llm.attributes[LLMAttributes.STREAMING] is True


def test_a_caller_supplied_usage_option_is_left_alone(spans, client, api):
    """They asked for the chunk, so they get the chunk."""
    api.reply = stream_reply(chat_chunk("a"), chat_chunk(usage=CHAT_USAGE))

    with ags.conversation("c-caller-usage"):
        with ags.turn():
            stream = client.chat.completions.create(
                model="gpt-4o",
                messages=[{"role": "user", "content": "hi"}],
                stream=True,
                stream_options={"include_usage": True},
            )
            chunks = list(stream)

    assert len(chunks) == 2
    assert chunks[-1].usage.prompt_tokens == 100
    (llm,) = llm_spans(spans)
    assert llm.attributes[LLMAttributes.INPUT_TOKENS] == 60


def test_the_alias_the_caller_asked_for_survives_the_resolved_id(spans, client, api):
    """``gen_ai.request.model`` holds the id that ran and was billed, so it is
    overwritten with the provider's dated snapshot — which used to lose the
    alias people actually write in their code, and with it any answer to
    "which of my model aliases is expensive"."""
    reply = chat_completion()
    reply["model"] = "gpt-4o-2024-08-06"
    api.reply = json_reply(reply)

    with ags.conversation("c-alias"):
        with ags.turn():
            client.chat.completions.create(
                model="gpt-4o", messages=[{"role": "user", "content": "hi"}]
            )

    (llm,) = llm_spans(spans)
    assert llm.attributes[LLMAttributes.REQUEST_MODEL] == "gpt-4o-2024-08-06"
    assert llm.attributes[LLMAttributes.REQUESTED_MODEL] == "gpt-4o"


def test_a_streamed_call_keeps_the_alias_too(spans, client, api):
    """The same guarantee on the path that carries most of an agent's traffic.

    A streamed span is emitted by the recorder at the end of the stream, from
    the model it last saw on a chunk — which is the resolved snapshot. The
    requested id has to be carried separately to survive that, and it used to
    not be: every streamed call lost the alias while every blocking one kept
    it.
    """
    api.reply = stream_reply(
        dict(chat_chunk("a"), model="gpt-4o-2024-08-06"),
        dict(
            chat_chunk(usage={"prompt_tokens": 3, "completion_tokens": 1}),
            model="gpt-4o-2024-08-06",
        ),
    )

    with ags.conversation("c-alias-stream"):
        with ags.turn():
            stream = client.chat.completions.create(
                model="gpt-4o", messages=[{"role": "user", "content": "hi"}], stream=True
            )
            assert user_loop(stream) == ["a"]

    (llm,) = llm_spans(spans)
    assert llm.attributes[LLMAttributes.REQUEST_MODEL] == "gpt-4o-2024-08-06"
    assert llm.attributes[LLMAttributes.REQUESTED_MODEL] == "gpt-4o"


def test_no_requested_model_attribute_when_the_two_agree(spans, client, api):
    """Present only on the difference — its absence is the statement that the
    provider answered with exactly what was asked for."""
    api.reply = json_reply(chat_completion())

    with ags.conversation("c-same"):
        with ags.turn():
            client.chat.completions.create(
                model="gpt-4o", messages=[{"role": "user", "content": "hi"}]
            )

    (llm,) = llm_spans(spans)
    assert llm.attributes[LLMAttributes.REQUEST_MODEL] == "gpt-4o"
    assert LLMAttributes.REQUESTED_MODEL not in llm.attributes


def test_the_disabled_sdk_changes_neither_the_wire_nor_the_chunks(client, api):
    """No conversation open: the call must be byte-identical to unpatched."""
    api.reply = stream_reply(chat_chunk("a"), chat_chunk("b"))

    stream = client.chat.completions.create(
        model="gpt-4o", messages=[{"role": "user", "content": "hi"}], stream=True
    )
    assert user_loop(stream) == ["a", "b"]
    assert "stream_options" not in api.bodies()[0]


def test_a_provider_error_is_raised_unchanged_and_recorded(spans, client, api):
    """The exception reaches the caller untouched — and the span says why.

    A raised call used to leave no trace at all, which made it look like it
    never happened; now it is the error it was, with zero tokens.
    """
    api.reply = error_reply(500)

    with ags.conversation("c-error"):
        with ags.turn():
            with pytest.raises(openai.InternalServerError):
                client.chat.completions.create(
                    model="gpt-4o", messages=[{"role": "user", "content": "hi"}]
                )

    (llm,) = llm_spans(spans)
    assert LLMAttributes.ERROR in llm.attributes
    assert llm.status.status_code.name == "ERROR"
    assert llm.attributes[LLMAttributes.INPUT_TOKENS] == 0
    assert llm.attributes[LLMAttributes.REQUEST_MODEL] == "gpt-4o"

    # The span is emitted after the call, so an undated exception event would
    # be stamped a few ms past end_time — an event outside its own span.
    (event,) = llm.events
    assert event.name == "exception"
    assert llm.start_time <= event.timestamp <= llm.end_time


def test_a_stream_keeps_its_type_and_context_manager(spans, client, api):
    api.reply = stream_reply(chat_chunk("a"), chat_chunk(usage=CHAT_USAGE))

    with ags.conversation("c-identity"):
        with ags.turn():
            stream = client.chat.completions.create(
                model="gpt-4o",
                messages=[{"role": "user", "content": "hi"}],
                stream=True,
            )
            assert isinstance(stream, openai.Stream)
            with stream as s:
                assert s is stream
                assert user_loop(s) == ["a"]

    assert len(llm_spans(spans)) == 1


def test_with_raw_response_is_recorded_and_still_usable(spans, client, api):
    """A non-streaming raw response is already in memory by the time we see
    it, so reading it costs the caller nothing — and skipping it costs a lot:
    `langchain-openai` routes every chat call through `with_raw_response`, and
    the LangChain handler stands down for providers this patch covers, so
    treating it as untouchable recorded neither. No span, no tokens, no error.
    """
    api.reply = json_reply(chat_completion())

    with ags.conversation("c-raw"):
        with ags.turn():
            raw = client.chat.completions.with_raw_response.create(
                model="gpt-4o", messages=[{"role": "user", "content": "hi"}]
            )
            assert raw.http_response.status_code == 200
            # Still fully usable afterwards: parse() memoises, so ours and
            # theirs are the same object rather than two reads of one body.
            assert raw.parse().usage.prompt_tokens == 100
            assert raw.parse() is raw.parse()

    (llm,) = llm_spans(spans)
    assert llm.attributes[LLMAttributes.INPUT_TOKENS] == 60
    assert llm.attributes[LLMAttributes.OUTPUT_TOKENS] == 40
    # Injection is for streams; a non-streaming call must not acquire options
    # it never asked for.
    assert "stream_options" not in api.bodies()[0]


@pytest.mark.asyncio
async def test_an_async_raw_response_is_recorded_too(spans, aclient, api):
    api.reply = json_reply(chat_completion())

    with ags.conversation("c-raw-async"):
        with ags.turn():
            raw = await aclient.chat.completions.with_raw_response.create(
                model="gpt-4o", messages=[{"role": "user", "content": "hi"}]
            )
            assert raw.parse().usage.prompt_tokens == 100

    (llm,) = llm_spans(spans)
    assert llm.attributes[LLMAttributes.INPUT_TOKENS] == 60


def test_a_raw_wrapped_stream_is_recorded_and_the_chunk_still_swallowed(
    spans, client, api
):
    """`stream=True` through `with_raw_response` — what `langchain-openai`
    sends when `include_response_headers=True`, and until now a call that
    recorded nothing at all. `parse()` on a streamed request reads no bytes:
    it builds the lazy Stream, memoised, so the caller iterates the very
    object the patch instrumented — which is also why the usage chunk the
    patch asked for can be taken back out of their loop."""
    api.reply = stream_reply(
        chat_chunk("a"), chat_chunk("b"), chat_chunk(usage=CHAT_USAGE)
    )

    with ags.conversation("c-raw-streaming"):
        with ags.turn():
            raw = client.chat.completions.with_raw_response.create(
                model="gpt-4o",
                messages=[{"role": "user", "content": "hi"}],
                stream=True,
            )
            stream = raw.parse()
            assert raw.parse() is stream
            assert user_loop(stream) == ["a", "b"]

    assert api.bodies()[0]["stream_options"] == {"include_usage": True}
    (llm,) = llm_spans(spans)
    assert llm.attributes[LLMAttributes.INPUT_TOKENS] == 60
    assert llm.attributes[LLMAttributes.STREAMING] is True


@pytest.mark.asyncio
async def test_an_async_raw_wrapped_stream_is_recorded_too(spans, aclient, api):
    api.reply = stream_reply(chat_chunk("a"), chat_chunk(usage=CHAT_USAGE))

    with ags.conversation("c-raw-streaming-async"):
        with ags.turn():
            raw = await aclient.chat.completions.with_raw_response.create(
                model="gpt-4o",
                messages=[{"role": "user", "content": "hi"}],
                stream=True,
            )
            chunks = [chunk async for chunk in raw.parse()]
            assert [c.choices[0].delta.content for c in chunks] == ["a"]

    (llm,) = llm_spans(spans)
    assert llm.attributes[LLMAttributes.INPUT_TOKENS] == 60
    assert llm.attributes[LLMAttributes.STREAMING] is True


def test_streaming_response_helper_still_streams(spans, client, api):
    """`with_streaming_response` is the deferred case proper — marked
    "stream" by the provider rather than "true", and never inspected."""
    api.reply = stream_reply(chat_chunk("a"), chat_chunk("b"))

    with ags.conversation("c-raw-stream"):
        with ags.turn():
            with client.chat.completions.with_streaming_response.create(
                model="gpt-4o",
                messages=[{"role": "user", "content": "hi"}],
                stream=True,
            ) as response:
                chunks = list(response.parse())

    assert [c.choices[0].delta.content for c in chunks] == ["a", "b"]
    assert llm_spans(spans) == []
    assert "stream_options" not in api.bodies()[0]


@pytest.mark.asyncio
async def test_async_streaming_swallows_the_injected_chunk(spans, aclient, api):
    api.reply = stream_reply(
        chat_chunk("a"), chat_chunk("b"), chat_chunk(usage=CHAT_USAGE)
    )

    with ags.conversation("c-async-stream"):
        with ags.turn():
            stream = await aclient.chat.completions.create(
                model="gpt-4o",
                messages=[{"role": "user", "content": "hi"}],
                stream=True,
            )
            seen = [chunk.choices[0].delta.content async for chunk in stream]

    assert seen == ["a", "b"]
    (llm,) = llm_spans(spans)
    assert llm.attributes[LLMAttributes.INPUT_TOKENS] == 60


@pytest.mark.asyncio
async def test_async_non_streaming_records_once(spans, aclient, api):
    api.reply = json_reply(chat_completion())

    with ags.conversation("c-async"):
        with ags.turn():
            await aclient.chat.completions.create(
                model="gpt-4o", messages=[{"role": "user", "content": "hi"}]
            )

    assert len(llm_spans(spans)) == 1


def test_the_sdk_stream_helper_sees_what_it_would_have_seen(spans, client, api):
    """``.stream()`` builds its request through ``create``, so it inherits both
    the injection and the swallow. Its own final completion must be unaffected."""
    api.reply = stream_reply(
        {
            "id": "chatcmpl-1",
            "object": "chat.completion.chunk",
            "created": 1,
            "model": "gpt-4o",
            "choices": [
                {
                    "index": 0,
                    "delta": {"role": "assistant", "content": "hello"},
                    "finish_reason": "stop",
                }
            ],
        },
        chat_chunk(usage=CHAT_USAGE),
    )

    with ags.conversation("c-helper"):
        with ags.turn():
            with client.chat.completions.stream(
                model="gpt-4o", messages=[{"role": "user", "content": "hi"}]
            ) as stream:
                for _ in stream:
                    pass
                final = stream.get_final_completion()

    assert final.choices[0].message.content == "hello"
    assert len(llm_spans(spans)) == 1


# ---------------------------------------------------------------------------
# 4. Failure isolation
# ---------------------------------------------------------------------------


def _explode(*args, **kwargs):
    raise RuntimeError("telemetry is on fire")


def test_a_broken_recorder_cannot_break_a_plain_call(spans, client, api, monkeypatch):
    monkeypatch.setattr(openai_patch, "record_llm_call", _explode)
    api.reply = json_reply(chat_completion())

    with ags.conversation("c-broken"):
        with ags.turn():
            result = client.chat.completions.create(
                model="gpt-4o", messages=[{"role": "user", "content": "hi"}]
            )

    assert result.choices[0].message.content == "hello"


def test_a_broken_recorder_cannot_break_a_stream(spans, client, api, monkeypatch):
    monkeypatch.setattr(openai_patch, "record_llm_call", _explode)
    api.reply = stream_reply(
        chat_chunk("a"), chat_chunk("b"), chat_chunk(usage=CHAT_USAGE)
    )

    with ags.conversation("c-broken-stream"):
        with ags.turn():
            stream = client.chat.completions.create(
                model="gpt-4o",
                messages=[{"role": "user", "content": "hi"}],
                stream=True,
            )
            assert user_loop(stream) == ["a", "b"]


def test_a_broken_capturing_check_cannot_break_a_call(spans, client, api, monkeypatch):
    monkeypatch.setattr(openai_patch, "capturing", _explode)
    api.reply = json_reply(chat_completion())

    with ags.conversation("c-broken-check"):
        with ags.turn():
            result = client.chat.completions.create(
                model="gpt-4o", messages=[{"role": "user", "content": "hi"}]
            )

    assert result.choices[0].message.content == "hello"
    assert "stream_options" not in api.bodies()[0]


def test_a_malformed_chunk_cannot_break_the_users_loop(spans, client, api, monkeypatch):
    def bad_extract(item):
        raise RuntimeError("cannot read usage")

    monkeypatch.setattr(
        openai_patch, "_CHAT", openai_patch._Surface("chat", bad_extract, True)
    )
    api.reply = stream_reply(chat_chunk("a"), chat_chunk("b"))

    with ags.conversation("c-bad-chunk"):
        with ags.turn():
            stream = client.chat.completions.create(
                model="gpt-4o",
                messages=[{"role": "user", "content": "hi"}],
                stream=True,
            )
            assert user_loop(stream) == ["a", "b"]


def test_a_stream_that_errors_mid_flight_still_raises(spans, client, api):
    """The decoder rejects a malformed event; that exception is the user's."""

    def truncated(request):
        return httpx.Response(
            200,
            content=b'data: {"not": "valid json"\n\n',
            headers={"content-type": "text/event-stream"},
        )

    api.reply = truncated

    with ags.conversation("c-stream-error"):
        with ags.turn():
            stream = client.chat.completions.create(
                model="gpt-4o",
                messages=[{"role": "user", "content": "hi"}],
                stream=True,
            )
            with pytest.raises(Exception):
                list(stream)


# ---------------------------------------------------------------------------
# 5. Leaks
# ---------------------------------------------------------------------------


def test_an_abandoned_stream_records_at_most_one_span(spans, client, api):
    api.reply = stream_reply(
        chat_chunk("a"), chat_chunk("b"), chat_chunk(usage=CHAT_USAGE)
    )

    with ags.conversation("c-abandon"):
        with ags.turn():
            stream = client.chat.completions.create(
                model="gpt-4o",
                messages=[{"role": "user", "content": "hi"}],
                stream=True,
            )
            for chunk in stream:
                assert chunk.choices[0].delta.content == "a"
                break
            stream.close()
            del stream
            gc.collect()

    assert len(llm_spans(spans)) <= 1


def test_a_stream_created_but_never_iterated_leaves_no_dangling_state(
    spans, client, api
):
    api.reply = stream_reply(chat_chunk("a"), chat_chunk(usage=CHAT_USAGE))

    with ags.conversation("c-never-read"):
        with ags.turn():
            stream = client.chat.completions.create(
                model="gpt-4o",
                messages=[{"role": "user", "content": "hi"}],
                stream=True,
            )
            stream.close()
            del stream
            gc.collect()

    assert len(llm_spans(spans)) <= 1


def test_the_patch_keeps_no_per_call_state(spans, client, api):
    """Nothing accumulates in the module across calls."""
    api.reply = json_reply(chat_completion())
    before = len(vars(openai_patch))

    with ags.conversation("c-state"):
        with ags.turn():
            for _ in range(5):
                client.chat.completions.create(
                    model="gpt-4o", messages=[{"role": "user", "content": "hi"}]
                )

    assert len(vars(openai_patch)) == before
    assert len(llm_spans(spans)) == 5


# ---------------------------------------------------------------------------
# 6. No conversation scope
# ---------------------------------------------------------------------------


def test_a_call_outside_a_conversation_records_nothing(spans, client, api):
    api.reply = json_reply(chat_completion())

    result = client.chat.completions.create(
        model="gpt-4o", messages=[{"role": "user", "content": "hi"}]
    )

    assert result.choices[0].message.content == "hello"
    assert spans.get_finished_spans() == ()


def test_a_disabled_conversation_records_nothing(spans, client, api):
    api.reply = json_reply(chat_completion())

    with ags.conversation("c-off", enabled=False):
        with ags.turn():
            client.chat.completions.create(
                model="gpt-4o", messages=[{"role": "user", "content": "hi"}]
            )

    assert spans.get_finished_spans() == ()


def test_a_stream_outside_a_conversation_is_untouched(spans, client, api):
    api.reply = stream_reply(chat_chunk("a"), chat_chunk("b"))

    stream = client.chat.completions.create(
        model="gpt-4o", messages=[{"role": "user", "content": "hi"}], stream=True
    )
    assert user_loop(stream) == ["a", "b"]
    assert "stream_options" not in api.bodies()[0]
    assert spans.get_finished_spans() == ()


# ---------------------------------------------------------------------------
# Regressions found by this review
# ---------------------------------------------------------------------------


def test_usage_riding_a_content_chunk_is_never_swallowed(spans, client, api):
    """Azure, vLLM, LiteLLM and the OpenAI-compatible proxies put usage on the
    last *content* chunk instead of appending a usage-only one. Dropping it
    deletes part of the answer, which no token count is worth."""
    api.reply = stream_reply(chat_chunk("a"), dict(chat_chunk("b"), usage=CHAT_USAGE))

    with ags.conversation("c-usage-on-content"):
        with ags.turn():
            stream = client.chat.completions.create(
                model="gpt-4o",
                messages=[{"role": "user", "content": "hi"}],
                stream=True,
            )
            assert user_loop(stream) == ["a", "b"]

    (llm,) = llm_spans(spans)
    assert llm.attributes[LLMAttributes.INPUT_TOKENS] == 60


def test_usage_on_every_chunk_does_not_empty_the_stream(spans, client, api):
    """The pathological version of the same server behaviour."""
    api.reply = stream_reply(
        dict(chat_chunk("a"), usage=CHAT_USAGE), dict(chat_chunk("b"), usage=CHAT_USAGE)
    )

    with ags.conversation("c-usage-everywhere"):
        with ags.turn():
            stream = client.chat.completions.create(
                model="gpt-4o",
                messages=[{"role": "user", "content": "hi"}],
                stream=True,
            )
            assert user_loop(stream) == ["a", "b"]

    assert len(llm_spans(spans)) == 1


@pytest.mark.asyncio
async def test_an_abandoned_async_stream_still_reports_its_tokens(spans, aclient, api):
    """Nothing runs an abandoned async generator's ``finally`` in time: the
    loop schedules its finalizer, usually during shutdown and always outside
    the conversation, so the tokens were being lost outright."""
    api.reply = stream_reply(
        chat_chunk("a"), chat_chunk("b"), chat_chunk(usage=CHAT_USAGE)
    )

    with ags.conversation("c-async-abandon"):
        with ags.turn():
            stream = await aclient.chat.completions.create(
                model="gpt-4o",
                messages=[{"role": "user", "content": "hi"}],
                stream=True,
            )
            async for _ in stream:
                break
            await stream.close()

    assert len(llm_spans(spans)) == 1


@pytest.mark.asyncio
async def test_an_async_stream_used_as_a_context_manager_ends_with_it(
    spans, aclient, api
):
    api.reply = stream_reply(chat_chunk("a"), chat_chunk(usage=CHAT_USAGE))

    with ags.conversation("c-async-with"):
        with ags.turn():
            stream = await aclient.chat.completions.create(
                model="gpt-4o",
                messages=[{"role": "user", "content": "hi"}],
                stream=True,
            )
            async with stream as s:
                async for _ in s:
                    break

    (llm,) = llm_spans(spans)
    assert llm.attributes[LLMAttributes.STREAMING] is True


def test_closing_an_exhausted_stream_does_not_record_it_twice(spans, client, api):
    api.reply = stream_reply(chat_chunk("a"), chat_chunk(usage=CHAT_USAGE))

    with ags.conversation("c-close-twice"):
        with ags.turn():
            stream = client.chat.completions.create(
                model="gpt-4o",
                messages=[{"role": "user", "content": "hi"}],
                stream=True,
            )
            assert user_loop(stream) == ["a"]
            stream.close()
            stream.close()

    assert len(llm_spans(spans)) == 1


def test_injection_safety_is_decided_before_the_first_request():
    """Injecting ``include_usage`` is only allowed while we can also swallow
    the chunk it produces. Learning that from the first live stream is one
    IndexError too late, so it is read off the stream classes at install."""

    class Renamed:
        def __next__(self):
            return self._items.__next__()

        async def __anext__(self):
            return await self._items.__anext__()

    assert openai_patch._injection_is_safe(Renamed, Renamed) is False
    assert openai_patch._injection_is_safe(openai.Stream, openai.AsyncStream) is True


def test_the_injection_latch_says_so_once():
    """Losing streamed token counts must not be silent.

    The latch closes when a release stops exposing the internals the patch
    reads, and everything downstream still works — spans, durations, errors,
    every non-streamed call. What stops is token capture on streams, and its
    symptom is indistinguishable from an agent that stopped making calls. At
    DEBUG that is unanswerable in production; once at WARNING, it is a
    one-line answer.
    """

    class Recorder:
        def __init__(self):
            self.warnings = []

        def warning(self, message, *args, **kwargs):
            self.warnings.append(message)

        def debug(self, *args, **kwargs):
            pass

    recorder = Recorder()
    # The `injection_safe` fixture guarantees the latch is open here, and puts
    # it back afterwards.
    assert openai_patch._iterator_of(object(), recorder) is None
    assert openai_patch._iterator_of(object(), recorder) is None

    assert recorder.warnings == [openai_patch._INTERNALS_CHANGED]
    assert openai_patch._INJECTION_SAFE is False


def test_nothing_is_injected_when_it_could_not_be_swallowed(spans, client, api):
    monkeypatched = openai_patch._INJECTION_SAFE
    openai_patch._INJECTION_SAFE = False
    api.reply = stream_reply(chat_chunk("a"), chat_chunk("b"))
    try:
        with ags.conversation("c-unsafe"):
            with ags.turn():
                stream = client.chat.completions.create(
                    model="gpt-4o",
                    messages=[{"role": "user", "content": "hi"}],
                    stream=True,
                )
                assert user_loop(stream) == ["a", "b"]
    finally:
        openai_patch._INJECTION_SAFE = monkeypatched

    assert "stream_options" not in api.bodies()[0]


# ---------------------------------------------------------------------------
# The remaining surfaces
# ---------------------------------------------------------------------------


def test_chat_parse_is_visible_even_though_it_skips_create(spans, client, api):
    api.reply = json_reply(chat_completion())

    with ags.conversation("c-parse"):
        with ags.turn():
            client.chat.completions.parse(
                model="gpt-4o", messages=[{"role": "user", "content": "hi"}]
            )

    (llm,) = llm_spans(spans)
    assert llm.attributes[LLMAttributes.INPUT_TOKENS] == 60


def test_responses_parse_is_visible(spans, client, api):
    api.reply = json_reply(response_object())

    with ags.conversation("c-responses-parse"):
        with ags.turn():
            client.responses.parse(model="gpt-4o", input="hi")

    (llm,) = llm_spans(spans)
    assert llm.attributes[LLMAttributes.INPUT_TOKENS] == 60


def responses_events():
    return [
        {
            "type": "response.created",
            "sequence_number": 0,
            "response": dict(response_object(), status="in_progress", usage=None),
        },
        {
            "type": "response.output_text.delta",
            "sequence_number": 1,
            "item_id": "msg-1",
            "output_index": 0,
            "content_index": 0,
            "delta": "hello",
            "logprobs": [],
        },
        {
            "type": "response.completed",
            "sequence_number": 2,
            "response": response_object(),
        },
    ]


def test_a_responses_stream_is_read_but_never_modified(spans, client, api):
    """There is no ``stream_options`` on this API — usage rides the terminal
    event whether or not anyone asked, so there is nothing to inject and
    nothing to swallow."""
    api.reply = stream_reply(*responses_events())

    with ags.conversation("c-responses-stream"):
        with ags.turn():
            stream = client.responses.create(model="gpt-4o", input="hi", stream=True)
            events = list(stream)

    assert [e.type for e in events] == [
        "response.created",
        "response.output_text.delta",
        "response.completed",
    ]
    assert "stream_options" not in api.bodies()[0]
    (llm,) = llm_spans(spans)
    assert llm.attributes[LLMAttributes.INPUT_TOKENS] == 60
    assert llm.attributes[LLMAttributes.STREAMING] is True


def test_the_responses_stream_helper_records_once(spans, client, api):
    api.reply = stream_reply(*responses_events())

    with ags.conversation("c-responses-helper"):
        with ags.turn():
            with client.responses.stream(model="gpt-4o", input="hi") as stream:
                for _ in stream:
                    pass

    assert len(llm_spans(spans)) == 1


def test_a_legacy_completions_stream_reports_its_tokens(spans, client, api):
    api.reply = stream_reply(
        {
            "id": "cmpl-1",
            "object": "text_completion",
            "created": 1,
            "model": "gpt-3.5-turbo-instruct",
            "choices": [
                {"index": 0, "text": "hi", "finish_reason": None, "logprobs": None}
            ],
        },
        {
            "id": "cmpl-1",
            "object": "text_completion",
            "created": 1,
            "model": "gpt-3.5-turbo-instruct",
            "choices": [],
            "usage": {"prompt_tokens": 7, "completion_tokens": 2, "total_tokens": 9},
        },
    )

    with ags.conversation("c-legacy-stream"):
        with ags.turn():
            stream = client.completions.create(
                model="gpt-3.5-turbo-instruct", prompt="hi", stream=True
            )
            assert [c.choices[0].text for c in stream] == ["hi"]

    (llm,) = llm_spans(spans)
    assert llm.attributes[LLMAttributes.OPERATION] == "text_completion"
    assert llm.attributes[LLMAttributes.INPUT_TOKENS] == 7


@pytest.mark.asyncio
async def test_async_embeddings_are_recorded(spans, aclient, api):
    api.reply = json_reply(
        {
            "object": "list",
            "model": "text-embedding-3-small",
            "data": [{"object": "embedding", "index": 0, "embedding": [0.1]}],
            "usage": {"prompt_tokens": 8, "total_tokens": 8},
        }
    )

    with ags.conversation("c-async-embed"):
        with ags.turn():
            await aclient.embeddings.create(model="text-embedding-3-small", input="hi")

    (llm,) = llm_spans(spans)
    assert llm.attributes[LLMAttributes.EMBEDDING_TOKENS] == 8


# ---------------------------------------------------------------------------
# Ending a stream in every other way
# ---------------------------------------------------------------------------


def test_breaking_out_of_a_stream_records_exactly_one_span(spans, client, api):
    api.reply = stream_reply(
        chat_chunk("a"), chat_chunk("b"), chat_chunk(usage=CHAT_USAGE)
    )

    with ags.conversation("c-break"):
        with ags.turn():
            stream = client.chat.completions.create(
                model="gpt-4o",
                messages=[{"role": "user", "content": "hi"}],
                stream=True,
            )
            for _ in stream:
                break
            stream.close()
            del stream
            gc.collect()

    assert len(llm_spans(spans)) == 1


def test_an_exception_in_the_users_loop_still_produces_one_span(spans, client, api):
    api.reply = stream_reply(chat_chunk("a"), chat_chunk(usage=CHAT_USAGE))

    with ags.conversation("c-user-raises"):
        with ags.turn():
            stream = client.chat.completions.create(
                model="gpt-4o",
                messages=[{"role": "user", "content": "hi"}],
                stream=True,
            )
            with pytest.raises(ValueError):
                for _ in stream:
                    raise ValueError("user code")
            stream.close()
            del stream
            gc.collect()

    assert len(llm_spans(spans)) == 1


def test_two_streams_open_at_once_do_not_share_state(spans, client, api):
    api.reply = stream_reply(chat_chunk("a"), chat_chunk(usage=CHAT_USAGE))

    with ags.conversation("c-concurrent"):
        with ags.turn():
            first = client.chat.completions.create(
                model="gpt-4o", messages=[{"role": "user", "content": "1"}], stream=True
            )
            second = client.chat.completions.create(
                model="gpt-4o", messages=[{"role": "user", "content": "2"}], stream=True
            )
            assert user_loop(first) == ["a"]
            assert user_loop(second) == ["a"]

    assert len(llm_spans(spans)) == 2


def test_an_explicit_include_usage_false_is_obeyed(spans, client, api):
    """Their call, their choice: the span still records the duration."""
    api.reply = stream_reply(chat_chunk("a"))

    with ags.conversation("c-no-usage"):
        with ags.turn():
            stream = client.chat.completions.create(
                model="gpt-4o",
                messages=[{"role": "user", "content": "hi"}],
                stream=True,
                stream_options={"include_usage": False},
            )
            assert user_loop(stream) == ["a"]

    assert api.bodies()[0]["stream_options"] == {"include_usage": False}
    (llm,) = llm_spans(spans)
    assert llm.attributes[LLMAttributes.INPUT_TOKENS] == 0
    # The 0/0 counts here are unknowns, not zeros — the marker is what lets
    # ingest tell this span from one that legitimately billed nothing.
    assert llm.attributes[LLMAttributes.USAGE_REPORTED] is False


def test_a_stream_that_reports_usage_carries_no_unknown_marker(spans, client, api):
    api.reply = stream_reply(
        chat_chunk("a"),
        chat_chunk(usage={"prompt_tokens": 3, "completion_tokens": 1, "total_tokens": 4}),
    )

    with ags.conversation("c-usage"):
        with ags.turn():
            stream = client.chat.completions.create(
                model="gpt-4o",
                messages=[{"role": "user", "content": "hi"}],
                stream=True,
            )
            user_loop(stream)

    (llm,) = llm_spans(spans)
    assert llm.attributes[LLMAttributes.INPUT_TOKENS] == 3
    assert LLMAttributes.USAGE_REPORTED not in llm.attributes
