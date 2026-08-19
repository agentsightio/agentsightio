---
outline: deep
---

<CopyMarkdownButton />

# LangChain

`init()` registers a callback handler with LangChain itself, so **your tools and
your models are recorded without `callbacks=[...]` appearing anywhere in your
code** — including tools nested inside a chain, which inherit it from the run
above them.

```python
agentsight.init()

with agentsight.conversation("wa-3859"):
    with agentsight.turn():
        agentsight.user_message("What is 6 times 7, and where is order A-1?")
        product = multiply.invoke({"a": 6, "b": 7})       # recorded
        answer = chain.invoke("summarise the order status")
        agentsight.agent_message(str(answer.content))
```

Threading a callback through every construction site is what an LCEL application
would otherwise have to do, and the registration is global rather than
context-scoped — so it also fires in threads your app starts, which is where a
context-scoped handler silently records nothing.

## What is recorded

| Event | Recorded | Notes |
|---|---|---|
| Tool calls | always | name, arguments, result, errors |
| LLM calls | when no provider patch covers them | see below |
| Chains, retrievers, retries | no | deliberately ignored |

**Tool calls are the reason this integration exists.** A provider patch sees the
tool *call* in the model's response but never the tool *running* — not its bound
arguments, not its result, not how long it took. Only the framework knows that.

Chains, retrievers and retries are skipped on purpose: in an LCEL app they
outnumber the events worth recording several times over, and a record per runnable
would bury the tools and the models in a tree nobody reads. What you get is what
the agent *did* and what it *spent*.

A tool that reports its failure rather than raising it — anything with
`handle_tool_error` set — is still recorded as a failure, not as a success that
happened to return an error string.

## Running alongside a provider patch

This is the normal case for a LangChain app on OpenAI or Anthropic: **both
integrations are on and nothing is double-counted.** The handler stands down on
LLM calls for any provider the patch already covers, so you get one LLM record
from the patch and tool records from the handler.

The patch wins because it reads the provider's own response object, while a
framework handler reads whatever the framework chose to surface — a lossy subset.

Two consequences of that rule worth knowing:

- **Azure OpenAI is OpenAI.** It reports itself as `azure` and runs on the
  patched client, so the patch records it and the handler stands down.
- **The OpenAI-compatible providers are covered.** DeepSeek, xAI, Together,
  Fireworks and friends are thin wrappers over the `openai` client, so the
  patch records the call and the handler stands down. The span's model id is
  the provider's own (`deepseek-chat`, never a GPT id); the provider's *name*
  appears as the reporting system only when the handler is the sole recorder —
  `auto_instrument=["langchain"]` with no OpenAI patch installed.

:::warning A new compatible provider could double-count
That last list is a list, so a provider that starts routing through the `openai`
client tomorrow is one the handler does not yet know to stand down for — and the
symptom is a doubled token count for that provider alone. The fix is one
argument: `init(auto_instrument=["langchain"])` runs the handler with no provider
patch beside it. Tell us as well, so the list stops being wrong.
:::

## Models no patch covers

For everything else — Bedrock, Vertex AI, Ollama, LiteLLM, a self-hosted
OpenAI-compatible server — **this handler is the only thing recording the call**,
so its token counts are the whole record. It reads the resolved model id under
every spelling those integrations use, which is what lets a Bedrock call carry
the platform-flavoured id that pricing needs to match.

A streamed call that reports no counts at all is marked as **having reported
nothing** rather than billed as zero, and a model that names itself to nobody can
be named with `model_hint()`. Both are on
[Other providers](./other-providers.md), which is the page for these providers.

:::warning Cache hits can report tokens nobody was billed
A cached LangChain response still reports usage through the callback, and the
handler cannot tell that answer from a fresh one. If you rely on LangChain's
cache, treat token counts as an upper bound. This is a limitation of the
callback, not a choice — see
[Deployment & limitations](/getting-started/deployment).
:::

## What you still do yourself

Messages, and only messages: `user_message()` and `agent_message()` around the
exchange, because no framework event knows which string is the text a human
actually typed. Everything between them — tools, models, tokens, latency — is
recorded without being mentioned.

Decorating a tool the handler already reports gives you **two** records for one
call. Decorate the work the framework cannot see; leave its own tools alone. See
[Tools & Actions](/tracking/tools-and-actions).

Turning the integration off is `init(auto_instrument=False)`, or a list without
`"langchain"` in it.

## Next

- [Other providers](./other-providers.md) — Bedrock, Vertex, Ollama, LiteLLM, and
  `model_hint()`
- [LlamaIndex](./llamaindex.md) — the same idea through a different mechanism
- [Tools & Actions](/tracking/tools-and-actions) — what a tool record holds, and
  when to decorate
- [Tokens & Cost](/tracking/tokens-and-cost) — how the two halves of coverage fit
  together
- [The LangChain example](/examples/langchain) — the runnable script: tools and a
  chain, with and without a real provider behind them
