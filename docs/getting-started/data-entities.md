---
outline: deep
---

<CopyMarkdownButton />

# Data entities

A common shape for an AI agent is one central system serving many clients, each
with its own data: one hotel-booking agent, many hotels. A **data entity** is how
that shape is recorded. Each conversation says which hotel it belongs to, the
dashboard filters by it, and a hotel can be given an embedded dashboard that shows
only its own conversations. You keep one agent and one API key.

## The hotel example

```python
import agentsight

agentsight.init()

def handle_message(hotel_code, session_id, text):
    with agentsight.conversation(session_id, data_entity=hotel_code):
        with agentsight.turn():
            agentsight.user_message(text)
            answer = agent.run(hotel_code, text)
            agentsight.agent_message(answer)
```

That is the whole integration. There is nothing to declare first: the first time
`"hotel-paris"` arrives, AgentSight creates it, and every later conversation with
that key lands under it.

The argument is optional, and passing it is the opt-in. A conversation without one
has no entity, nothing is created, and nothing changes for an integration that
never uses this.

## What a key is

The key is your own identifier: a hotel code, a tenant slug, a client id. Pick
something stable, because it is permanent.

- **Trimmed, and matched case-insensitively.** `"Hotel-Paris"` and `"hotel-paris"`
  are one entity, and the first spelling seen is the one kept.
- **Up to 255 characters of any printable text.** The SDK clamps a longer key and
  warns once. A blank key counts as no key.
- **Permanent.** A key cannot be changed once it exists. It is what your tracking
  code sends and your filters name. The display **name** is what you edit, and it
  starts out equal to the key.

A key containing a NUL or an unpaired surrogate is dropped with one warning and the
conversation is recorded without an entity. The API refuses those characters, and
sending one would cost every conversation in its batch.

## What happens to a conversation

