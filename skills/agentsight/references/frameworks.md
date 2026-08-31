# Providers and frameworks

What `auto_instrument` covers, what it deliberately does not, and the rules
that keep token counts honest. Never claim automatic where it isn't — the
tables below are the truth to repeat to the developer.

## Contents

- [The four targets](#the-four-targets)
- [OpenAI](#openai)
- [Anthropic](#anthropic)
- [LangChain](#langchain)
- [LlamaIndex](#llamaindex)
- [Everything else: the framework is the only recorder](#everything-else-the-framework-is-the-only-recorder)
- [model_hint()](#model_hint)
- [What an LLM record carries](#what-an-llm-record-carries)

## The four targets

`init(auto_instrument=…)` takes `True` (all), `False` (none), or a list of:
`"openai"`, `"anthropic"`, `"langchain"`, `"llama_index"`. A missing package
is skipped quietly; a **misspelled target is skipped silently** — copy the
names exactly.

Provider patches (`openai`, `anthropic`) read the provider's own usage object
— exact counts, cache counters included. Framework handlers (`langchain`,
`llama_index`) record **tool calls always**, and LLM calls **only where no
provider patch covers them**. Running both together is normal and does not
double-count: the framework side stands down on any LLM call the provider
side already sees, because the patch's numbers are better.

LLM calls are recorded wherever they happen; they attach to the active turn
when one exists, and spend outside any turn is still counted.

## OpenAI

Covered (sync and async, including Azure clients): Chat Completions `create`
**and** `parse` (structured outputs bypass `create`), legacy text
completions, `Embeddings.create` (its own billable line — never mixed into
chat input), the Responses API, and `chat.completions.stream(...)`.

- **Streaming:** with `stream=True` and no `stream_options` set by the caller,
  the SDK asks OpenAI to include usage and absorbs the trailing usage-only
  chunk so `chunk.choices[0]` keeps working in the app's own loop. A caller
  that sets `stream_options` itself is left alone.
- `with_raw_response` **is** recorded (this matters: `langchain-openai` routes
  chat calls through it). `with_streaming_response` is **not** — see the
  limitations below.

## Anthropic

Covered (sync and async): `messages.create`, `messages.parse`, the
`messages.stream(...)` context manager, and the beta surface including
tool-runner loops. The Bedrock / Vertex / platform client variants build the
same messages resource, so they are covered too — **token counts exact**, but
their platform-flavoured model ids (`anthropic.claude-…`, `…@20240229`) may be
reported as `unpriced` until a rate exists for that exact id. Legacy Text
Completions are not covered (the response carries no usage at all).

Cache read/write tokens are recorded as their own lines. Anthropic reports no
reasoning-token breakdown, so that column is 0 there by design.

## LangChain

A globally registered callback handler — **no `callbacks=[…]` to pass, no
code change**; it also fires in threads the app starts.

- **Tool calls are recorded without decoration** — framework-defined tools
  arrive with durations, arguments, results, and failures. Do not decorate
  them (two spans per call otherwise).
- LLM calls: recorded by the handler **only** for providers no patch covers
  (Ollama, Bedrock via LangChain, etc.). OpenAI-compatible wrappers
  (DeepSeek, Together, Fireworks, xAI, and friends) are treated as covered by
  the OpenAI patch. If a brand-new OpenAI-compatible provider ever
  double-counts, the remedy is `init(auto_instrument=["langchain"])` — handler
  only, no patch.
- **Cache caveat:** a cached response still reports usage through the
  callback, and the handler cannot tell it from a fresh one. With LangChain's
  cache enabled, treat token totals as an upper bound — a fact to put in
  front of the developer, not to decide for them.
- The framework surfaces a lossy subset of provider usage — cache counters
  are usually absent on handler-recorded calls.

## LlamaIndex

Attached to LlamaIndex's own instrumentation dispatcher at `init()` — no
`Settings` change, no global handler slot taken.

- `FunctionTool` calls are recorded (arguments as the model actually called
  them, failures flagged). Same rule: don't decorate what it already reports.
- Chat implemented in terms of `complete` records **once**, not twice.
- LLM stand-down works as in LangChain: the provider patch wins where
  installed.

## Everything else: the framework is the only recorder

Direct Bedrock (`boto3`), Vertex SDK, Ollama HTTP, LiteLLM, a self-hosted
OpenAI-compatible server, a hand-written model class — **no patch exists, and
there is no setting to switch on.** Reached through LangChain or LlamaIndex
they are recorded; called directly they are not, because nothing in the path
announces the call.

When the code makes direct calls, put three honest options to the developer:

1. Reach the model through a framework — recorded.
2. Wrap the call site in `@agentsight.task` — shape and duration on the
   record, **no token counts**.
3. Accept the gap, named in the report.

Related limitations to state up front when they apply:

- **`with_streaming_response` produces no span** (OpenAI and Anthropic both).
  Ordinary `stream=True` is fully recorded — this is only about the wrapper
  that hands over the raw HTTP body. Tokens spent through it are not captured.
  Accept or switch those call sites — the developer's call.
- **A stream that ends without a usage event is marked as unreported, not
  billed as zero.** Unknown spend reads as unknown.
- **A very large single exchange** may outgrow one transmission and be partly
  unaccounted on the dashboard. Normal exchanges are nowhere near this.

## model_hint()

Detection reads the model from the provider's response or the call's own
arguments. A wrapper that yields neither produces a record with **no model
name — permanently unpriceable**. A missing *rate* is fixed later and repriced
retroactively; a missing *name* cannot be recovered. `model_hint()` is where
the developer says what is on the other end:

```python
with agentsight.model_hint("llama3.1:8b"):
    answer = chain.invoke(text)

@agentsight.model_hint("llama3.1:8b")      # decorator form, async-safe
async def classify(text: str) -> str: ...
```

The rules that make a broad hint safe:

| Situation | Recorded |
|---|---|
| the call resolved a model of its own | that model — hint ignored |
| the call resolved nothing | the hint, marked as *declared* |
| hints nested | the innermost |
| `model_hint(None)` inside a hint | no hint, for that block |

Strictly a fallback — it can name a nameless call, never mislabel a resolved
one, so wrapping a whole handler in one is safe. The hint is read when the
call **starts**, so a stream created inside the block is covered when it
drains later; LangChain's `.stream()` starts on iteration, so keep the block
around the iteration. The model name behind a wrapper is something only the
developer knows — ask them.

**Unpriced is not zero.** A named model with no rate records exact tokens and
`unpriced` cost; when a rate exists, history is restated. `0` would claim the
call was free — the SDK never makes that claim.

## What an LLM record carries

Accounting only: model (and whether it was declared via hint), token counts
(input, output, cache read/write, reasoning and audio as subsets, embeddings
as their own line), timing, and error class. **Prompts, completions, and
embedding vectors are never sent.** Cost is priced server-side from the token
counts — the SDK sends no cost figure, so a wrong rate can be corrected and
history restated.
