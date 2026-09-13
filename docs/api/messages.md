---
outline: deep
---

<CopyMarkdownButton />

# Messages

`ags.messages` is **one message at a time, by pk** — read it, and edit the
metadata document your application attached to it. It does not create
messages and it does not touch the transcript: content, sender and timestamp
are what the tracking SDK observed, and they stay that way.

```python
message = ags.messages.get(4821)
ags.messages.update_metadata(4821, {"visualization": record})   # write role
```

## Why this exists

Message metadata is written when the turn is recorded —
`agentsight.agent_message(content, metadata={...})` — and it is the document
the dashboard's **message templates** render inside the bubble. Some of what
your application knows about a message only exists *after* the turn: a
picture generated for it in the background, a verdict from a later check, a
score. That belongs on the message it is about, next to what the turn wrote,
and nothing on the tracking side can put it there once the turn is over. This
namespace can.

## Naming a message

Messages have no business id of their own — the tracking SDK never asked you
for one — so the only handle is the integer pk the API returns:

```python
conversation = ags.conversations.get("wa-3859")
pk = conversation["messages"][-1]["id"]
```

A string is refused rather than looked up, because there is nothing to look
it up by. (`ags.conversations.get()` accepts either id; this namespace accepts
the pk only.)

There is no `list()`: messages come nested in their conversation, and the
API has no message list of its own. Read transcripts with
[`conversations.get()`](./conversations.md#one-conversation-whole) or
[`conversations.list_full()`](./conversations.md#listing).

## Reading one

```python
ags.messages.get(4821)
```

Content, sender, timestamp, metadata, attachments (with signed URLs that
expire after one hour), action logs and the message's vote. *Read role.*

## Changing metadata without replacing it

```python
ags.messages.update_metadata(4821, {"visualization": record})
ags.messages.update_metadata(4821, remove=["draft"])
```

Reads the stored document, merges, writes the result back. Exactly the rules
of the [conversation twin](./conversations.md#changing-metadata-without-replacing-it):
the merge is **shallow** — a nested dict is replaced whole — and **no value is
filtered**: `None`, `False`, `0` and `""` are stored as given. `remove` is the
only thing that deletes a key, and naming a key that is not there is a no-op.

Two round trips, and not atomic. A message is normally written once, by the
turn that recorded it, and enriched afterwards by one job, so the window
matters less than it does for conversations — but two jobs merging into the
same message at the same moment can still lose one of the two updates.

Blocking, like the rest of this client. Off an event loop:

```python
await asyncio.to_thread(ags.messages.update_metadata, 4821, data)
```

## Replacing it outright

```python
ags.messages.update(4821, metadata={"visualization": record})
```

The whole document, and keys you do not send are gone. Metadata is the only
field `update()` takes — the endpoint would accept more, but a client that
could rewrite the transcript would have two sets of semantics for what a
message is.

## Next

- [Conversations](./conversations.md) — where the transcript, and the pk,
  come from.
- [Feedbacks](./feedbacks.md) — the other thing recorded against a message
  pk.