| Situation | Result |
|---|---|
| No key | No entity, shown as **Unassigned**. Nothing is created. |
| A key seen for the first time | The entity is created, named after its key, and the conversation is linked. |
| A known key, in any casing | Linked. |
| The key of a deleted entity | Linked anyway. The entity shows as still receiving traffic. |
| An unknown key, with the agent at its [cap](#the-cap-of-500) | Recorded as Unassigned, and the agent's overflow counter goes up. |
| A later key that differs from the one already set | Ignored, and the backend logs it. The conversation keeps the first. |
| A later key on a conversation that has none yet | Linked now, and the usage already recorded for that conversation moves with it. |

### A conversation's entity is set once

The first key that reaches a conversation is the one it keeps, so one conversation
can never be split across two hotels in your reports. Spans without a key do not
lock anything in, so a key that arrives later still applies.

The other side of this is that **a wrong key cannot be corrected**. Moving a
conversation to another entity is not supported, and `conversations.update()`
refuses the field.

Conversations recorded before you started passing a key stay Unassigned. A
history import can name an entity per conversation — the import file's optional
`data_entity` field, which [importing history](./importing-history.md) covers — and
conversations imported without one are Unassigned too.

## Where to pass it

Pass it on `conversation()`, or on `open_conversation()` for the
[visit phase](/tracking/conversations#the-visit-phase). The decorator form of
`turn()` also takes it when it opens the conversation itself:

```python
@agentsight.turn(id_from="session_id", data_entity="hotel-paris")
def handle_message(session_id, text):
    ...
```

A turn that runs inside a conversation already open can name the key too, in
either form:

```python
with agentsight.conversation(session_id):
    with agentsight.turn(data_entity=hotel_code):
        ...
```

The key goes onto the conversation, as long as it has none. A conversation keeps
its first key, so a different one named later is ignored and the SDK warns once.
Outside any conversation a `with agentsight.turn(...)` records nothing, with or
without a key.

### Attachments

`upload_attachments()` sends the key when it runs inside the conversation's own
scope. Given a different `conversation_id`, or called outside any scope, it sends
no key, because the conversation may be recorded under a key this call cannot see
and a wrong one would be permanent. That conversation gets its entity from its
next span. If it never has one, it stays Unassigned.

## A default for the whole deployment

A deployment that serves one client can set the key once, the way it sets the
[environment](./environments.md):

```python
agentsight.init(data_entity="hotel-paris")
```

```bash
AGENTSIGHT_DATA_ENTITY=hotel-paris
```

A conversation that names its own key wins over the default, and an argument to
`init()` wins over the variable.

A key named on a turn also wins over the default, but only until something has
been recorded for that conversation. After its first span or upload the backend
holds the default, and the conversation stays on it.

:::warning Choose a default or per-conversation keys, not both
The default means "everything in this deployment belongs to this client". Anything
recorded before the conversation's own key is named goes out under the default, and
the first key sticks: `open_conversation(cid)` without the key is the usual case.
If your conversations carry their own keys, leave the default unset.
:::

## The cap of 500

An agent can hold **500 active data entities**. Past that:

- An unknown key is recorded as Unassigned. If a later span of that conversation
  carries a key when there is room, it is linked then.
- Keys that already exist keep working, including deleted ones.
- Creating or restoring an entity through the API answers `400`.
- A counter records how many times a conversation went Unassigned this way, and
  when the last one did. It appears on the Data entities settings page and from
  the API:

```python
ags.me(refresh=True)["data_entities"]
# {'limit': 500, 'active_count': 500, 'overflow_count': 12, 'overflow_at': '2026-11-02T09:14:07Z'}
```

Deleting entities frees slots. A cap this size usually means something other than
real clients is reaching the key, such as a session id passed by mistake.

## Deleting and restoring

Deleting an entity is a soft delete, and **no data is lost**. Its conversations keep
it, and its key stays reserved so that its history has one row.

A deleted entity is hidden from the filter dropdowns and frees its slot under the
cap. Traffic that still sends its key keeps landing on it, and the settings page
then marks it as still receiving traffic and offers **Restore**.

Embed tokens pinned to a deleted entity [stop working](#a-dashboard-for-one-client)
until it is restored.

## Entities and environments

The two are independent. An agent has one list of entities, spanning its
environments, and a conversation carries one of each. Filters compose, so
`production` and `hotel-paris` means exactly that.

An [environment](./environments.md) separates test traffic from real traffic. An
entity separates one client from another. Analytics still cover production only,
and a filter on an entity narrows that same report.

## Where it shows up

- **Settings → Data entities**, to name, edit, delete and restore them.
- **An entity switcher** beside the environment switcher, with "All entities" and
  "Unassigned". All includes the Unassigned rows.
- **Filters and badges** on the analytics report (including its cost card and token
  chart), conversations, feedback and tickets. Saved reports are stamped with the
  entity they were made for, and older reports appear under All.

Feedback about the agent as a whole and tickets without a conversation belong to no
entity, so they appear only under All. Development Mode's check of which metrics are
receiving data stays agent-wide, and comparing entities side by side in one report
is not available.

## Reading it back

Every conversation, usage and feedback row carries its key in `data_entity`, and so
does a ticket's nested `conversation`. It is `null` for Unassigned and for a row with
no conversation. The same two filters work on conversations, feedback, tickets and
usage, in the [API client](/api/data-entities) and over
[REST](./api-reference.md#data-entities):

```python
from agentsight.api import AgentSight

ags = AgentSight()

ags.conversations.list(data_entity="hotel-paris")        # any casing
ags.conversations.list(data_entity_unassigned=True)      # no entity
ags.conversations.list(data_entity_unassigned=False)     # any entity
ags.usage.summary(data_entity="hotel-paris")             # what one client cost
```

Against a backend without data entities the API client refuses these filters with
a `ValidationError` instead of sending them, because that backend would ignore
them and return every row. Over raw REST nothing stops the request, so check
`capabilities` on `/api/me/` for `data-entities` first.

:::danger A filter is not a tenant boundary
An API key sees its whole agent, so these filters are a convenience for your own
code, not isolation. Never rely on one to decide what a client is allowed to see.
Use a scoped embed token, which the server enforces.
:::

## A dashboard for one client

An embed token can be **pinned to one entity** when you create it in the dashboard.
The server then applies that scope to everything the embed reads, whatever the page
asks for. One token per hotel gives each hotel its own dashboard.

- There is no snippet attribute for this, on purpose. Anyone can edit a page's
  markup, so the scope lives on the token and the snippet stays the same.
- A scoped embed hides the entity selector and shows the entity's name in its
  header. An unscoped embed shows a selector beside the environment selector.
- A scoped embed sees only saved reports stamped with its entity. Older reports
  hold numbers across all entities and would leak between clients.
- If the entity is deleted, its tokens stop opening until it is restored. The
  dashboard warns you before the delete.

A token's scope cannot be changed afterwards. To change it, revoke the token and
create another.

An embed is not the only way. To give a client's own staff a login instead, invite
them under **Settings → Team** as Viewers restricted to their entity. A **domain
rule** on the same page does it for everyone who signs in through your agent's
subdomain with a verified address at the client's email domain. The server enforces
a Viewer's restriction the way it enforces a token's scope.

## Checking it

The file exporter shows exactly what would be sent, with no backend:

```bash
AGENTSIGHT_FILE_EXPORTER=./agentsight-traces python your_app.py
jq '.conversations[] | {conversation_id, data_entity}' ./agentsight-traces/*.json
```

If every conversation reads Unassigned, the key is not reaching the conversation.
Look for a value that is blank at runtime, or a `turn()` carrying the key outside
any conversation.

## On an older backend

An older backend ignores the field and records the conversation without an entity,
so nothing fails and no data is lost. At startup, once the SDK has checked what the
backend supports, it logs one warning that `data_entity` is being ignored.
`init(verify_key=False)` turns that check off, and the warning with it. On such a
backend the [`data_entities`](/api/data-entities) namespace raises `NotFoundError`,
and the API client refuses the entity filters.

## Next

- [Conversations](/tracking/conversations) — every field a conversation can carry
- [The `data_entities` namespace](/api/data-entities) — naming, declaring, deleting
  and restoring entities from code
- [Environments](./environments.md) — the other partition, and how the two compose
