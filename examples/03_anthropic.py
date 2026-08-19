"""The Anthropic patch — messages, the streaming manager, cache tokens.

Same shape as the OpenAI example and the same absence of `agentsight` calls
around the provider: `Messages.create` and the `client.messages.stream(...)`
manager are both wrapped, so a streamed answer produces one span with real
token counts rather than nothing.

`anthropic` is not a dependency of this project, so this script reports and
exits when it is missing rather than faking the package. Install it to run:

    pip install anthropic
    python examples/03_anthropic.py
    AGENTSIGHT_EXAMPLES_OFFLINE=1 python examples/03_anthropic.py
"""

import json

import _common  # noqa: F401  — puts the repository root on sys.path
import httpx

import agentsight as ags

MODEL = "claude-opus-5"
MISSING_MODEL = "claude-does-not-exist"
# On a thinking-capable model the reasoning block spends from the same budget
# as the answer; 256 gets eaten whole by thinking and the reply comes back
# empty (the span still records 256 output tokens — capped, not lost).
MAX_TOKENS = 1024

MESSAGE_BODY = {
    "id": "msg_1", "type": "message", "role": "assistant", "model": MODEL,
    "content": [{"type": "text", "text": "Order A-1 ships tomorrow."}],
    "stop_reason": "end_turn", "stop_sequence": None,
    "usage": {
        "input_tokens": 120, "output_tokens": 45,
        # Anthropic prices cache writes ABOVE plain input and cache reads far
        # below it, so neither can be folded into input_tokens.
        "cache_creation_input_tokens": 30, "cache_read_input_tokens": 200,
    },
}


def _sse(*events) -> bytes:
    return "".join(
        "event: %s\ndata: %s\n\n" % (name, json.dumps(data)) for name, data in events
    ).encode()


STREAM_EVENTS = (
    ("message_start", {"type": "message_start", "message": {
        "id": "msg_2", "type": "message", "role": "assistant", "model": MODEL,
        "content": [], "stop_reason": None, "stop_sequence": None,
        "usage": {"input_tokens": 120, "output_tokens": 0}}}),
    ("content_block_start", {"type": "content_block_start", "index": 0,
                             "content_block": {"type": "text", "text": ""}}),
    ("content_block_delta", {"type": "content_block_delta", "index": 0,
                             "delta": {"type": "text_delta", "text": "Order A-1 "}}),
    ("content_block_delta", {"type": "content_block_delta", "index": 0,
                             "delta": {"type": "text_delta", "text": "ships tomorrow."}}),
    ("content_block_stop", {"type": "content_block_stop", "index": 0}),
    ("message_delta", {"type": "message_delta", "delta": {"stop_reason": "end_turn"},
                       "usage": {"output_tokens": 45}}),
    ("message_stop", {"type": "message_stop"}),
)


def _stub(request: httpx.Request) -> httpx.Response:
    body = json.loads(request.content or b"{}")

    if body.get("model") == MISSING_MODEL:
        return httpx.Response(404, json={"type": "error", "error": {
            "type": "not_found_error", "message": "model not found"}})

    if body.get("stream"):
        return httpx.Response(200, content=_sse(*STREAM_EVENTS),
                              headers={"content-type": "text/event-stream"})

    return httpx.Response(200, json=MESSAGE_BODY)


def _first_text(blocks) -> str:
    return next((b.text for b in blocks if getattr(b, "type", None) == "text"), "")


def make_client():
    import anthropic

    if _common.live("ANTHROPIC_API_KEY"):
        return anthropic.Anthropic(max_retries=0)

    return anthropic.Anthropic(
        api_key="sk-ant-stub", max_retries=0,
        http_client=httpx.Client(transport=httpx.MockTransport(_stub)),
    )


def main() -> None:
    try:
        import anthropic  # noqa: F401
    except ImportError:
        print("anthropic is not installed — nothing to demonstrate.")
        print("  pip install anthropic")
        return

    run = _common.start("03_anthropic", auto_instrument=["anthropic"])
    client = make_client()
    question = [{"role": "user", "content": "Where is my order?"}]

    with ags.conversation("demo-anthropic", customer_id="user-12345", source="web"):
        with ags.turn("plain-message"):
            ags.user_message("Where is my order?")
            answer = client.messages.create(
                model=MODEL, max_tokens=MAX_TOKENS, messages=question
            )
            # Not content[0]: on a thinking-capable model the first block is a
            # ThinkingBlock, and the reasoning is not what the customer said.
            ags.agent_message(_first_text(answer.content))

        with ags.turn("streamed"):
            # The manager's __enter__ is patched, not just create(): a stream
            # consumed through `with` reports usage only at the end, and
            # closing the block early is what decides whether a span exists.
            ags.user_message("And the other one?")
            with client.messages.stream(
                model=MODEL, max_tokens=MAX_TOKENS, messages=question
            ) as stream:
                text = "".join(stream.text_stream)
            ags.agent_message(text)

        with ags.turn("failure"):
            ags.user_message("break something")
            try:
                client.messages.create(
                    model=MISSING_MODEL, max_tokens=16, messages=question
                )
            except Exception as exc:
                print(f"call failed as intended: {type(exc).__name__}")

    run.finish()


if __name__ == "__main__":
    main()
