---
outline: deep
---

<CopyMarkdownButton />

# Other providers

Bedrock, Vertex AI, Ollama, LiteLLM, a self-hosted OpenAI-compatible server, a
model class you wrote yourself. There is no patch for any of these, and there is
no setting to switch on: **they are recorded through whichever framework you
reach them with**, and this page is about the two things that behave differently
when nothing but the framework is watching.

```python
agentsight.init()   # nothing provider-specific to configure

with agentsight.conversation("wa-3859"):
    with agentsight.turn():
        agentsight.user_message(text)
        answer = chain.invoke(text)          # Bedrock, Ollama, LiteLLM ...
        agentsight.agent_message(answer.content)
```

:::warning The framework is the only recorder
A model reached through [LangChain](./langchain.md) or
[LlamaIndex](./llamaindex.md) is recorded. **The same model called directly — a
`boto3` client, a Vertex SDK call, an HTTP request to Ollama — is not**, because
there is nothing in the path that announces it. If a provider matters enough to
account for, reach it through a framework, or record the work around it with
[`@agentsight.task`](/tracking/tools-and-actions) so at least the call's shape
and duration are on the record.
:::

## What is recorded, and how well

The token counts these providers report are read and recorded like any other, and
the model id is read **wherever the integration puts it** — the standardised key
the mainstream providers adopted, and also the older `model` and `model_id` that
the unpatched ones are still on (Ollama reports the first, Bedrock the second).
That matters more than it looks: Bedrock's platform-flavoured id is the name a
rate has to match, so a call carrying it can be priced, and a call carrying only
your configured alias cannot.

The gaps, stated honestly:

- **Cache counters are usually absent.** The frameworks surface a lossy subset of
  what a provider reports, which is exactly why a provider patch wins wherever one
  exists.
- **A stream that reports no counts is marked, not billed as zero.** These are the
  providers most likely to end a stream without saying what it billed, and unknown
  spend reads as unknown rather than as a call that was free.
- **A model with no name is unpriceable** — the subject of the rest of this page.

## When a model cannot be named

Detection reads the model from the provider's response, or from the call's own
arguments. A few wrappers give it neither: a hand-rolled chat model around a
self-hosted server, a custom framework LLM that reports nothing about itself. The
record then names the system and no model at all.

**That is permanent.** With no name on the record, no rate can ever match it —
and unlike a missing rate, which is filled in later and repriced retroactively, a
missing *name* cannot be recovered. `model_hint()` is where you say what is on the
other end:

```python
with agentsight.model_hint("llama3.1:8b"):
    answer = chain.invoke(text)
```

It works as a decorator too, and both forms are async-safe:

```python
@agentsight.model_hint("llama3.1:8b")
async def classify(text: str) -> str:
    ...
```

### The rules that make a broad hint safe

| Situation | What is recorded |
|---|---|
| the call resolved a model of its own | that model — the hint is ignored |
| the call resolved nothing | the hint, marked as declared |
| hints nested | the innermost one |
| `model_hint(None)` inside a hint | no hint, for that block only |

The hint is **strictly a fallback**. A call that names itself keeps its own name
however many hint blocks it is running inside, so at worst a hint names a call that
would otherwise be nameless — it can never mislabel one that was resolved. That is
what makes it safe to wrap a whole chain, or a whole handler, in one.

Filled records are marked as carrying a **declared** model, so an assertion you
made stays distinguishable from a measurement the provider reported. It is worth
setting anyway: a named call is priced now, or the day a rate exists for it. A
nameless one is priced never.

:::info When the hint is read
At the moment the call starts, not when the record is written — so a stream created
inside the block is still covered when it drains long after the block exits. The
one shape to watch is a lazily-started stream: LangChain's `.stream()` does not
start the call until you iterate it, so keep the block around the iteration rather
than around the call that built it.
:::

## Unpriced is not zero

A model with a name but no rate is recorded as **`unpriced`**, and its tokens are
exact. Cost is priced on our side, so the day a rate exists for that id its whole
history is restated — nothing is lost by having deployed before we had one.

`0`, by contrast, would be a claim: that the call was free. Nothing in the SDK ever
makes that claim on your behalf.

## Next

- [LangChain](./langchain.md) — the handler recording these calls, and its
  stand-down rules
- [LlamaIndex](./llamaindex.md) — the same, through the dispatcher
- [Tokens & Cost](/tracking/tokens-and-cost) — pricing, coverage, and turning
  capture off
- [What the SDK sends](/getting-started/what-the-sdk-sends) — every field an LLM
  record carries
