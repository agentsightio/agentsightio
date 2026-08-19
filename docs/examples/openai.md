---
outline: deep
---

<CopyMarkdownButton />

# OpenAI

[`examples/02_openai.py`](https://github.com/agentsightio/agentsightio/blob/main/examples/02_openai.py)
demonstrates the [OpenAI integration](/integrations/openai). No `agentsight`
call appears anywhere near the OpenAI calls — the patch wraps the provider
SDK's own methods, so it sees every call, including ones a framework makes on
your behalf.

```bash
python examples/02_openai.py
AGENTSIGHT_EXAMPLES_OFFLINE=1 python examples/02_openai.py
```

With `OPENAI_API_KEY` set — including one picked up from a `.env` file — the
script makes real, billed calls and says so first. Without it, a real `openai`
client runs over an `httpx.MockTransport`: every line of the patch still
executes, only the socket is replaced.

## What it runs

Inside one conversation, a turn for each shape worth knowing:

- **Plain chat** — one `client.chat.completions.create()` between the user and
  agent messages. The span carries the model, token counts, and the cached and
  reasoning token details the provider reports.
- **Streaming, usage requested** — `stream=True` with
  `stream_options={"include_usage": True}`. One span, real token counts,
  marked as streamed.
- **Streaming, usage not requested** — the same call without the usage chunk.
  The span's duration is real; its token counts are unknowns and carry
  `usage_reported=false`, so no rollup can read them as a free call. See
  [Tokens & Cost](/tracking/tokens-and-cost).
- **Embeddings** — embedding tokens are their own billable line, never a
  subset of chat spend.
- **Retrieve-then-answer** — an embedding call and a chat call inside one
  turn, the RAG shape. Token counts from different models are not the same
  unit, so spend is accounted per model within the turn, never per turn alone.
- **A failure** — a request for a model that does not exist. The span is
  written with the error and whatever tokens were billed before it failed —
  not dropped, not disguised as a zero-token success.
- **Turnless spend** — a final call outside any turn: the background
  classification kind of spend that is easy to forget. It still lands, attached
  to the conversation.

## What to look for in the output

Seven `llm` spans in `examples/traces/02_openai/`. Compare the two streamed
ones: same call, but only the one that asked for usage has token counts — the
other says `USAGE UNREPORTED` in the printed tree. The failed call's span
records the error type instead of vanishing.
