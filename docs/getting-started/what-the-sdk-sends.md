---
outline: deep
---

<CopyMarkdownButton />

# What the SDK sends

Every piece of data in this page comes from a call you wrote — `user_message()`,
`agent_message()`, a `@tool` decorator, a `conversation()` scope. Nothing is
scraped from your process, inferred from your traffic, or picked up ambiently.
You decide what is instrumented, and that decides what is sent.

That matters because integrating AgentSight is a data-processing decision you
are making on behalf of your own users. You should be able to predict the
payload before you ship, not discover it afterwards — so the whole of it is
listed below, and the first section is how to check the list against your own
application rather than take our word for it.

## See it yourself, before you send anything

Point `AGENTSIGHT_FILE_EXPORTER` at a directory and the SDK writes what it would
have transmitted, and transmits nothing. No API key, no account, no network.

```bash
AGENTSIGHT_FILE_EXPORTER=./agentsight-traces python your_app.py
```

You get one JSON file per batch, named so a plain directory listing is in export
order:

```bash
ls ./agentsight-traces/
# 20260815T105829.710Z-0001.json
# 20260815T105834.712Z-0002.json

jq '.conversations[].spans[] | {kind, name, attributes}' ./agentsight-traces/*.json
```

:::info These are the bytes, not a preview
The file and the network path are built by the same function, so what you read
here is exactly what would have been sent. Nothing is summarised, sampled or
reshaped on the way out.
:::

It is a development aid — it does not retry, batch by size or bound its disk
use — so use it to inspect an integration, not to run one in production.

## The shape of a payload

Spans, grouped by conversation:

```json
{
  "sdk": { "name": "agentsight-python", "version": "0.1.0" },
  "conversations": [
    {
      "conversation_id": "demo-plain",
      "customer_id": "user-12345",
      "source": "web",
      "spans": [ /* whole spans, oldest first */ ]
    }
  ]
}
```

And one span, whole:

```json
{
  "span_id": "585174cf073aeb9a",
  "trace_id": "8b1f0e1c9d5a4c2f9e3b7a6d4c8e2f10",
  "parent_span_id": null,
  "kind": "tool",
  "name": "search_orders",
  "started_at": "2026-08-15T10:58:29.710236+00:00",
  "ended_at": "2026-08-15T10:58:29.710441+00:00",
  "duration_ms": 0.205,
  "status": "ok",
  "attributes": { /* the tables below */ },
  "events": [ /* messages, exceptions */ ],
  "otel": { /* the OpenTelemetry envelope */ }
}
```

## What each call sends

### A message

`user_message()` and `agent_message()` record the text you passed, as a
timestamped event on the turn.

| Attribute | When | Example |
|---|---|---|
| `agentsight.message.sender` | always | `"end_user"` or `"agent"` |
| `agentsight.message.content` | always | `"Where is my order?"` |
| `agentsight.message.metadata` | only if you pass `metadata=` | `{"channel": "whatsapp"}` as JSON |

The content is the string you passed, unchanged. It is the transcript your
client reads, which is why it is never inferred from anywhere else: a rewritten
prompt or an image description is not what the human typed.

### A tool or task

`@tool` and `@task` record the call, and **every argument the function
received**.

| Attribute | When | Example |
|---|---|---|
| `agentsight.tool.name` | always | `"search_orders"` |
| `agentsight.tool.arguments` | always | `{"customer_id": "user-12345", "status": "open"}` as JSON |
| `agentsight.tool.response` | if it returned | `"[{'id': 'A-1', 'total': 42.0}]"` |
| `agentsight.tool.error` | only on failure | the exception's message |

Arguments are bound to their parameter names and serialised, so keyword and
positional calls produce the same record. `self` is dropped. This is the one
place worth reading twice before you instrument: if a decorated function takes a
card number, a password or a national ID, that value is sent.

