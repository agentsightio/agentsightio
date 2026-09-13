# The data plane: API client and REST surface

Reading and managing what was recorded — the two things that are *created*
here rather than by the tracking SDK, feedback and action definitions — and the
one thing *edited after the fact*: a message's metadata. Unlike the tracking
plane, **everything here raises on failure**; that is the point of a read
client.

Full references: `docs.agentsight.io/api/` (Python client) and
`docs.agentsight.io/getting-started/api-reference` (REST).

## Contents

- [Recording is not on this surface](#recording-is-not-on-this-surface)
- [The client](#the-client)
- [Conversations](#conversations)
- [Messages: metadata after the turn](#messages-metadata-after-the-turn)
- [Feedback — the one thing to wire](#feedback--the-one-thing-to-wire)
- [Actions: labelling for the dashboard](#actions-labelling-for-the-dashboard)
- [Usage and cost](#usage-and-cost)
- [Spans and traces](#spans-and-traces)
- [REST notes for non-Python callers](#rest-notes-for-non-python-callers)
- [Exceptions](#exceptions)

## Recording is not on this surface

Conversations, messages, tool calls, token usage, buttons and attachments have
**exactly one way in for live traffic: the tracking SDK.** There is no HTTP
endpoint for creating them — a design decision, not a gap (two write paths
would mean two sets of semantics). This settles the multi-service question
honestly:

- A **non-Python service** in the conversation path cannot record directly.
  The options are: propagate the conversation id and fields into the Python
  service that does the recording; add a small Python component that owns the
  recording; or accept the gap, named in the report.
- What any language **can** do over REST: create feedback, declare and label
  actions, edit the metadata of a message that already exists, and read
  everything back.

Creating is not editing. A message the tracking SDK already recorded can have
its **metadata** changed here afterwards — [the one write on a
message](#messages-metadata-after-the-turn) this plane allows. Its content,
sender and timestamp cannot: they are the transcript, and the transcript stays
tracking's.

There is one other way conversations get in, and it is not this surface
either: a **bulk import of historical conversations**, uploaded as a JSON file
in the dashboard. It carries conversations and their messages and nothing else
— no tool calls, no token usage or cost, no geolocation — and it is
deliberately not on the API-key plane, so no client here can drive it. It is
also **not a second way to record live traffic**: dedup is on
`(agent, conversation_id)`, and an id that already exists is rejected
(`conversation_already_exists`), never merged into. Building that file is the
`agentsight-migration` skill's job.

## The client

```python
from agentsight.api import AgentSight

ags = AgentSight()          # key from AGENTSIGHT_API_KEY; or AgentSight("ags_…")
ags.me()                    # the preflight: agent id/name, role, environment slugs
ags.environments()          # ['production', 'development', …] — the authoritative list
```

- Construction: `AgentSight(api_key=None, *, endpoint=None, timeout=15,
  max_retries=3)`. Usable as a context manager; `close()` when long-lived.
- **A key belongs to exactly one agent** — "which agent" is never a
  parameter. Reading two agents means two keys.
- Roles: a key is `read` or `write`. Recording and every write here need
  `write`; `me()["role"]` is the only way to know in advance.
- Namespaces: `ags.conversations`, `ags.messages`, `ags.feedbacks`,
  `ags.actions`, `ags.usage`, `ags.spans`.
- Lists paginate; iterate the returned pages/iterator rather than assuming one
  page. The client refuses filter names it does not recognise **before
  sending** — deliberately, because on the raw REST surface an unknown query
  parameter is ignored and silently widens the result set.
- Conversation arguments accept the numeric id or the business string id
  (`"wa-3859"`) interchangeably; string ids are resolved and cached. Messages
  have no business id — `ags.messages` takes the integer pk only, and refuses
  a string rather than looking it up.

## Conversations

- `list(**filters)` / `list_full(**filters)` — summaries vs full transcripts;
  list what you need, `list_full` is the heavier call.
- `list(include_tickets=True)` — **narrows AND includes**: only conversations
  with at least one ticket come back, each carrying its `tickets` at full
  depth (discussion thread included). Never add it to a listing that must
  stay complete. `get()` carries tickets unconditionally.
- `get(conv, full=True)`, `attachments(conv)`, `metadata_keys()`,
  `metadata_values(key)`, `resolve(conv)`, `rename(conv, name)`,
  `mark(conv, is_marked=True)`, `update(conv, **fields)`.
- A transcript message's `id` is its pk — the handle `ags.messages` and
  `feedbacks.create_for_message` take. `list()` summaries carry no messages;
  `get()` and `list_full()` do.
- `update_metadata(conv, metadata=None, *, remove=None)` — reads before it
  writes, so it merges against the server state; use this (not the tracking
  call) when the conversation is closed or another process wrote the previous
  keys.
- `delete(conv)` — **soft, and the only kind.** The conversation leaves lists
  and dashboards; there is no purge on this surface. State this plainly when
  retention or erasure comes up.

## Messages: metadata after the turn

```python
message = ags.messages.get(4821)                                    # read role
ags.messages.update_metadata(4821, {"visualization": record})      # write role
ags.messages.update_metadata(4821, remove=["draft"])
ags.messages.update(4821, metadata={"visualization": record})      # replaces the whole document
await asyncio.to_thread(ags.messages.update_metadata, 4821, data)  # off an event loop
```

Message metadata — the document `agent_message(content, metadata=…)` recorded
with the message — is what the dashboard's **message templates** render inside
the bubble; conversation metadata is only a raw key/value tab. So what the
application learns about a message *after* the turn — a picture generated for
it in the background, a verdict from a later check, a score — belongs on that
message, next to what the turn wrote, and this namespace is the only way to put
it there once the turn is over. Needs `agentsight >= 0.1.4`; on older versions
`ags.messages` is an `AttributeError`.

**Never record a second message for it.** The tracking plane orders a
transcript by what it observed, so a message recorded when the job finishes
lands after whatever the user said in the meantime — the same mechanism as the
orphan half-exchange in [debugging.md](debugging.md), except deliberate and
harder to spot. Editing the metadata of the message that exists reorders
nothing.

- **The pk only.** Messages have no business id; the argument is the integer
  `id` a transcript row carries (`ags.conversations.get(conv)["messages"][n]["id"]`).
  A string is refused, not looked up. No `list()` and no create — messages come
  nested in their conversation.
- **Metadata is the only field.** `update()` takes nothing else; content,
  sender and timestamp stay what tracking observed.
- `update_metadata()` reads the stored document, merges, writes it back — the
  conversation twin's rules: **shallow** (a nested dict is replaced whole),
  **nothing filtered** (`None`, `False`, `0`, `""` are stored as given),
  `remove` the only delete, an absent key in `remove` a no-op. Two round trips,
  not atomic — two jobs enriching the same message at the same moment can lose
  one update. It raises rather than merging into `{}` when the server withholds
  the field, so it never blanks a document by accident.
- `update(metadata=…)` **replaces** the document; keys not sent are gone.
- Write role for both; blocking, like the rest of this client.

What the dashboard then shows is decided by a **message template** — per
agent, created in the AgentSight dashboard by an Owner or Editor (not reachable
with an API key: describe the template to the developer, you cannot create
it). A template binds dot-path keys and renders its HTML with `{{key.path}}`
tokens (`{{#each key.path}}…{{/each}}` over arrays) **only when every bound
key resolves on that message** — null and empty arrays count as missing, so a
failed job whose image URL is null hides an image block by itself. Images open
in a lightbox. The agent's `show_message_metadata` flag must be on (default
on).

## Feedback — the one thing to wire

Feedback is created here, not by the tracking SDK, because it arrives from the
developer's own UI on its own schedule — often after the conversation is over:

```python
ags.feedbacks.create_for_conversation("wa-3859", "positive", comment="solved it")
ags.feedbacks.create_for_agent("negative", comment="too slow")   # about the agent overall
ags.feedbacks.create_for_message(4821, "negative", topic="style", reason="too_bold")
```

- `sentiment` ∈ `positive` / `neutral` / `negative`. Comment optional. Write
  role required.
- `create_for_message` targets one message by pk (the transcript carries the
  ids). `topic`/`reason` are the host app's own slugs — stored and counted,
  never interpreted. One vote per message: a repeat call updates the stored
  vote (server answers 200, not 201), and the vote reads back nested on its
  message in the transcript payloads.
- Also: `list(**filters)`, `get(id)`,
  `update(id, sentiment=…, comment=…, topic=…, reason=…)`, `delete(id)`.
- Wiring it means one small endpoint in the developer's backend that their UI
  calls — offer it, don't assume it; default: not wired, reported as a gap.
- Retried writes are not idempotent — a replayed create is a second row —
  except `create_for_message`, which updates the one vote per message and is
  safe to retry.
- Tickets ride behind the same gate as conversations:
  `list(include_tickets=True)` narrows to promoted feedback AND puts the
  nested `ticket` (full depth) on each row; `has_ticket` / `ticket_status`
  work only alongside it (400 without); `get(id)` carries the ticket
  unconditionally.

## Actions: labelling for the dashboard

An action's `display_name` and `description` are how a tool reads on the
client-facing dashboard, and they do not travel with tool calls:

```python
ags.actions.update(action_id, display_name="Order lookup")
ags.actions.create("lookup_order", display_name="Order lookup")   # declare before first run
```

Tracking usually brings the action into being (first decorated call carrying
the name); declaring up front puts it on the dashboard before the tool ships,
and the first real call adopts the row. There is no `delete()` — every
recorded invocation hangs off the definition. `logs(id)` lists invocations.
Default: function names as-is, with a labelling pass proposed to the developer.

## Usage and cost

```python
ags.usage.summary(group_by="model", currency="usd")   # model | conversation | day; usd | eur
ags.usage.list(model="gpt-4o", started_at_after=…)
```

Per-turn, per-model rows with exact token columns. `cost_source` on each row
tells you where the figure came from — server-priced, or `unpriced` for a
model with no rate yet (tokens exact, cost restated when a rate exists;
never silently zero). EUR values are omitted, not zeroed, where no exchange
rate was on file — handle the missing key.

## Spans and traces

The raw record beneath the dashboard — useful for debugging an integration
remotely (the local-first tool is the file exporter,
[debugging.md](debugging.md)):

- `ags.spans.list(**filters)` — filter by `conversation_id`, `trace_id`,
  `kind`, `status`, `environment`, time range.
- `ags.spans.get(id, payload=False)` — `id` is the row id from a list, not the
  hex `span_id`.
- `ags.spans.trace(trace_id)` — the tree: a turn with its tools and LLM calls
  nested beneath it. A `truncated: true` means spans are missing.

## REST notes for non-Python callers

For reading and feedback from another language:

- Base URL `https://api.agentsight.io`; every path ends in a slash and **the
  slash is load-bearing** — without it the answer is a 404 in HTML, so a JSON
  parse fails before the status is read. Copy paths exactly from the REST
  reference.
- Auth on every request: `Authorization: Api-Key ags_YOUR_KEY`. Keys are
  issued in the dashboard, shown **once** at creation, revocable. Never in a
  browser or client-side code.
- `GET /api/me/` is the preflight: agent, role, environment slugs. The 401
  worth catching separately: *"Agent does not have an active subscription or
  development phase"* — the credential is fine, the account is not; rotating
  the key fixes nothing.
- Lists share one envelope (`count`, `page_size`, `total_pages`,
  `current_page`, `next`, `previous`, `results`); `page_size` caps at 100
  (clamped, not refused). **An unknown query parameter is ignored, not
  rejected** — a typo widens the result set silently, so check `count` and
  copy filter names from the reference.
- A row belonging to another agent answers `404`, indistinguishable from
  absent — by design. `403` is about the key (read role attempting a write).
- One message: `GET /api/track/{pk}/` (read role); `PATCH /api/track/{pk}/`
  with `{"metadata": {...}}` (write role) edits its metadata and **replaces
  the whole document**, so read first, merge, write back. Content, sender and
  timestamp are outside the contract.
- `429` carries `Retry-After` in seconds — honour it. Rate numbers are
  capacity controls, not contract; none are published. Retry reads; do not
  blindly retry writes — nothing on this API is idempotent, with two
  exceptions: `create_for_message` (one vote per message, a repeat updates it)
  and a message-metadata `PATCH` resent with the same body (it is the
  read-merge-write around it that can lose a concurrent edit, not the write).

## Exceptions

All under `agentsight.AgentSightError`:

- `ConfigurationError` → `MissingApiKeyError`, `InvalidApiKeyError`
- `APIError` (carries status and response) → `AuthenticationError`
  (→ `SubscriptionInactiveError`), `PermissionDeniedError`, `NotFoundError`,
  `ValidationError`, `MethodNotAllowedError`, `RateLimitError`
  (`.retry_after`), `ServerError`
- `NetworkError`, `UploadError`

Catch `SubscriptionInactiveError` apart from bad-key errors — its fix is
billing, not the key. `RateLimitError.retry_after` is the server's own pacing.
