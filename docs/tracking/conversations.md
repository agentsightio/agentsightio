---
outline: deep
---

<CopyMarkdownButton />

# Conversations

A conversation is the thread your customer would recognise — a WhatsApp
exchange, a support session, a week of back-and-forth about one order. It is
what everything else is filed under, and it is the only thing in the SDK you
have to name yourself.

## Opening one

```python
import agentsight

with agentsight.conversation("wa-3859"):
    ...
```

The id is **a business string you control** — whatever your own system already
calls that thread. Use the same one again tomorrow and it is the same
conversation, across restarts, deploys and however many processes your
architecture involves. Your data and AgentSight's then agree on what "this
conversation" means without a mapping table between them.

Omit it and one is generated:

```python
with agentsight.conversation():
    ...
```

That is what you want for a throwaway session and never what you want for a real
thread — nothing later can tie a generated id back to the customer it belonged
to.

The scope works three ways. As a context manager, as an async context manager,
and as a decorator:

```python
@agentsight.conversation(customer_id="user-456")
def nightly_summary():
    ...
```

The decorator builds a fresh scope on every call, so a handler decorated without
an explicit id records **one conversation per invocation** rather than pooling
every caller into one. When you do want them pinned together, pass an id — or
reach for `turn(id_from=...)`, which takes the id out of the handler's own
arguments and is shown in the [Quickstart](/getting-started/quick-start).

A conversation produces no span of its own. What it does is establish scope: the
fields below are stamped onto everything recorded inside it, which is what makes
them filterable later without you threading context down your call stack.

## What you can attach

All optional, all keyword-only.

| Parameter | Type | Default |
|---|---|---|
| `customer_id` | `str` | — |
| `customer_ip_address` | `str` | — |
| `device` | `str` | — |
| `source` | `str` | — |
| `language` | `str` | — |
| `name` | `str` | — |
| `environment` | `str` | from `init()` |
| `metadata` | `dict` | — |
| `enabled` | `bool` | `True` |

**`customer_id`** — your own identifier for the person on the other end. It is
what turns a pile of conversations into one customer's history.

**`customer_ip_address`** — used for geolocation on the dashboard. It has to
parse as an IP address; anything that does not is dropped rather than sent.

**`device`** — `"desktop"`, `"mobile"`, `"tablet"`, or whatever vocabulary your
product uses. Free text, not an enum.

**`language`** — the language the conversation is being held in.

**`name`** — a human-readable title for the thread, shown in place of the id.

**`environment`** — `"production"` or `"development"`, plus any custom slug your
agent has. Per-conversation always wins over the deployment-wide default, because
a development conversation inside a production process is your statement, not the
SDK's to override. See [Environments](/getting-started/environments).

**`metadata`** — a free-form dictionary for anything the fields above do not
cover: plan, order id, experiment arm. Changeable afterwards, which is the next
section.

**`enabled`** — pass `False` and everything inside the scope becomes a no-op.
Useful for test traffic and evaluation runs that should not land in the same
numbers as real customers.

:::warning `source` is recorded but not surfaced
`source` is stored with the conversation's archived spans and can be read back
from them, but it does not reach the conversation itself — no dashboard, filter
or API response shows it today. It is still worth sending if you want the record;
it is not something to build a filter on. Every other field above behaves the way
you would expect.
:::

Values are kept honest on the way out rather than on the way in: string fields
are clamped at 255 characters and an unparseable IP is dropped, because a single
over-length field would otherwise be enough to reject every conversation
travelling in the same batch. Nothing raises, and nothing is lost but the
overflow. The full table is in
[What the SDK sends](/getting-started/what-the-sdk-sends).

## Changing metadata afterwards

The scope takes its metadata once, at the top of a handler — which is before most
of what is worth recording has happened. `update_metadata()` is the same field
afterwards:

```python
with agentsight.conversation("wa-3859", metadata={"order_id": "A-1"}):
    with agentsight.turn():
        agentsight.user_message(text)
        outcome = await agent.run(text)
        agentsight.agent_message(str(outcome))

    agentsight.update_metadata({"topic": "delivery", "self_served": False})
```

Four rules, and they are the whole of it:

- **It merges, it does not replace.** `order_id` above survives.
- **The merge is shallow.** A nested dictionary is replaced whole rather than
  merged key by key, which is what keeps "replace this sub-object" sayable.
- **No value is filtered.** `None`, `False`, `0` and `""` are stored exactly as
  given. `self_served=False` above is data, not an omission.
- **`remove=` is the only way to delete a key**, and naming one that is not
  there does nothing:

```python
agentsight.update_metadata(remove=["awaiting_reply"])
agentsight.update_metadata({"plan": "enterprise"}, remove=["trial_ends"])
```

The last two rules are one decision seen from both sides. A call that dropped
falsy values would silently lose every `False` you meant to record, so deletion
had to be said out loud instead.

It needs an active conversation scope; outside one there is nothing to update and
the call does nothing. Like every other tracking call, it never raises — a
malformed argument is dropped rather than thrown at your handler.

:::info When the previous state lives somewhere else
The merge is against what *this* process knows: the scope's own metadata plus
whatever earlier calls in the same scope set. Keys written by another process are
not visible here, so they are not preserved. When the conversation is already
closed, or the previous state is only on the server, use the API client's
`conversations.update_metadata()` instead — it reads before it writes.
:::

## The visit phase

Someone loaded the widget and typed nothing. That is worth recording, and no
decorator can express it — a decorator only fires once somebody has already
engaged:

```python
agentsight.open_conversation(
    "wa-3859",
    device="mobile",
    source="web",
    language="en",
)
```

It takes the same fields as `conversation()`, records that the conversation
exists, and marks nothing as engaged. **Any tracked activity — in practice, the
first turn — marks engagement**, which is exactly the difference between "the widget loaded" and
"the user said something" — and therefore the difference your interaction metrics
depend on.

It is delivered on the same schedule as everything else, so it arrives within an
export interval rather than instantly. For a widget-loaded event that changes
nothing.

## Next

- [Turns & Messages](./turns-and-messages.md) — what goes inside the scope, and
  the shapes a real exchange takes
- [Metrics](/getting-started/metrics) — what the visit phase and the first turn
  are counted as
- [Environments](/getting-started/environments) — how `environment` is resolved,
  and what happens to a slug your agent does not have
