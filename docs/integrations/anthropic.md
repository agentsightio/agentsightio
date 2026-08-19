---
outline: deep
---

<CopyMarkdownButton />

# Anthropic

Same shape as [OpenAI](./openai.md) and the same absence of `agentsight` calls
around the provider: `init()` patches the `anthropic` client's own methods, so
**every message and every stream is recorded**, with real token counts including
the two cache lines.

```python
agentsight.init()

with agentsight.conversation("wa-3859"):
    with agentsight.turn():
        agentsight.user_message("Where is my order?")
        answer = client.messages.create(
            model="claude-opus-5", max_tokens=1024, messages=messages
        )
        text = next(b.text for b in answer.content if b.type == "text")
        agentsight.agent_message(text)
```

The first content block is not always the answer — on a thinking-capable model it
is the reasoning, and reasoning is not what you want in a transcript your client
reads.

## What is recorded

| Surface | Recorded |
|---|---|
| `messages.create` | yes, streamed and blocking |
| `messages.parse` (structured outputs) | yes |
| `client.messages.stream(...)` | yes |
| `beta.messages` — including `tool_runner` loops | yes |
| `with_raw_response` | yes, streaming included |
| `with_streaming_response` | **no** |
| Legacy Text Completions | **no** |

Sync and async clients both.

Three of those need a patch of their own rather than riding on `create`, and it is
worth knowing why the coverage is what it is: `parse()` and `stream()` build their
own requests, and `beta.messages` is a different class that happens to share a
name. Miss any one of them and the calls that go missing are the idiomatic ones.

`stream()` is instrumented where the request actually fires — entering the `with`
block, not calling the method — so a stream consumed the idiomatic way produces
one record with real counts rather than nothing:

```python
with agentsight.turn():
    agentsight.user_message("And the other one?")
    with client.messages.stream(
        model="claude-opus-5", max_tokens=1024, messages=messages
    ) as stream:
        text = "".join(stream.text_stream)
    agentsight.agent_message(text)
```

Legacy Text Completions is left alone deliberately: those responses carry no usage
at all, so the record could only ever show a model and a duration with zero
tokens — indistinguishable from a call that was free.
`with_streaming_response` is the other gap, for the reason it is on every
provider: reading that body belongs to you. See
[Deployment & limitations](/getting-started/deployment).

## Cache tokens are their own lines

Anthropic prices cache writes **above** plain input and cache reads far below it,
so neither can be folded into the input count. One blocking call reporting
`input 120`, `cache_read 200`, `cache_creation 30` is recorded as three separate
numbers — 350 billable tokens in total, and each priced at its own rate.

Input here is already the uncached remainder, which is the opposite of how OpenAI
reports it; the SDK normalises both so a mixed-provider deployment adds up.

:::info Extended thinking has no breakdown
Thinking is billed inside output tokens and the API exposes no separate counter,
so reasoning reads 0 on this provider rather than a fabricated split. If a
breakdown ever appears it is captured without you upgrading anything.
:::

## Claude on Bedrock and Vertex

`AnthropicBedrock`, `AnthropicVertex` and their siblings build the very same
messages resource, so **the same patch covers them** — token counts are exact and
complete on those platforms.

What changes is the model id: those platforms report platform-flavoured names
(`anthropic.claude-...-v2:0`, `claude-...@20240229`), and a name we have no rate
for reads as **`unpriced`** rather than as zero. The tokens are still exact, so
that spend is restated as soon as a rate exists for the id.

Claude reached through a framework instead of through the `anthropic` client is a
different path — see [Other providers](./other-providers.md).

## Streaming, failures, and calls outside a turn

Usage arrives split across two events on a stream, and the counts are cumulative
totals rather than deltas; both are merged into one record, so a streamed answer
is one LLM call and not one per chunk. A stream that ends without ever reporting
usage is marked as **having reported nothing** — never billed as an authoritative
zero.

A call that raises is recorded as an error carrying the model and any tokens
billed before the failure, then re-raised untouched. A stream that fails before
the first event still records the model you asked for, which is the only name that
call will ever have.

A call inside a conversation scope but outside any turn belongs to the
conversation rather than to an exchange, which is where background spend surfaces.

## Next

- [OpenAI](./openai.md) — the other patched provider, and the streamed-usage
  story that differs there
- [Other providers](./other-providers.md) — Claude through Bedrock or Vertex via a
  framework, and `model_hint()`
- [Tokens & Cost](/tracking/tokens-and-cost) — pricing, `unpriced`, and turning
  capture off
- [Streaming](/tracking/streaming) — `wrap()`, for a handler that returns before
  the stream ends
- [The Anthropic example](/examples/anthropic) — the runnable script: messages,
  the `stream()` manager and cache tokens, with the payload written to disk
