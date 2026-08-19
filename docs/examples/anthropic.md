---
outline: deep
---

<CopyMarkdownButton />

# Anthropic

[`examples/03_anthropic.py`](https://github.com/agentsightio/agentsightio/blob/main/examples/03_anthropic.py)
demonstrates the [Anthropic integration](/integrations/anthropic). As with the
OpenAI example, no `agentsight` call appears near the provider:
`Messages.create` and the `client.messages.stream(...)` manager are both
wrapped, so a streamed answer produces one span with real token counts rather
than nothing.

`anthropic` is not a dependency of this project, so the script reports and
exits when the package is missing rather than faking it:

```bash
pip install anthropic
python examples/03_anthropic.py
AGENTSIGHT_EXAMPLES_OFFLINE=1 python examples/03_anthropic.py
```

## What it runs

- **A plain message** — `client.messages.create()` between the user and agent
  messages. The stub's usage block carries `cache_creation_input_tokens` and
  `cache_read_input_tokens` alongside plain input: Anthropic prices cache
  writes above plain input and cache reads far below it, so neither can be
  folded into `input_tokens` — the span keeps all four counts separate. See
  [Tokens & Cost](/tracking/tokens-and-cost).
- **A streamed message** — through the `with client.messages.stream(...)`
  manager. The manager's `__enter__` is patched, not just `create()`: a stream
  consumed through `with` reports usage only at the end, and closing the block
  is what completes the span.
- **A failure** — a request for a model that does not exist; the span records
  the error.

Two details in the script are worth stealing for real integrations. It reads
the answer with a helper that takes the first *text* block, not `content[0]` —
on a thinking-capable model the first block is a `ThinkingBlock`, and the
reasoning is not what the customer was told. And it sets `max_tokens=1024`
rather than something small: on a thinking-capable model the reasoning block
spends from the same budget as the answer, and a low cap gets eaten whole by
thinking — the span still records the capped output tokens, but the reply
comes back empty.

## What to look for in the output

Three `llm` spans in `examples/traces/03_anthropic/`. The plain message's span
carries all four token counts; the streamed one is marked streamed with usage
assembled from the stream's start and end events.
