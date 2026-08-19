---
outline: deep
---

<CopyMarkdownButton />

# LlamaIndex

`init()` attaches to LlamaIndex's own dispatcher, so **your tool calls and your
model calls are recorded with no wiring at all** — no callback manager to set, no
handler to pass, and nothing to change about how your agents are built.

```python
agentsight.init()

async def handle(question: str):
    with agentsight.conversation("wa-3859"):
        with agentsight.turn():
            agentsight.user_message(question)
            result = await agent.run(question)
            agentsight.agent_message(str(result))
```

The dispatcher is process-wide, which is what makes this work in real
applications: agent code builds its models at import, **before `init()` runs**, so
anything that had to be installed onto an object would reach nothing.

## What is recorded

| Event | Recorded | Notes |
|---|---|---|
| Tool calls | always | name, arguments, result, errors |
| LLM calls | when no provider patch covers them | see below |
| Retrievers, query engines, workflow steps | no | deliberately ignored |

**Tool calls are the reason this integration exists**, and the reason is worth
stating plainly: in a real agent the tools are framework objects — tool-spec
methods registered through `to_tool_list()`, where the framework introspects each
signature and docstring to build the schema the model sees. Decorating those means
editing every class that defines one and risking the agent's own behaviour. This
records them where they run instead, and costs you nothing.

Arguments are recorded as the model actually chose them rather than as the
framework's wrapper shape, so a tool record reads like the call the agent made.

A tool that reports failure in its output instead of raising — which is how an
agent loop usually receives one — is still recorded as a failure:

```
tool  multiply       0.3ms  ok      {"a": 6, "b": 7}  ->  42
tool  broken_tool    0.4ms  error   upstream inventory service is down
```

## Running alongside a provider patch

A LlamaIndex app on OpenAI has two things watching the same call. **They do not
both record it:** the handler stands down on LLM calls for any provider a patch
already covers, so you get exactly one LLM record per call, plus tool records the
patch could never produce.

The patch wins because it reads the provider's own usage object; this handler
reads what LlamaIndex surfaces, which drops the cache counters.

One more double that is handled for you: LlamaIndex implements `chat` in terms of
`complete` (or the reverse) for any model that provides only one of them, and both
halves announce themselves. **One API call is recorded once** — the outer call,
the one your application actually made.

## Models no patch covers

For a model reached only through LlamaIndex — Bedrock, Vertex AI, Ollama,
LiteLLM, a custom LLM class of your own — this handler is the only thing recording
it, so its counts are the whole record. A streamed call that surfaces no counts is
marked as **having reported nothing** rather than billed as zero.

A vendor it cannot identify is reported as unknown rather than guessed at. That is
deliberate — guessing "openai" because most LlamaIndex apps are OpenAI apps would
suppress the record entirely, on the grounds that a patch was covering it — and it
is what `model_hint()` is for:

```python
with agentsight.model_hint("llama3.1:8b"):
    response = await agent.run(question)
```

[Other providers](./other-providers.md) has the full treatment.

## What you still do yourself

Messages, and only messages. Everything between `user_message()` and
`agent_message()` — every tool call, every model call, the token counts and the
latency — is captured without being named.

Decorating a tool the handler already reports gives you **two** records for one
call. Decorate the functions the framework never sees; leave its own tools alone.
See [Tools & Actions](/tracking/tools-and-actions).

Turning the integration off is `init(auto_instrument=False)`, or a list without
`"llama_index"` in it. The spellings `llamaindex` and `llama-index` are accepted
as aliases.

## Next

- [Other providers](./other-providers.md) — Bedrock, Vertex, Ollama, LiteLLM, and
  `model_hint()`
- [LangChain](./langchain.md) — the same idea through a different mechanism
- [Tools & Actions](/tracking/tools-and-actions) — what a tool record holds, and
  when to decorate
- [Streaming](/tracking/streaming) — `wrap()`, for an agent whose answer streams
  out of your handler
- [The LlamaIndex example](/examples/llamaindex) — the runnable script: framework
  tools the handler sees, and the stand-down rule demonstrated live
