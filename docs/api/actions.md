---
outline: deep
---

<CopyMarkdownButton />

# Actions

An action is a **definition, not an event** — `search_orders` the capability,
rather than the eleven times it ran this morning. `ags.actions` reads those
definitions, reads their invocations, and sets the two fields that decide how
each one reads on the dashboard.

```python
for action in ags.actions.list():
    print(action["name"], "→", action["display_name"])
```

## Where actions come from

**The tracking SDK is the only thing that creates one.** The first `@tool` or
`@task` span carrying a name brings that action into being; every later one
finds it already there.

So there is deliberately no `create()` here, and no `delete()`. An action exists
because your agent performed it, and a second way to conjure or destroy that row
would mean two sets of semantics for the same table — while a `delete()` would
take every invocation hanging off the definition with it.

## What this namespace is for

`display_name` and `description` decide how an action reads in the dashboard,
and **a span carries neither**. There is nowhere else to set them:

```python
ags.actions.update(                                        # write role
    7,
    display_name="Search orders",
    description="Looks up a customer's recent orders by id.",
)
```

`name` is changeable too, and rarely should be — it is the name the backend
matches on, so renaming it means the next span carrying the old name creates a second
action beside this one. Change the display name instead; that is what it is for.

The action has to exist before you can label it, which means your agent has to
have performed it at least once. There is no way to pre-register a tool you have
not shipped yet.

## Reading them

```python
ags.actions.list(name__icontains="order")
ags.actions.get(7)
```

| Filter | Selects on |
|---|---|
| `name` | the exact name spans are matched on |
| `name__icontains` | part of that name |
| `display_name` | the dashboard label |
| `search` | across name, display name and description at once |
| `ordering` | the sort |

There is no `agent` filter here: a key is bound to one agent and the scoping is
applied before any filter runs, so the parameter could only ever be a no-op or
a contradiction.

## Invocations

```python
for log in ags.actions.logs(7):
    print(log["started_at"], log["duration_ms"], log["error_message"])
```

Each log is one recorded run — when it started and ended, how long it took,
what it returned, and the error message if it failed. These come from the
tracking plane as well, and this call reads them back.

It returns **a plain list, not an iterator**: this one is not paginated, so
there is no `.page()` and nothing to walk.

:::info Durations here are measured, not declared
An action's `duration_ms` is the real elapsed time of the decorated call. If
you are comparing against figures from an older SDK, expect a step change —
those were whatever the caller typed in.
:::

## Next

- [Tools & Actions](/tracking/tools-and-actions) — `@tool` and `@task`, and how
  the name gets chosen
- [Spans](./spans.md) — the same invocations with their arguments, responses and
  place in the trace
- [Conversations](./conversations.md) — filtering conversations by `action_name`
