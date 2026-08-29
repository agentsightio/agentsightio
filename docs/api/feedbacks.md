---
outline: deep
---

<CopyMarkdownButton />

# Feedbacks

`ags.feedbacks` is **the one place this client records something that
happened**, and the exception proves the rule everywhere else. Conversations,
messages, action logs, buttons, attachments and spans are written by the
tracking SDK because they are things that happened and the SDK watched them
happen. Feedback is not telemetry.
Nothing about a run of your agent reveals whether the person on the other end
was satisfied with it — somebody has to say so, and the moment they say it is a
click in your application, not an event any SDK could observe.

So there is no tracking-plane path for feedback, no span kind, and no
inference. You call this when your user clicks the thumb.

```python
ags.feedbacks.create_for_conversation("wa-3859", "positive")     # write role
ags.feedbacks.create_for_agent("negative", "Slow at peak hours")  # write role
```

## Two kinds, two methods

**Conversation feedback** is how one specific conversation went. **Agent
feedback** is how the agent is doing overall, optionally scoped to one
environment. They are separate methods rather than one method with a flag
because they genuinely take different arguments — `environment` is accepted on
agent feedback and refused on conversation feedback.

```python
ags.feedbacks.create_for_conversation("wa-3859", "negative", "Never got my refund")
ags.feedbacks.create_for_agent("positive", environment="production")
```

| Parameter | Type | Default |
|---|---|---|
| `conversation` | `str` or `int` | required, on conversation feedback |
| `sentiment` | `str` | required |
| `comment` | `str` | — |
| `agent` | `int` | your key's own agent |
| `environment` | `str` | — |

`sentiment` is `positive`, `neutral` or `negative`. Anything else is rejected
before the request is made, with a message naming the three.

`conversation` takes either id and costs no extra round trip either way — this
is the one method where the string is resolved server-side rather than by the
client.

`agent` on `create_for_agent()` fills itself in from
[`me()`](./index.md#who-this-key-is), so
`ags.feedbacks.create_for_agent("positive")` is the whole call. A key can only
ever write to one agent, which made naming it redundant. Pass it explicitly only
if you already have the number in hand.

`environment` is a slug — `ags.environments()` lists the ones this agent has.

## Reading it back

```python
for feedback in ags.feedbacks.list(sentiment="negative"):
    print(feedback["conversation_id"], feedback["comment"])

ags.feedbacks.get(42)
```

Newest first. `page()` gives you the envelope instead of the iterator, which is
how you read a count without walking the rows:

```python
ags.feedbacks.page().count
```

`page()` also takes a page number and the same filters as `list()` —
`ags.feedbacks.page(2, sentiment="negative")`.

| Filter | Selects on |
|---|---|
| `sentiment` | `positive`, `neutral` or `negative` |
| `kind` | conversation feedback or agent feedback |
| `conversation` (pk), `conversation_id` (string) | one conversation's feedback |
| `agent`, `user` | who it is about, and who left it — `agent` only accepts your key's own agent id, so it never narrows |
| `environment` (or `env`) | the environment it was left in |
| `has_comment`, `comment_contains` | the free text |
| `created_at_after`, `created_at_before` | when it was left |
| `include_tickets` | the gate to the ticket surface — see below |
| `has_ticket`, `ticket_status` | the promoted state — only alongside `include_tickets=True` |
| `search`, `ordering` | across the searchable fields, and the sort |

To go the other way — conversations that have feedback, rather than the
feedback itself — filter [conversations](./conversations.md#the-filters) on
`has_feedback` or `feedback_sentiment`.

### Tickets: `include_tickets` narrows as it includes

A ticket is typically a promoted piece of feedback, and `include_tickets=True`
is how you read that promotion back:

```python
for feedback in ags.feedbacks.list(include_tickets=True):
    ticket = feedback["ticket"]
    print(ticket["status"], ticket["title"], ticket["comments_count"])
```

Each returned row carries its `ticket` — id, title, status, priority, tags,
timestamps, `comments_count` and the full discussion thread under `comments`,
oldest message first — or you can narrow further with `has_ticket` and
`ticket_status` (which accepts a list and ORs it:
`ticket_status=["open", "in_progress"]`).

:::warning It also narrows the result set
`include_tickets=True` does two things at once: it puts the ticket on each
row, **and it drops every feedback that was never promoted** — with no error.
Do not add it "just to see tickets" on a listing you expect to stay complete;
the page's `count` is the promoted count. Without it, payloads carry no
`ticket` key, `counts` collapses to `{"all": N}`, and `has_ticket` /
`ticket_status` answer 400 — same contract as
[conversations](./conversations.md#tickets-include_tickets-narrows-as-it-includes).
:::

`get()` needs no parameter: one feedback by id carries its `ticket`
unconditionally, at the same full depth, or `null` when it was never promoted.

## Correcting and removing

```python
ags.feedbacks.update(42, sentiment="neutral")             # write role
ags.feedbacks.update(42, comment="Resolved on the second attempt")
ags.feedbacks.delete(42)                                  # write role
```

`sentiment` and `comment` are the two changeable fields. Unlike a conversation,
a feedback row deletes for real — it is a statement somebody made, and
withdrawing it means it is gone rather than hidden.

## Next

- [Conversations](./conversations.md) — filtering conversations by the feedback
  on them
- [Metrics](/getting-started/metrics) — how feedback reads on the dashboard
- [The API client](./index.md) — where the `write` role is reported
