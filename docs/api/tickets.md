---
outline: deep
---

<CopyMarkdownButton />

# Tickets

`ags.tickets` is the agent's workflow surface: the bugs and tasks a team
tracks against an agent, optionally anchored to the conversation they are
about and to the feedback that prompted them. Tickets were dashboard-only
until the key plane opened here; a key now gets the whole lifecycle, which is
what lets an agent **file its own ticket** when a guardrail trips or a tool
keeps failing — a genuinely better story than escalating into a transcript
nobody reads.

```python
ags.tickets.create("Timeout in checkout", priority="high",
                   conversation="wa-3859")                     # write role
ags.tickets.add_comment(57, "Reproduced on the last three runs.")  # write role
```

Reads need a *read* key, writes a *write* key. Everything is scoped to the
one agent the key is bound to — another agent's ticket id answers `404`,
indistinguishable from an id that does not exist.

## Filed as the machine

A ticket or comment created here is **attributed to the key, not to a
person**: the author is the API key's *name* (the label you gave it at
creation; the agent's name if that is blank), and comments carry the role
`"agent"` alongside the human `"dev"` and `"reporter"` — there is
deliberately no `role` parameter, so machine entries can never pass as human
ones.

Every write notifies the whole team, the key's owner included. File tickets
deliberately, not on every failed turn.

::: warning Nothing here is idempotent
There is no dedupe key: a retried `create()` files a second ticket and a
retried `add_comment()` posts a second comment. Automation should guard its
own retries — list first, or track what it filed.
:::

## Filing and moving tickets

```python
ticket = ags.tickets.create(
    "Timeout in checkout",
    priority="high",              # low | medium | high
    tags=["checkout"],
    conversation="wa-3859",       # business id or pk — both work
    feedback_id=3,                # the feedback that prompted it
)
ags.tickets.update(ticket["id"], status="in_progress")
ags.tickets.update(ticket["id"], status="closed")
```

`title` is the one required argument. `status` starts at `open` and moves
through `backlog`, `open`, `in_progress`, `in_review`, `done`, `closed`.
`environment` (a slug — `ags.environments()` lists them) defaults to the
agent's production environment and is **write-once**: it records where the
problem was observed, and `update()` refuses it locally.

`conversation` takes the business `conversation_id` string or the integer pk
— strings cost one resolving request the first time, then the client's id
cache answers. A ticket created from conversation feedback inherits that
feedback's conversation unless you anchor one explicitly; product feedback
is rejected.

`delete()` exists, but takes the discussion thread with it — prefer
`update(id, status="closed")` for anything a human might still want to read.

## Reading them back

```python
for ticket in ags.tickets.list(status=["open", "in_progress"]):
    print(ticket["title"], ticket["comments_count"])

ags.tickets.get(57)                # one ticket, thread included
```

Filters: `status` (a list ORs), `priority`, `conversation` (pk),
`conversation_id` (business string), `has_conversation`, `has_feedback`,
`tags` (comma-separated, matches any), `created_at_after/_before`,
`updated_at_after/_before`, `search` (title), `ordering`. There is no
`environment` filter — the route does not select on it.

Every ticket payload embeds its full `comments` thread and the nested
`conversation`/`feedback` summaries; there is no summary depth on this
route. `ags.tickets.comments(57)` reads the same thread as its own paginated
list, for the rare thread too long to want inline.

## The thread

```python
ags.tickets.add_comment(57, "Reproduced on the last three runs.")
```

`body` is the whole contract — see [Filed as the machine](#filed-as-the-machine)
for what the server fills in around it.

## Next

- [Feedbacks](./feedbacks.md) — where tickets usually come from:
  `include_tickets=True` shows which feedback was promoted
- [Conversations](./conversations.md) — the same gate on the conversation
  list, and tickets on every detail payload
- [Errors and retries](./errors.md) — why a `create()` is never replayed
  automatically
