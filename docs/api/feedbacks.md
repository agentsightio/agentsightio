---
outline: deep
---

<CopyMarkdownButton />

# Feedbacks

`ags.feedbacks` is **the one place this client creates rows**, and the exception
proves the rule everywhere else. Conversations, messages, action logs, buttons,
attachments and spans are written by the tracking SDK because they are things
that happened and the SDK watched them happen. Feedback is not telemetry.
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
| `search`, `ordering` | across the searchable fields, and the sort |

To go the other way — conversations that have feedback, rather than the
feedback itself — filter [conversations](./conversations.md#the-filters) on
`has_feedback` or `feedback_sentiment`.

:::info No ticket filters, and no ticket object
Tickets are internal workflow state and are not on the API-key surface at all.
Feedback payloads here carry no nested ticket, `has_ticket` and `ticket_status`
are refused with an error naming the filters that do work, and the aggregate
`counts` collapses to `{"all": N}`. That is a boundary drawn on purpose, not a
field that has yet to be added.
:::

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
