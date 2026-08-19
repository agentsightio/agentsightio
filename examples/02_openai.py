"""The OpenAI patch — chat, streaming, embeddings and a failure.

No `agentsight` call appears anywhere near the OpenAI calls. The patch wraps
the provider SDK's own methods, so it sees every call, including ones a
framework makes on your behalf.

Runs against the real API when `OPENAI_API_KEY` is set — including one loaded
from the repository's `.env`, which importing `agentsight` does for you, so
check the banner before assuming this is free. Otherwise it drives a real
`openai` client over an `httpx.MockTransport`, the technique the test suite
uses: every line of the patch still executes, only the socket is replaced.

    venv/bin/python examples/02_openai.py
    AGENTSIGHT_EXAMPLES_OFFLINE=1 venv/bin/python examples/02_openai.py
"""

import json

import _common  # noqa: F401  — puts the repository root on sys.path
import httpx

import agentsight as ags

MODEL = "gpt-4o-mini"
EMBEDDING_MODEL = "text-embedding-3-small"
#: Fails identically against the stub and against the real API.
MISSING_MODEL = "gpt-does-not-exist"


# ---------------------------------------------------------------------------
# The stub, used when there is no key. Canned bodies, real client, real patch.
# ---------------------------------------------------------------------------

CHAT_BODY = {
    "id": "chatcmpl-1", "object": "chat.completion", "created": 1, "model": MODEL,
    "choices": [{"index": 0, "finish_reason": "stop",
                 "message": {"role": "assistant", "content": "Order A-1 ships tomorrow."}}],
    "usage": {
        "prompt_tokens": 120, "completion_tokens": 45, "total_tokens": 165,
        # Cached input is billed at a different rate, so it is never folded
        # into prompt_tokens; reasoning is a *subset* of completion_tokens.
        "prompt_tokens_details": {"cached_tokens": 40},
        "completion_tokens_details": {"reasoning_tokens": 12},
    },
}

EMBEDDING_BODY = {
    "object": "list", "model": EMBEDDING_MODEL,
    "data": [{"object": "embedding", "index": 0, "embedding": [0.1, 0.2, 0.3]}],
    "usage": {"prompt_tokens": 8, "total_tokens": 8},
}


def _sse(*chunks) -> bytes:
    body = "".join("data: %s\n\n" % json.dumps(c) for c in chunks)
    return (body + "data: [DONE]\n\n").encode()


def _chunk(content=None, usage=None):
    chunk = {
        "id": "chatcmpl-1", "object": "chat.completion.chunk", "created": 1,
        "model": MODEL,
        "choices": [] if content is None
        else [{"index": 0, "delta": {"content": content}, "finish_reason": None}],
    }
    if usage is not None:
        chunk["usage"] = usage
    return chunk


def _stub(request: httpx.Request) -> httpx.Response:
    body = json.loads(request.content or b"{}")

    if request.url.path.endswith("/embeddings"):
        return httpx.Response(200, json=EMBEDDING_BODY)

    if body.get("model") == MISSING_MODEL:
        return httpx.Response(404, json={"error": {"message": "model not found"}})

    if body.get("stream"):
        chunks = [_chunk("Order "), _chunk("A-1 "), _chunk("ships tomorrow.")]
        # The provider only sends a usage chunk when asked to. When it does
        # not, the span records `usage_reported=false` rather than zeros.
        if (body.get("stream_options") or {}).get("include_usage"):
            chunks.append(_chunk(usage={"prompt_tokens": 120, "completion_tokens": 45,
                                        "total_tokens": 165}))
        return httpx.Response(200, content=_sse(*chunks),
                              headers={"content-type": "text/event-stream"})

    return httpx.Response(200, json=CHAT_BODY)


def make_client():
    import openai

    if _common.live("OPENAI_API_KEY"):
        return openai.OpenAI(max_retries=0)

    return openai.OpenAI(
        api_key="sk-stub", max_retries=0,
        http_client=httpx.Client(transport=httpx.MockTransport(_stub)),
    )


# ---------------------------------------------------------------------------


def main() -> None:
    run = _common.start("02_openai", auto_instrument=["openai"])
    client = make_client()
    question = [{"role": "user", "content": "Where is my order?"}]

    with ags.conversation("demo-openai", customer_id="user-12345", source="web"):
        with ags.turn("plain-chat"):
            ags.user_message("Where is my order?")
            answer = client.chat.completions.create(model=MODEL, messages=question)
            ags.agent_message(answer.choices[0].message.content)

        with ags.turn("streamed"):
            ags.user_message("And the other one?")
            stream = client.chat.completions.create(
                model=MODEL, messages=question, stream=True,
                stream_options={"include_usage": True},
            )
            text = "".join(c.choices[0].delta.content or ""
                           for c in stream if c.choices)
            ags.agent_message(text)

        with ags.turn("streamed-without-usage"):
            # Same call, usage not requested. The span's duration is real; its
            # zero token counts are unknowns, and carry a marker saying so, so
            # no rollup can read them as a free call.
            ags.user_message("once more")
            stream = client.chat.completions.create(
                model=MODEL, messages=question, stream=True,
                stream_options={"include_usage": False},
            )
            for _ in stream:
                pass

        with ags.turn("embeddings"):
            # Embedding tokens are their own billable line, never a subset.
            client.embeddings.create(model=EMBEDDING_MODEL, input="where is my order")

        with ags.turn("retrieve-then-answer"):
            # Two models inside one turn — the RAG shape. Their spend must
            # stay separable: token counts from different models are not the
            # same unit, so accounting keys on (turn, model), never the turn
            # alone.
            ags.user_message("what was that tracking number again?")
            client.embeddings.create(model=EMBEDDING_MODEL,
                                     input="tracking number for order A-1")
            answer = client.chat.completions.create(model=MODEL, messages=question)
            ags.agent_message(answer.choices[0].message.content)

        with ags.turn("failure"):
            ags.user_message("break something")
            try:
                client.chat.completions.create(model=MISSING_MODEL, messages=question)
            except Exception as exc:
                # The span is written with the error and whatever tokens were
                # billed before it failed — not dropped, not disguised as a
                # zero-token success.
                print(f"call failed as intended: {type(exc).__name__}")

        # No turn at all: a background classification, the kind of spend that
        # is easy to forget and lands as turnless usage.
        client.chat.completions.create(model=MODEL, messages=question)

    run.finish()


if __name__ == "__main__":
    main()
