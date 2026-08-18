---
outline: deep
---

<CopyMarkdownButton />

# OpenAI

There is nothing to wire up. `init()` patches the `openai` client's own methods,
so **every call it makes is recorded** — including the ones a framework makes on
your behalf — and no `agentsight` call appears anywhere near the provider.

```python
agentsight.init()

with agentsight.conversation("wa-3859"):
    with agentsight.turn():
        agentsight.user_message("Where is my order?")
        answer = client.chat.completions.create(
            model="gpt-4o-mini", messages=messages
        )
        agentsight.agent_message(answer.choices[0].message.content)
```

The patch is on the client's resource classes rather than on an instance, which
is why it covers `client.chat`, `client.beta.chat`, the module-level `openai.chat`
proxy and `AzureOpenAI` from one place — and why creating clients wherever you
like changes nothing.

## What is recorded

| Surface | Recorded |
|---|---|
| Chat Completions `create` | yes, streamed and blocking |
| Chat Completions `parse` (structured outputs) | yes |
| Responses API `create` / `parse` | yes |
| Legacy Completions | yes |
| Embeddings | yes, as their own billable line |
| `client.chat.completions.stream(...)` | yes |
| `with_raw_response` | yes, streaming included |
| `with_streaming_response` | **no** |

Sync and async clients both, with no separate setting.

`parse()` is patched in its own right because structured-output calls do not go
through `create()` — in an agent codebase they are often the majority of calls,
and a patch on `create` alone would miss all of them.

`with_streaming_response` is the one deliberate gap: reading that body belongs to
you, and until you read it there is genuinely nothing to record. Those calls'
tokens are not captured. See
[Deployment & limitations](/getting-started/deployment).

Each LLM record carries the model that answered, the token counts, the operation,
the duration, and — when the stream reported none — the fact that usage was never
reported. **Prompts and completions are never sent.**

## Token counts, in the units they are billed in

A single blocking chat call records more than two numbers, because the provider
prices more than two things:

| Reported | Recorded as |
|---|---|
| `prompt_tokens: 120` with `cached_tokens: 40` | 80 input + 40 cache read |
| `completion_tokens: 45` with `reasoning_tokens: 12` | 45 output, of which 12 reasoning |
| an embeddings call's 8 prompt tokens | 8 embedding tokens |

Cached input is **subtracted out of** the input count rather than left inside it,
because a cache read costs a fraction of fresh input and folding the two together
would price them the same. Reasoning tokens are a **subset** of output, not an
addition — summing them would double-count. Embedding tokens are never chat input:
different model, different rate.

Two models inside one turn — the retrieve-then-answer shape — stay separable, so
a turn that embeds a query and then answers reports each model's spend under its
own name.

## Streaming

A streamed call reports no usage at all unless the request asks for it, so **the
SDK asks for you**:

```python
stream = client.chat.completions.create(
    model="gpt-4o-mini", messages=messages, stream=True
)
for chunk in stream:
    print(chunk.choices[0].delta.content or "", end="")
```

That records full token counts, and the loop above still works.

:::info Why that loop still works
Asking for usage makes the provider append a final chunk with no `choices` in it,
which is exactly what breaks `chunk.choices[0]`. So the SDK swallows the chunk it
asked for on the way out — the option is only ever injected where the response can
still be filtered. Set `stream_options` yourself and nothing is injected and
nothing is swallowed: the stream passes through untouched and usage is read as it
goes by.
:::

Pass `stream_options={"include_usage": False}` and you get the honest outcome
instead of a wrong one: the record's duration is real, and its zero token counts
are marked as **never reported** rather than recorded as a call that cost
nothing.

:::warning If a future release moves the internals
Streamed capture reads one attribute inside the provider's stream object. If a
release stops exposing it, streamed calls report no tokens — and the SDK says so
**once, at WARNING**, on the `agentsight` logger, because the symptom otherwise
looks identical to an agent that stopped making calls. Blocking calls, durations
and errors are unaffected.
:::

## Failures are recorded, not swallowed

A call that raises is a call that happened. It is recorded as an error, carrying
the model and whatever tokens were billed before it failed, and **the exception
propagates untouched**:

```python
with agentsight.turn():
    try:
        client.chat.completions.create(
            model="gpt-does-not-exist", messages=messages
        )
    except openai.NotFoundError:
        ...
```

Without that, a failed call either disappears — inflating your success rate — or
looks like a zero-token success, which is worse.

## Calls outside a turn

An LLM call inside a conversation scope but outside any turn is still recorded; it
belongs to the conversation rather than to an exchange. That is where background
spend shows up — the classifier, the router, the summariser — and it is usually
the spend nobody expected.

Turning the integration off is `init(auto_instrument=False)`, or a list without
`"openai"` in it. See [Tokens & Cost](/tracking/tokens-and-cost).

## Next

- [Anthropic](./anthropic.md) — the same shape, and where the two providers'
  accounting differs
- [LangChain](./langchain.md) — what changes when the calls come from a framework
- [Tokens & Cost](/tracking/tokens-and-cost) — pricing, `unpriced`, and turning
  capture off
- [Streaming](/tracking/streaming) — `wrap()`, for a handler that returns before
  the stream ends
- [The OpenAI example](/examples/openai) — the runnable script: chat, both
  streaming modes, embeddings and a failure, with the payload written to disk
