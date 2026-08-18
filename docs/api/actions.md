---
outline: deep
---

<CopyMarkdownButton />

# Actions

An action is a **definition, not an event** — `search_orders` the capability,
rather than the eleven times it ran this morning. `ags.actions` reads those
definitions, reads their invocations, declares new ones, and sets the two fields
that decide how each one reads on the dashboard.

```python
for action in ags.actions.list():
    print(action["name"], "→", action["display_name"])
```

## Where actions come from

**Tracking makes them as it goes.** The first `@tool` or `@task` span carrying a
name brings that action into being; every later one finds it already there. Most
of your actions will arrive this way and you never have to think about it.

**Or you declare one ahead of time**, so a capability shows up in the dashboard
before — or without — anything ever performing it:

```python
ags.actions.create(                                        # write role
    "search_orders",
    display_name="Search orders",
    description="Looks up a customer's recent orders by id.",
)
```

The two converge. Tracking resolves an action by its name, so the first span
carrying `search_orders` **adopts** the row above rather than creating a second
one beside it — with the label you already gave it intact. Declare it, then
ship the tool, and there is still exactly one action.

That only works while a name means one thing, so `create()` raises
[`ValidationError`](./errors.md) on a name this agent already has:

```
An action named "search_orders" already exists for this agent.
```

It refuses rather than handing back the existing row, because you asked to
create something and quietly returning a different id is how you end up
updating an action you never meant to touch. Reach for
`ags.actions.list(name="search_orders")` if you need to know which one it is.

Uniqueness is **per agent** — a different agent of yours may hold
`search_orders` too, and normally will.

There is deliberately no `delete()`. Every recorded invocation hangs off the
definition, so removing one would take that action's whole history with it; the
route behind it refuses too. Rename or relabel with `update()` instead.

## What this namespace is for

`display_name` and `description` decide how an action reads in the dashboard,
and **a span carries neither**. For an action tracking created, this is the only
place they can be set:

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
Renaming onto a name this agent already holds is refused with the same 400
`create()` gives.

The action has to exist before you can label it — because your agent performed
it, or because you declared it with `create()` above.

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