:::warning Arguments are captured in full
There is no field-level exclusion yet. To keep a value out of the payload, keep
it out of the decorated function's signature — pass it through a closure, an
object attribute, or a lookup inside the body. See
[Controlling what is sent](#controlling-what-is-sent).
:::

### An LLM call

**Prompts and completions are not sent.** No message array, no system prompt, no
model output, no embedding vectors. LLM spans carry the accounting only.

| Attribute | When | Example |
|---|---|---|
| `gen_ai.system` | always | `"openai"`, `"anthropic"` |
| `gen_ai.usage.input_tokens` | always | `80` |
| `gen_ai.usage.output_tokens` | always | `45` |
| `gen_ai.request.model` | if a model resolved | `"gpt-4o-mini-2024-07-18"` |
| `gen_ai.operation.name` | always in practice | `"chat"`, `"embeddings"`, `"text_completion"` |
| `agentsight.llm.requested_model` | only if it differs from the resolved id | `"gpt-4o-mini"` |
| `agentsight.llm.model_declared` | only if `model_hint()` supplied the model | `true` |
| `agentsight.llm.streaming` | only when streamed | `true` |
| `agentsight.llm.usage_reported` | only when a stream closed without usage | `false` |
| `agentsight.llm.error` | only on failure | the provider's error message |
| `agentsight.llm.cache_read_tokens` | if non-zero | `40` |
| `agentsight.llm.cache_write_tokens` | if non-zero | `1200` |
| `agentsight.llm.reasoning_tokens` | if non-zero | `12` |
| `agentsight.llm.audio_input_tokens` | if non-zero | `220` |
| `agentsight.llm.audio_output_tokens` | if non-zero | `64` |
| `agentsight.llm.embedding_tokens` | if non-zero | `8` |

Token counts and the resolved model id are what your usage and cost figures are
computed from. There is no cost attribute — cost is derived from these, so a
rate that turns out to have been wrong can be restated rather than frozen into
whichever SDK version you pinned.

### A conversation

Everything you pass to `conversation()` is carried on every span in that
conversation, because a conversation outlives any one process and there is no
single span that owns it.

| Attribute | When | Example |
|---|---|---|
| `agentsight.conversation.id` | always | `"demo-plain"` — generated if you omit it |
| `agentsight.conversation.customer_id` | only if you pass it | `"user-12345"` |
| `agentsight.conversation.customer_ip` | only if you pass it, and only if it parses as an IP | `"203.0.113.7"` |
| `agentsight.conversation.device` | only if you pass it | `"desktop"` |
| `agentsight.conversation.language` | only if you pass it | `"en"` |
| `agentsight.conversation.name` | only if you pass it | `"Order questions"` |
| `agentsight.conversation.source` | only if you pass it | `"web"` |
| `agentsight.conversation.environment` | from the scope, `init()` or `AGENTSIGHT_ENVIRONMENT` | `"production"` |
| `agentsight.conversation.metadata` | only if you pass it | `{"topic": "delivery"}` as JSON |

Each of these is present only because your code supplied it. An integration that
passes nothing but a conversation id sends nothing but a conversation id.

### Buttons and attachments

| Attribute | When | Example |
|---|---|---|
| `agentsight.button.event` | on `button()` | `"feedback"` |
| `agentsight.button.label` | on `button()` | `"Was this helpful?"` |
| `agentsight.button.value` | on `button()` | `"yes"` |
| `agentsight.attachment.sender` | on an attachment call | `"end_user"` |
| `agentsight.attachment.count` | on an attachment call | `1` |
| `agentsight.attachment.files` | on an attachment call | `[{"name": "receipt.pdf", "size": 18422, "mime_type": "application/pdf"}]` |
| `agentsight.attachment.mode` | only via `upload_attachments()` | `"base64"` |
| `agentsight.metadata` | only if you pass `metadata=` to either call | `{"source": "widget"}` as JSON |

Attachment **spans** carry descriptors only — name, size, MIME type. The bytes
never travel in a span. `upload_attachments()` does send the file contents; see
[Sent outside spans](#sent-outside-spans).

### A failure

When instrumented work raises, OpenTelemetry's standard exception event is
recorded on the span:

```json
{
  "name": "exception",
  "timestamp": "2026-08-15T10:58:29.712Z",
  "attributes": {
    "exception.type": "RuntimeError",
    "exception.message": "the thing exploded",
    "exception.stacktrace": "Traceback (most recent call last):\n  File \"/srv/app/handlers.py\", line 89, in handle\n…",
    "exception.escaped": false
  }
}
```

:::warning Stack traces include your source
`exception.stacktrace` carries absolute file paths and code context from your
own service. Nothing in the dashboard displays it, but it is on the wire and it
is stored.
:::

A turn that did not finish is still sent, marked with why:

| Attribute | When | Example |
|---|---|---|
| `agentsight.turn.complete` | on every turn | `false` |
| `agentsight.turn.incomplete_reason` | only when incomplete | `"error"`, `"abandoned"`, `"deadline"`, `"shutdown"` |

### On every span

| Field | Example |
|---|---|
| `span_id`, `trace_id`, `parent_span_id` | `"585174cf073aeb9a"` |
| `started_at`, `ended_at`, `duration_ms` | `0.205` |
| `status` | `"ok"`, `"error"`, `"unset"` |
| `kind` | `"turn"`, `"tool"`, `"task"`, `"llm"`, `"button"`, `"attachment"`, `"conversation"` |
| `agentsight.span.kind`, `agentsight.entity.name` | `"tool"`, `"search_orders"` |
| `agentsight.turn.id` | links a span to the exchange it happened in |

Plus the OpenTelemetry envelope, under `otel`:

```json
{
  "span_kind": "INTERNAL",
  "trace_flags": 3,
  "trace_state": null,
  "is_remote": false,
  "status_description": null,
  "links": [],
  "dropped": { "attributes": 0, "events": 0, "links": 0 },
  "resource": {
    "telemetry.sdk.language": "python",
    "telemetry.sdk.name": "agentsight-python",
    "telemetry.sdk.version": "0.1.0",
    "service.name": "agentsight-python",
    "service.instance.id": "234a6d31-e775-477b-9395-b7110f04a304"
  },
  "scope": { "name": "agentsight", "version": "0.1.0", "schema_url": "" }
}
```

`service.name` is the SDK's own name, not your service's — the SDK does not read
or transmit your service identity. `service.instance.id` is a random UUID
generated per process, which is how one deployment's spans are told from
another's; it is not derived from your host, your network or your environment.

## What is never sent

- **LLM prompts, completions and embedding vectors.** Only token counts and
  model ids.
- **Attachment file contents in spans.** Descriptors only.
- **Your logs or your metrics.** OpenTelemetry has three signals and this SDK
  uses one: tracing. It installs no log handler and exports no metrics.
- **Anything ambient.** No environment variables, no process arguments, no
  request headers, no host or network detail. The SDK does not walk your objects
  looking for interesting fields.
- **Anything sampled away.** Every span is recorded. A sampled transcript would
  be a partial conversation, which is worse than none.

The SDK also keeps its OpenTelemetry pipeline to itself: it uses a private
tracer provider and never registers a global one, so it captures no spans from
any other instrumentation you have installed.

## Sent outside spans

Four requests do not carry spans, listed for completeness:

| What | When | What it carries |
|---|---|---|
| Key verification | once at `init()`, on a background thread | your API key only, no conversation data |
| Span batches | every 5 seconds by default | the payload above, gzipped above 8 KB where the server supports it |
| Conversation upsert | before an `upload_attachments()` batch | the conversation id and environment, so the files have a conversation to land on |
| Attachment upload | only on `upload_attachments()` | **the file contents**, base64-encoded, with their filenames and MIME types |

`record_attachments()` records that files were shared without sending them.
`upload_attachments()` sends them. They are separate calls so the choice is
explicit.

## Limits

| Limit | Value | Effect |
|---|---|---|
| Message content, tool responses, error strings | 16 384 characters | truncated, marked `...[truncated]` |
| Conversation string fields | 255 characters | clamped |
| Metadata JSON | 16 KB budget | oversized entries dropped largest-first; the payload always stays valid JSON |
| `customer_ip` | must parse as an IP | otherwise dropped entirely |

## Where it goes, and how long it is kept

Spans are stored whole. The dashboard renders a transcript from them, but the
spans themselves carry more than the transcript shows — timings, the tool and
LLM structure beneath each exchange, and the events belonging to turns that
never completed and so never reached a transcript at all.

**They are kept indefinitely.** There is no retention window today. A retention
window is under consideration; if one is adopted it will be stated here, and
before it applies.

Because it is stored, you can read it:

```python
from agentsight.api import AgentSight

ags = AgentSight()
for span in ags.spans.list(conversation_id="demo-plain", kind="tool"):
    print(span["name"], span["attributes"])

ags.spans.trace("8b1f0e1c9d5a4c2f9e3b7a6d4c8e2f10")   # one exchange as a tree
```

That is the same data this page describes, read back from where it landed —
which is the point: nothing is stored that you cannot retrieve.

## Controlling what is sent

These are the controls that exist today.

**Don't instrument the call.** The most direct one. An `agent.run()` that is not
inside a `turn()` produces no spans; a function without `@tool` produces no
arguments. You choose the granularity.

**Turn off a whole conversation.** Every span inside becomes a no-op — useful
for test traffic, replays and internal evaluation runs:

```python
with agentsight.conversation("qa-run-41", enabled=False):
    ...   # nothing is recorded, nothing is sent
```

**Turn off automatic LLM capture.** Provider and framework calls stop producing
spans; your explicit calls are unaffected:

```python
agentsight.init(auto_instrument=False)
agentsight.init(auto_instrument=["openai"])   # or narrow it to one
```

**Turn off the SDK.** Without a valid key, `init()` returns `False` and every
scope and decorator becomes a pass-through — your application behaves exactly as
if AgentSight were not installed.

:::info What is not available yet
There is no field-level redaction — no way to keep `agentsight.message.content`
or one argument of a `@tool` out of the payload while still recording the call.
This is a gap, not a design: if you need it, it is worth telling us, because
what gets built first follows what is asked for. Until then the controls above
are the granularity available, and the practical answer for a sensitive value is
to keep it out of the instrumented signature.
:::
