---
outline: deep
---

<CopyMarkdownButton />

# Conversations

`ags.conversations` is **everything you can do to a conversation that has
already been recorded** — find it, read its transcript, correct how it is
labelled, hide it. What it cannot do is create one: live conversations come
into being through `agentsight.conversation(...)` on the tracking side, and
there is no second way in for live traffic. Historical conversations from a
system you used before AgentSight are the one exception, and they arrive by a
different route entirely — a one-off file upload in the dashboard, described
in [Importing existing history](/getting-started/importing-history).

```python
for conversation in ags.conversations.list(has_feedback=True):
    print(conversation["conversation_id"], conversation["message_count"])

conversation = ags.conversations.get("wa-3859")
for message in conversation["messages"]:
    print(message["sender"], message["content"])
```

Every method here accepts either id — the business `conversation_id` your
application knows, or the integer primary key. See
[Naming a conversation](./index.md#naming-a-conversation).

## Listing

`list()` returns a [lazy iterator](./pagination.md) of conversations **without
their transcripts**:

```python
ags.conversations.list(environment="production", is_marked=True)
```

That is a deliberate difference from the raw API, which sends an API key the
whole transcript of every row it returns — messages, attachments, action logs
and feedback included. Over a busy agent that is hundreds of megabytes to
answer "which conversations were marked", so this client asks for the lean
shape and offers the other one by name:

```python
for conversation in ags.conversations.list_full(started_at_after="2026-08-01"):
    render(conversation["messages"])
```

`list_full()` is the only way to read messages in bulk — there is no message
list of its own on this API. Reach for it when you are exporting or rendering
transcripts, and for nothing else.

Soft-deleted conversations are excluded from both unless you ask for them:

```python
ags.conversations.list(include_deleted=True)
```

## The filters

Booleans and datetimes are converted for you — pass `True`, or a `datetime`,
and the right thing goes on the wire. A filter this list does not name is
[refused locally](./errors.md), because a filter the server ignores returns
more rows than you asked for.

| Filter | Selects on |
|---|---|
| `conversation_id` | the exact business id |
| `customer_id`, `customer_id__icontains` | who the conversation was with |
| `customer_ip_address` | the recorded IP, exactly |
| `environment` (or `env`) | `production` or `development` (`prod`/`dev` accepted) |
| `device`, `language`, `name` | what was recorded about the conversation |
| `is_marked` | flagged conversations |
| `include_deleted` | include the soft-deleted ones |
| `include_tickets` | conversations that have a ticket — and each row then carries its tickets in full. [Read the warning below](#tickets-include-tickets-narrows-as-it-includes) |
| `has_messages`, `has_action`, `has_feedback` | conversations where something happened |
| `action_name` | conversations in which a matching tool or task ran — case-insensitive, on part of the name |
| `message_contains` | text inside the transcript |
| `feedback_sentiment` | `positive`, `neutral` or `negative` |
| `metadata_key`, `metadata_value`, `metadata` | your own metadata — see below |
| `started_at_after`, `started_at_before` | when it began |
| `search` | across the searchable fields at once |
| `ordering` | the sort, `-started_at` style |

Combining them narrows, as you would expect:

```python
unhappy = ags.conversations.list(
    environment="production",
    feedback_sentiment="negative",
    started_at_after=datetime(2026, 8, 1),
    ordering="-started_at",
)
```

On [usage](./usage.md) and [spans](./spans.md), `environment` additionally
accepts any slug the agent owns.

Metadata filtering has a wire format of its own. `metadata` takes `key:value`
pairs — comma-separated to require several at once, dot paths for nested keys —
and `metadata_key` only filters together with a companion `metadata_value`:

```python
ags.conversations.list(metadata="plan:pro,analysis.room_name:kitchen")
ags.conversations.list(metadata_key="plan", metadata_value="pro")
```

### Tickets: `include_tickets` narrows as it includes

```python
for conversation in ags.conversations.list(include_tickets=True):
    for ticket in conversation["tickets"]:
        print(ticket["status"], ticket["title"], len(ticket["comments"]))
```

Each returned row carries its `tickets` — id, title, status, priority, tags,
timestamps and the full discussion thread under `comments`, oldest message
first.

:::warning It also narrows the result set
`include_tickets=True` does two things at once: it puts the tickets on each
row, **and it drops every conversation that has no ticket** — an agent with a
thousand conversations and three ticketed ones returns three rows, with no
error. It is the one thing about this filter that is easy to get wrong: do not
add it "just to see tickets" on a listing you expect to stay complete. The
page's `count` is the ticketed count. Composes with `list_full()`.
:::

## One conversation, whole

```python
conversation = ags.conversations.get("wa-3859")
```

`get()` returns the record **with** its messages, attachments, action logs and
feedback — asking for one conversation by id is the case where you almost
certainly want all of it.

`full=False` is accepted and sent, but the endpoint underneath answers a detail
request the same way either way, so expect the whole conversation regardless.
The `full` distinction is a property of [listing](#listing), where it is the
difference between a lean row and a transcript.

Messages arrive in order, each carrying its sender, content, timestamp, any
metadata you recorded, and the action logs, attachments or button click that
belong to it.

Two more keys arrive on detail with no parameter needed — asking for one
conversation by id is itself the explicit act:

- **`tickets`** — every ticket filed against the conversation, discussion
  thread included, exactly the shape `include_tickets` puts on list rows.
- **`token_usage`** — what the conversation cost, or `null` when nothing was
  recorded:

```json
{
  "totals": {"prompt_tokens": 8210, "completion_tokens": 1650, "total_tokens": 9860},
  "cost_usd": "0.05242500",
  "cost_sources": ["backend"],
  "models": [
    {"model": "claude-sonnet-4-5", "cost_source": "backend",
     "cost_usd": "0.05242500", "prompt_tokens": 8210,
     "completion_tokens": 1650, "total_tokens": 9860}
  ]
}
```

`totals` names only the token columns that are non-zero for this conversation
(`total_tokens` always), and `models` breaks the same columns down per model —
tokens from different models are not the same unit. Costs are decimal
**strings**. `cost_source` is carried through rather than blended: a model
with no price row on file books `unpriced`, and its zero means "we could not
price this", never "this was free" — one entry per model *and* pricing source,
so a partially repriced model shows both.

## Attachments

```python
files = ags.conversations.attachments("wa-3859")
```

Every attachment on the conversation, with download URLs. The response is an
envelope, not a bare list: `conversation` (the numeric id), `conversation_id`,
`attachment_count`, and the rows under `attachments`.

:::warning Download URLs expire after an hour
The URLs are signed and short-lived, so fetch a file when you need it rather
than storing the link. A URL you saved yesterday will not work today — ask
again, it costs one request.
:::

## What metadata has been recorded

Three calls answer "what keys are even in use here", which is what you need
before you can filter on metadata sensibly:

```python
ags.conversations.metadata_keys()
# {'keys': ['order_id', 'plan', 'region', 'channel']}

ags.conversations.metadata_values("plan")
# {'key': 'plan', 'values': ['enterprise', 'pro']}

ags.conversations.message_metadata_keys()
# {'keys': ['locale', 'latency_ms']}
```

They are a discovery aid, not analytics: the server reads a recent sample of
conversations rather than the full history, so a key last used months ago can
be missing from the list. For building a filter UI over data you did not write
yourself, that is almost always enough.

## Renaming and marking

```python
ags.conversations.rename("wa-3859", "Refund — resolved")   # write role
ags.conversations.mark("wa-3859")                          # write role
ags.conversations.mark("wa-3859", False)
```

A name is a display label, capped at 255 characters and stripped of surrounding
whitespace. Marking is the flag the dashboard filters on; `mark()` sets it,
`mark(..., False)` clears it.

## Changing several fields at once

```python
ags.conversations.update(                                  # write role
    "wa-3859",
    customer_id="user-456",
    language="en",
    device="mobile",
)
```

`update()` accepts `name`, `is_marked`, `customer_id`, `device`, `language` and
`metadata`. The identity fields are immutable server-side — a conversation's id,
its start time and the agent it belongs to are what make it that conversation.

`metadata` here **replaces the whole document**, because that is all the
underlying change can do. To merge instead, use the next call.

:::info A conversation still open in this process updates itself twice
Every field above except `is_marked` is also stamped on every span the
conversation produces, so if the conversation is still open *here* — inside a
live `agentsight.conversation(...)` scope — the new value is pushed into that
scope as well. Without it the next span would carry the old value and write it
straight back over what you just changed.

That echo can only reach a scope in this process, and it needs the business
`conversation_id` to know which scope to look for. Passing an integer primary
key for a conversation that is open here and was never listed or resolved by
string still writes the row — it just skips the echo. Prefer the string id,
which is what you passed to `agentsight.conversation()` in the first place.
:::

## Changing metadata without replacing it

```python
ags.conversations.update_metadata("wa-3859", {"plan": "enterprise"})
ags.conversations.update_metadata("wa-3859", remove=["trial_ends"])
```

Four rules, and they are the same four the tracking-side call follows:

- **It merges, it does not replace.** Keys you do not name survive.
- **The merge is shallow.** A nested dictionary is replaced whole rather than
  merged key by key.
- **No value is filtered.** `None`, `False`, `0` and `""` are stored exactly as
  given.
- **`remove=` is the only way to delete a key**, and naming one that is not
  there does nothing.

:::warning Two round trips, and not atomic
There is no conditional write underneath this, so it reads what is stored,
merges, and writes the result back. Two callers merging into the same
conversation at the same moment can lose one of the two updates.

While a conversation is still open in your process,
[`agentsight.update_metadata()`](/tracking/conversations#changing-metadata-afterwards)
is the better call — it needs no fetch and cannot race. This one is for
conversations that have already ended.
:::

Like everything else here it blocks, which does not mean it has to sit on your
event loop:

```python
background_tasks.add_task(ags.conversations.update_metadata, "wa-3859", data)
await asyncio.to_thread(ags.conversations.update_metadata, "wa-3859", data)
```

## Deleting is soft, and there is no other kind

```python
ags.conversations.delete("wa-3859")                        # write role
```

The row survives, flagged as deleted and hidden from listings. It is reversible,
and it is readable again the moment you ask for it:

```python
ags.conversations.list(include_deleted=True)
ags.conversations.get("wa-3859")     # still answers
```

**Nothing on this API destroys a conversation.** That is a decision, not a
missing feature: users delete a conversation to stop seeing it, not to destroy
it, and a destructive call reachable by an integration is a hazard no
convenience justifies — a hard delete would take the messages, attachments,
action logs, spans and token usage with it, unrecoverably. Permanent removal is
an operator action against the database. If you need one, ask.

:::info `purge()` is gone
Earlier versions of this client had a `purge()` that really did destroy the row.
It no longer exists, and the route it called now performs the same soft delete —
so code calling it by hand hides a conversation rather than destroying one.
:::

## Next

- [Feedbacks](./feedbacks.md) — what `has_feedback` and `feedback_sentiment` are
  filtering on
- [Usage](./usage.md) — what a conversation cost, by conversation
- [Spans](./spans.md) — what happened inside a turn, when the transcript is not
  enough
- [Tracking conversations](/tracking/conversations) — the other side: how these
  rows come into being
