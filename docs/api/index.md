---
outline: deep
---

<CopyMarkdownButton />

# The API client

`import agentsight` starts telemetry. **`agentsight.api` is the other
direction** — the client you hold when you want the data back out: the
conversations that were recorded, what they cost, the feedback people left, and
the raw spans underneath all of it.

```python
from agentsight.api import AgentSight

ags = AgentSight()

for conversation in ags.conversations.list(has_feedback=True):
    print(conversation["conversation_id"], conversation["name"])

ags.conversations.rename("wa-3859", "Refund — resolved")
```

The two halves share a package and nothing else. Tracking never raises and
never blocks, because a monitoring library that breaks your handler is worse
than no monitoring. This client always raises, because it moves customer data
and returns answers you are going to act on — here, silence would be the bug.

## Building one

```python
from agentsight.api import AgentSight

ags = AgentSight()                          # reads AGENTSIGHT_API_KEY
staging = AgentSight(api_key="ags_…")       # or name the key yourself
```

| Parameter | Type | Default |
|---|---|---|
| `api_key` | `str` | `AGENTSIGHT_API_KEY` |
| `endpoint` | `str` | `AGENTSIGHT_API_ENDPOINT`, else `https://api.agentsight.io` |
| `timeout` | `float` | `15` |
| `max_retries` | `int` | `3` |

`api_key` is the one positional argument; the rest are keyword-only. A key
found in a local `.env` file works the same as one exported in the shell, as
long as `python-dotenv` is installed.

The key is checked for shape at construction rather than on the first request,
so a truncated paste fails where you can see it —
[`MissingApiKeyError`](./errors.md) when there is none at all,
`InvalidApiKeyError` when what you passed is not shaped like a key. A key that
passes that check can still be refused by the server; that arrives later, as an
`AuthenticationError`.

`timeout` is per request. `max_retries` applies to reads only — see
[Errors and retries](./errors.md) for what does and does not get replayed.

## As many clients as you have keys

A key belongs to exactly one agent in one account, so "which agent" is not a
parameter anywhere in this client — it is the key. Staging and production, or
two different agents, means two clients in the same process:

```python
production = AgentSight(api_key=os.environ["AGENTSIGHT_KEY_PROD"])
staging = AgentSight(
    api_key=os.environ["AGENTSIGHT_KEY_STAGING"],
    endpoint="https://api-staging.agentsight.io",
)
```

Each keeps its own connection pool and its own caches, and neither knows about
the other.

For a script that only ever needs one, there is a module-level default:

```python
from agentsight.api import client

client.conversations.list()
```

It is built the first time you touch it, **never at import**. That distinction
is the reason importing `agentsight` reads no configuration and opens no
connection: a module-level client that constructed itself at import would raise
in any process that has no API key set, including one exporting spans to a file
and talking to nobody.

## Closing it

The client pools connections, and a `with` block releases them:

```python
with AgentSight() as ags:
    for row in ags.usage.list(model="gpt-4o-mini"):
        ...
```

`ags.close()` does the same thing without the block. In a long-lived service,
build one client at startup and keep it — there is nothing per-request about it,
and a new client per request throws away the pool and every cached lookup.

## Who this key is

`me()` answers the three questions you would otherwise have to guess at:

```python
ags.me()
```

```json
{
  "agent_id": 20,
  "agent_name": "demo agent",
  "role": "write",
  "environments": [
    { "id": 39, "slug": "production", "name": "Production", "is_production": true },
    { "id": 40, "slug": "development", "name": "Development", "is_production": false }
  ],
  "capabilities": ["…"]
}
```

`role` is `read` or `write`, and it is the only way to know in advance whether a
write will be refused; there is no other endpoint that reports a key's own
permissions. A `read` key raises `PermissionDeniedError` on every method marked
*write role* in these pages.

The payload is returned exactly as it arrives, so a newer backend may add keys
this page does not list. It is fetched once and cached for the life of the
client — pass `refresh=True` to fetch it again.

`environments()` is the flat slug list, which is the form every `environment=`
filter wants:

```python
ags.environments()      # ['production', 'development']
```

It reads the same cached payload as `me()`, and takes the same `refresh=True`.

## Naming a conversation

Every method that identifies a conversation takes **either id**: the business
`conversation_id` you passed to `agentsight.conversation(...)`, or the backend's
integer primary key.

```python
ags.conversations.get("wa-3859")     # the id your application knows
ags.conversations.get(737)           # the one the dashboard URL shows
```

A string costs one lookup the first time and none afterwards — the mapping is
remembered per client. Listing conversations primes that cache for every row it
returns, so walking a list and then managing rows costs no extra requests at
all:

```python
for conversation in ags.conversations.list(is_marked=True):
    ags.conversations.rename(conversation["conversation_id"], "Reviewed")
```

`ags.conversations.resolve("wa-3859")` performs the lookup on its own if you
want it explicit rather than implicit. The cache holds the most recent thousand
or so mappings and is per client, so it never grows without bound in a
long-running process.

Two methods manage it by hand, for the rare case where you have conversation
records from somewhere else — a webhook body, a queue message — and would rather
not pay for lookups you can already answer:

```python
ags.remember(record)      # a payload naming both ids primes the cache
ags.forget("wa-3859")     # drop one mapping
```

`remember()` ignores anything that does not name both ids, so feeding it an
arbitrary payload is safe. `forget()` is called for you by `delete()`, because a
deleted conversation's primary key is not something to keep handing out.

## What it deliberately cannot do

This client reads and manages; it does not record. **It cannot create a
conversation, a message, an action log, a button click or an attachment** —
those belong to the tracking SDK, and two ways to write the same row would mean
two sets of semantics for how that row reaches the dashboards.

The three things it does create are not records of a run. Feedback, for a
reason [its own page](./feedbacks.md) explains. An action **definition** — note
that this is the definition, not the action *log*: `actions.create()` declares
that a capability exists, and the tracking SDK adopts that declaration the first
time the capability actually runs; see [Actions](./actions.md). And
[tickets](./tickets.md) — workflow items a team, or the agent itself, decides
to file, which no span could ever observe either.

There is also no `buttons` namespace. `agentsight.button()` records clicks and
they are archived complete, but nothing currently projects them into a table
this client could read, so a `buttons.list()` here would return an empty page to
every caller — which reads as "no clicks" rather than "not surfaced yet". The
clicks are readable as what they actually are:

```python
ags.spans.list(kind="button")
```

## The namespaces

| Namespace | What it covers |
|---|---|
| [`conversations`](./conversations.md) | reading, filtering and managing them |
| [`feedbacks`](./feedbacks.md) | the feedback surface, and the one place this records |
| [`tickets`](./tickets.md) | the agent's workflow items — full CRUD, filed as the machine |
| [`actions`](./actions.md) | action definitions, their logs, their labels |
| [`usage`](./usage.md) | tokens spent and what they cost |
| [`spans`](./spans.md) | the raw archive everything else is projected from |

## Next

- [Conversations](./conversations.md) — the namespace you will reach for first
- [Pagination](./pagination.md) — how lists walk themselves, and how to read a
  count without walking anything
- [Errors and retries](./errors.md) — the exception hierarchy, and which
  requests are replayed
- [What the SDK sends](/getting-started/what-the-sdk-sends) — the other half of
  the story: exactly what got recorded in the first place
