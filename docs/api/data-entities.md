---
outline: deep
---

<CopyMarkdownButton />

# Data entities

`ags.data_entities` manages the clients one agent serves: one hotel-booking agent,
many hotels. [The guide](/getting-started/data-entities) explains the idea and how
keys behave.

You do not need this namespace to start. Tracking creates an entity the first time
it sees a key:

```python
with agentsight.conversation("wa-3859", data_entity="hotel-paris"):
    ...
```

This namespace is for giving one a readable name, declaring one ahead of its
traffic, and deleting or restoring one.

```python
for entity in ags.data_entities.list():
    print(entity["key"], entity["name"], entity["conversation_count"])

ags.data_entities.update(12, name="Hotel Paris")            # write role
```

It needs `agentsight >= 0.2.0` and a backend that supports data entities. On one
that does not, every call raises [`NotFoundError`](./errors.md), and the
[entity filters](#filtering-by-entity) are refused.

## Naming an entity

These methods take the integer `id` from a row. A key is refused rather than looked
up, because finding one means walking the list, and that cost should be visible
where you pay it:

```python
entity = next(
    row for row in ags.data_entities.list() if row["key"].lower() == "hotel-paris"
)
ags.data_entities.update(entity["id"], name="Hotel Paris")
```

The match is lowercased because keys match case-insensitively and the row holds the
first spelling seen.

`lower()` gives the server's answer for ASCII keys. For other letters the server
matches by its own case rules, which can treat as one key a pair that `lower()`
keeps apart, such as `İstanbul` and `istanbul`. If your keys are not ASCII, compare
against the spelling the row holds.

## Listing

```python
ags.data_entities.list()                      # active entities
ags.data_entities.list(include_deleted=True)  # deleted ones too
```

*Read role.* Lazy and paged like [every list](./pagination.md). An agent holds at
most 500 active entities, so walking it is cheap.

| Field | What it is |
|---|---|
| `id` | what this namespace takes |
| `key` | what tracking sends as `data_entity` and what the filters take; permanent |
| `name` | the display name, which starts out equal to the key |
| `description` | free text |
| `metadata` | your own JSON, or `null` |
| `origin` | how the row began: `sdk`, `dashboard`, `api` or `import` |
| `first_seen_at`, `last_seen_at` | when it first appeared, and when a conversation last landed under it |
| `is_deleted`, `deleted_at` | the soft delete |
| `conversation_count` | conversations under it |
| `receiving_traffic` | `true` on a deleted row that conversations are still landing on |
| `embed_token_count` | active embed tokens pinned to it, which stop working if it is deleted |
| `member_count`, `rule_count`, `invitation_count` | dashboard access: team members, email-domain rules and pending invitations restricted to it |

## Reading one

```python
ags.data_entities.get(12)
```

*Read role.* A deleted entity can still be read by id, which is what makes restoring
it possible.

## Declaring one ahead of its traffic

```python
ags.data_entities.create(                                  # write role
    "hotel-paris",
    name="Hotel Paris",
    description="City-centre flagship.",
    metadata={"rooms": 220},
)
```

Only the key is required. It is trimmed, and an empty or over-255-character key is
refused rather than changed, because the key is permanent and this is the moment you
choose it. This differs from tracking, which clamps a long key so that a batch is
not lost over it.

The server answers `400`, raised as `ValidationError`, in two cases:

- the key already exists, in any casing, **including on a deleted entity**, because a
  key stays reserved so its history has one row;
- the agent already has 500 active entities.

A key containing a NUL or an unpaired surrogate is refused as well, because no key
can hold one. The client raises that `ValidationError` itself and sends nothing.
Over raw REST it is a `400`.

## Changing its label

```python
ags.data_entities.update(12, name="Hotel Paris (Opéra)")   # write role
ags.data_entities.update(12, description="Refurbished.")
ags.data_entities.update(12, metadata={"rooms": 240})
```

`name`, `description` and `metadata`, and nothing else. An empty `name` goes back to
the key. `metadata` is replaced whole, and `None` clears it.

The key cannot be updated, and asking raises `ValidationError` before any request is
sent.

## Deleting and restoring

```python
ags.data_entities.delete(12)    # write role, safe to repeat
ags.data_entities.restore(12)   # write role, returns the row
```

Delete is soft. Conversations keep the entity and the key stays reserved. Traffic
that still sends the key keeps landing on the hidden row, which then reports
`receiving_traffic`. Embed tokens pinned to it stop working until it is restored.

Restoring takes a slot back, so it raises `ValidationError` when the agent already
has 500 active entities.

## The cap

```python
ags.me(refresh=True)["data_entities"]
# {'limit': 500, 'active_count': 3, 'overflow_count': 0, 'overflow_at': None}
```

`overflow_count` is how many conversations were created Unassigned because their
key arrived at the cap, and `overflow_at` is when that last happened. Each
conversation counts once, however many requests carried the key. A conversation
that began without a key and was sent an unknown one later, at the cap, is not
counted. `me()` is cached, and these counters move, so pass `refresh=True` for a
current reading.

## Filtering by entity

Conversations, feedback, tickets and usage take the same two filters:

```python
ags.conversations.list(data_entity="hotel-paris")      # one key, any casing
ags.feedbacks.list(data_entity_unassigned=True)        # no entity
ags.tickets.list(data_entity_unassigned=False)         # any entity
ags.usage.summary(data_entity="hotel-paris")           # what one client cost
```

A blank `data_entity` raises `ValidationError` instead of being sent, because the
server reads a blank key as no filter, and an empty variable would return every
client's rows. A `data_entity` containing a NUL or an unpaired surrogate is refused
the same way, because no key can hold one. `None` means not filtered, as it does
for every filter on this client.

Feedback and tickets follow their conversation, so agent-level feedback and tickets
without a conversation appear under neither filter.

Conversation, usage and feedback rows carry the key as `data_entity`, and so does a
ticket's nested `conversation`. It is `None` for Unassigned and for a row with no
conversation.

On a backend that does not support data entities, either filter raises
`ValidationError` as soon as the list is read, and the list itself is never
requested: that backend would ignore the filter and return every row. Each refusal
costs one `GET /api/me/`. A cached "no" is read again before it is trusted, so a
client that outlives a backend upgrade starts filtering.

:::danger A filter is not a tenant boundary
An API key sees its whole agent, so a filter only narrows what your own code
reads. The server enforces two boundaries: a
[scoped embed token](/getting-started/data-entities#a-dashboard-for-one-client),
and a dashboard login for the client's own staff as
[Viewers restricted to their entities](/getting-started/data-entities#a-dashboard-for-one-client).
To show a client only its own data, use one of those.
:::

## Conversations are not moved here

A conversation's entity is set once, by the first key that reaches it, and
`ags.conversations.update()` refuses the field. A conversation reads back with its
`data_entity` key, or `None` for Unassigned.

## Next

- [Data entities](/getting-started/data-entities) — keys, the cap, and what happens
  to each conversation
- [Conversations](./conversations.md) — the filters in context
- [Pagination](./pagination.md) — reading a count without walking anything
