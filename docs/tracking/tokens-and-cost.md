---
outline: deep
---

<CopyMarkdownButton />

# Tokens & Cost

This is the shortest page in the documentation, because there is almost nothing
to do. **Every LLM call made inside a conversation scope is counted
automatically** — token usage, the model that actually answered, and the cost —
with no decorator, no wrapper and no counter to keep.

```python
with agentsight.conversation("wa-3859"):
    with agentsight.turn():
        agentsight.user_message(text)
        reply = client.chat.completions.create(...)   # counted
        agentsight.agent_message(reply.choices[0].message.content)
```

## What is covered

| Integration | How it attaches | What it sees |
|---|---|---|
| [OpenAI](/integrations/openai) | patches the provider client | every call, including ones a framework makes for you |
| [Anthropic](/integrations/anthropic) | patches the provider client | every call, including ones a framework makes for you |
| [LangChain](/integrations/langchain) | registers with the callback system | tool calls, plus LLM calls no provider patch covers |
| [LlamaIndex](/integrations/llamaindex) | registers with the dispatcher | tool calls, plus LLM calls no provider patch covers |

Nothing needs configuring. `init()` installs whichever of the four are importable
and skips the rest.

Models reached **through** a framework rather than through a patched provider
client — [Bedrock, Vertex AI, Ollama, LiteLLM and the
rest](/integrations/other-providers) — are recorded by the framework
integration, which is the only thing watching them. So a LangChain app
on Bedrock is counted; the same Bedrock call made directly, with no framework
involved, is not.

Running a provider integration and a framework integration together is the normal
case and **does not double-count**. A LangChain app on OpenAI produces one LLM
record from the provider side and tool records from the framework side, because
the framework side stands down on any call the provider side already sees.

## What "every call" means

Every call. Including the ones nobody thinks to track: the evaluator scoring the
answer, the router picking a path, the classifier deciding whether the question
is in scope, the summariser compressing history. Those calls are usually small
and always numerous, and they are where surprising cost hides.

That is the argument for scoping by conversation rather than counting by hand.
Anything that runs inside the scope is on the books whether or not you remembered
it existed.

:::info Prompts and completions are never sent
LLM records carry the accounting — model, token counts, timing — and nothing
else. The text of what you sent the model and what it sent back does not leave
your process. Message content does, but only the text you pass to
`user_message()` and `agent_message()` yourself.
:::

## Cost

Cost is **priced on our side, from your exact token counts**. The SDK does not
carry a rate table and does not compute a price.

That matters more than it sounds. Rates change, and published rates are sometimes
wrong; pricing server-side means your history can be **restated** when either
happens, instead of staying frozen at whatever the SDK happened to know on the
day you deployed it.

A model we have no rate for is marked **`unpriced`** — not zero. Unknown spend
reads as unknown, and it can be repriced retroactively once a rate exists for it.

## When a model cannot be named

Detection reads the model from the provider's own response, or from the arguments
of the call. A few wrappers give it neither: a hand-rolled chat model around a
self-hosted server, a custom framework LLM that reports nothing about itself.

A call with no model name is **permanently unpriceable** — no rate can ever match
it, and repricing cannot recover what was never named. `model_hint()` is where you
say what is on the other end:

```python
with agentsight.model_hint("llama3.1:8b"):
    chain.invoke(...)
```

It is strictly a fallback: a call that resolves a model of its own keeps it, and
the hint fills only the hole it left.
[Other providers](/integrations/other-providers) covers it in full, alongside the
providers that need it.

## Turning it off

`init()` installs everything importable by default. Pass `False` for none of it:

```python
agentsight.init(auto_instrument=False)
```

Or name the ones you want:

```python
agentsight.init(auto_instrument=["openai", "langchain"])
```

Valid names are `openai`, `anthropic`, `langchain` and `llama_index`. The
spellings `llamaindex`, `llama-index`, `claude` and `openai_agents` are accepted
as aliases.

:::warning A misspelled target is silent
An unrecognised name is skipped rather than reported, so
`auto_instrument=["open_ai"]` disables OpenAI capture and says nothing about it.
Check the spelling against the list above if usage stops appearing.
:::

Turning an integration off does not turn tracking off — conversations, turns,
messages and decorated tools carry on exactly as before. You lose the automatic
LLM accounting for that provider, and nothing else.

## Next

- [Tools & Actions](./tools-and-actions.md) — the other half of what happens
  inside a turn
- [Conversations](./conversations.md) — the scope that decides what gets counted
- [Configuration](/getting-started/configuration) — keys, environments, and
  logging
