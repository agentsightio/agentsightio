---
outline: deep
---

<CopyMarkdownButton />

# Spans

Conversations, messages, action logs and usage rows are **projections**. This is
the archive they are projected from — the OpenTelemetry spans the SDK sent, as
stored. Read-only, and the place to look when a conversation renders in a way
you did not expect.

```python
for span in ags.spans.list(conversation_id="wa-3859", kind="tool"):
    print(span["name"], span["duration_ms"], span["attributes"])
```

What spans hold that the projections deliberately drop: exact parent and child
structure, per-call durations and status, tool arguments and responses,
OpenTelemetry resource and scope attributes, and any attribute a newer SDK emits
that has no projection rule yet.

Spans were previously write-only — sent on every export, stored, and readable by
nobody. [What the SDK sends](/getting-started/what-the-sdk-sends) documents every
attribute that reaches them; this page is how you read them back.

## Three shapes, cheapest first

| Call | Returns |
|---|---|
| `list()` | spans matching filters, newest first |
| `get(id)` | one span, optionally with its verbatim payload |
| `trace(trace_id)` | one whole trace, nested by parent |

## Filtering

```python
ags.spans.list(kind="tool", status="error")
ags.spans.list(trace_id="617823595d579cb3…")
ags.spans.list(conversation_id="wa-3859", started_at_after=datetime(2026, 8, 1))
```

| Filter | Selects on |
|---|---|
| `kind` | `turn`, `llm`, `tool`, `task`, `button`, `attachment`, `conversation` |
| `status` | `ok`, `error`, `unset` |
| `name` | the span's name, exactly |
| `conversation` (pk), `conversation_id` (string) | one conversation |
| `trace_id` | one trace, flat |
| `span_id`, `parent_span_id` | one span, or one span's children |
| `environment` | the environment slug — not `env`, as on usage |
| `started_at_after`, `started_at_before` | when it ran |
| `ordering` | the sort |

The set is small on purpose. It is built around the indexes the archive
actually has, so every filter offered is one the store can serve: there is no
substring search on `name` and no filtering inside `attributes`. Over an archive
of every span an agent ever sent, those are the queries that would need to be
built for before they were worth offering.

`kind` is whatever the emitting SDK called it, and is deliberately not validated
here — a newer release may send a kind this one has never heard of, and it is
stored rather than rejected.

## What a row looks like

```json
{
  "id": 10452,
  "conversation": 737,
  "conversation_id": "wa-3859",
  "trace_id": "d332aa0112fbf31cae3dd38030161235",
  "span_id": "29d5361e042cbeb2",
  "parent_span_id": null,
  "kind": "turn",
  "name": "turn",
  "started_at": "2026-08-17T13:32:32.985597Z",
  "ended_at": "2026-08-17T13:32:32.985729Z",
  "duration_ms": 0.132,
  "status": "ok",
  "attributes": { "agentsight.conversation.id": "wa-3859", "…": "…" },
  "events": [ { "name": "agentsight.message", "attributes": { "…": "…" } } ]
}
```

`attributes` and `events` are the substance — the tool arguments and responses,
the message content, the token counts. They are on every row.

:::warning Rows never carry `payload`, at any page size
`payload` is the verbatim OpenTelemetry span and the largest field on the row.
It repeats `attributes` and `events` inside itself and is about half a stored
span's bytes, so a list of them is exactly the mistake the conversation list had
to correct. It is available one span at a time, and only when you ask.
:::

## One span, with everything

```python
span = ags.spans.get(10452, payload=True)
span["payload"]
```

`payload=True` adds the raw envelope: resource attributes, instrumentation
scope, links, trace flags and state, the status description, dropped-record
counts, and any field a future SDK adds. Nothing was discarded on the way in, so
this is the whole thing as it arrived.

`get()` takes the **`id` from a list row, not the `span_id`** — that one is the
OpenTelemetry identifier and is only unique within a conversation. Passing
anything but an integer is refused before the request is made.

## One turn, as a tree

`list(trace_id=...)` gives you a trace flat. `trace()` gives you the same spans
arranged the way they happened:

```python
trace = ags.spans.trace("617823595d579cb34b3988c807b0cbe6")

for root in trace["roots"]:
    print(root["kind"], root["name"], root["duration_ms"])
    for child in root["children"]:
        print("  ", child["kind"], child["name"], child["duration_ms"])
```

```
turn retry 102.219
   tool check_open_tickets 100.31
   llm gpt-4o-mini 1.587
```

That is the shape to reach for when the question is "what happened inside this
turn", rather than "find me the spans that look like X" — and the answer above
took two lines to find: the tool call is where the hundred milliseconds went,
not the model.

The response is `{trace_id, span_count, truncated, roots}`. Each node is a span
row plus a `children` list, nested to whatever depth your agent produced, and
never carrying `payload` — read that one span at a time.

A span whose parent is not in the trace appears as a root rather than being
dropped, so `span_count` always equals the number of nodes in the tree.

:::info `truncated` means spans are missing, not that the trace ended
It is `True` when the trace was larger than one response assembles and the tail
was cut. The trace did not stop there. Reach for `list(trace_id=...)` and page
through it if you need all of them.
:::

`trace()` is not paginated, so there is no iterator here either.

## What this is good for

**Button clicks**, which have no namespace of their own because nothing projects
them into a readable table yet — but the spans are complete:

```python
for span in ags.spans.list(kind="button"):
    print(span["attributes"]["agentsight.button.label"],
          span["attributes"]["agentsight.button.value"])
```

**Turns that never finished**, which never reach a transcript by design, and are
recorded anyway — `agentsight.turn.complete` is the marker, and
`agentsight.turn.incomplete_reason` says whether it was an error, an
abandonment, a deadline or a shutdown:

```python
for span in ags.spans.list(kind="turn", status="error"):
    print(span["attributes"].get("agentsight.turn.incomplete_reason"))
```

**A tool call whose output looks wrong**, with the arguments it actually
received and the response it actually returned, rather than the summary of them:

```python
span = ags.spans.list(kind="tool", name="search_orders").first()
span["attributes"]["agentsight.tool.arguments"]
span["attributes"]["agentsight.tool.response"]
```

## Next

- [What the SDK sends](/getting-started/what-the-sdk-sends) — every attribute
  these carry, and what is never sent
- [Actions](./actions.md) — the same invocations as definitions and logs
- [Usage](./usage.md) — the LLM spans, aggregated and priced
- [Conversations](./conversations.md) — the projection most questions start from
