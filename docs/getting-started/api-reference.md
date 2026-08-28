---
outline: deep
---

<CopyMarkdownButton />

# REST API reference

Everything the tracking SDK records is readable back over HTTP, with nothing but
an API key and a client that speaks JSON. This page is the contract: paths,
parameters, response shapes and errors, for the read-and-manage surface an API
key can reach.

> **Working in Python?** [The API client](/api/) covers this same surface with
> pagination, typed errors, retries and id resolution already handled. This page
> is for every other language — and for reading exactly what goes on the wire.

A few routes an API key can reach are deliberately outside this contract — an
id-lookup helper, attachment-URL signing, and a `?paginate=false` switch on the
list routes. They may change without notice; nothing below depends on them.

```bash
curl "https://api.agentsight.io/api/conversations/?full=false&page_size=2" \
  -H "Authorization: Api-Key ags_YOUR_KEY"
```

## Base URL

```
https://api.agentsight.io
```

Every path below is absolute against that host, and every one of them ends in a
slash. **The slash is load-bearing.** A request without it is not redirected —
it is a `404`, and that particular one answers in HTML rather than JSON, so a
client that assumes a JSON body will fail on the parse rather than on the
status. Copy the paths exactly.

:::info Recording data is the SDK's job, not this API's
This page documents reading and managing. **Conversations, messages, tool calls,
token usage, button clicks and attachments have exactly one way in: the
[tracking SDK](/getting-started/quick-start).** There is no HTTP endpoint here
for creating them, and that is a design decision rather than a gap — two ways to
write the same row would mean two sets of semantics for how it reaches your
dashboards, and only one of them could be the one that is tested.

Two things you *can* create here are not recordings of a run: feedback, for the
reason its [own section](#feedbacks) explains, and an action **definition** —
declaring that a capability exists, which the SDK then adopts the first time it
actually runs.
:::

## Authentication

Every request carries your API key in the `Authorization` header:

```http
Authorization: Api-Key ags_YOUR_KEY
```

Keys are issued in the [dashboard](https://app.agentsight.io/). **A key belongs
to exactly one agent**, so "which agent" is never a parameter — it is the key.
Reading two agents means two keys.

### Roles

A key is `read` or `write`. Every endpoint below is marked accordingly; a
`read` key attempting a write gets `403`.

### Who this key is

<span class="api-method get">GET</span> `/api/me/` — *read role*

The preflight call. It answers the three things you would otherwise have to
guess at: which agent the key is bound to, what it is allowed to do, and which
environment slugs exist.

```bash
curl "https://api.agentsight.io/api/me/" \
  -H "Authorization: Api-Key ags_YOUR_KEY"
```

<details>
<summary><code>200 OK</code></summary>

```json
{
  "agent_id": 20,
  "agent_name": "demo agent",
  "role": "write",
  "environments": [
    {
      "id": 39,
      "slug": "production",
      "name": "Production",
      "is_production": true,
      "created_at": "2026-08-01T11:13:21.607086Z",
      "updated_at": "2026-08-01T11:13:21.607088Z"
    },
    {
      "id": 40,
      "slug": "development",
      "name": "Development",
      "is_production": false,
      "created_at": "2026-08-01T11:13:21.607094Z",
      "updated_at": "2026-08-01T11:13:21.607096Z"
    }
  ],
  "capabilities": ["gzip-ingest"]
}
```

</details>

`role` is the only way to know in advance whether a write will be refused —
there is no other endpoint that reports a key's own permissions. The `slug`
values are what an `environment=` filter or an environment-scoped write wants;
note that two of the filters below accept only a fixed vocabulary rather than
any slug, and each says so where it appears.

The payload is returned as it arrives, so a newer release may add keys this page
does not list. Ignore what you do not recognise.

### When authentication fails

```json
{ "detail": "Authentication credentials were not provided." }
```

```json
{ "detail": "Invalid API key." }
```

Both are `401`, and both mean the same class of problem: no usable credential.
A key that is revoked, expired or not linked to an agent lands here too.

:::warning One 401 that rotating your key will not fix
```json
{ "detail": "Agent does not have an active subscription or development phase." }
```

The credential is fine; the account is not. Issuing a new key changes nothing —
this one is answered in the billing settings, not in the key settings. Worth
catching separately for exactly that reason.
:::

## How every list behaves

List endpoints answer with the same seven-key envelope:

```json
{
  "count": 539,
  "page_size": 2,
  "total_pages": 270,
  "current_page": 1,
  "next": "https://api.agentsight.io/api/conversations/?full=false&page=2&page_size=2",
  "previous": null,
  "results": [ … ]
}
```

| Key | Means |
|---|---|
| `count` | how many records match the filters, across all pages |
| `page_size` | how many were served on this one |
| `total_pages` | how many pages that makes |
| `current_page` | which one this is |
| `next`, `previous` | the neighbouring pages, or `null` at either end |
| `results` | the records |

| Parameter | Default | Notes |
|---|---|---|
| `page` | `1` | out of range answers `404` |
| `page_size` | `15` | **capped at 100**; a larger value is clamped, not refused |

Walking a result set by incrementing `page` is equivalent to following `next`
and is usually easier — `next` is an absolute URL built from the host header the
server saw, which is not always the host you want to call.

**`ordering`** takes a field name, prefixed with `-` for descending. Each
section lists the fields its route will sort on; anything else is ignored.

**Timestamps** are ISO 8601, always UTC:

```
2026-08-17T10:32:33.305953Z
```

Datetime filters accept the same form. **Booleans** are the lowercase strings
`true` and `false`.

:::danger An unknown query parameter is ignored, not rejected
```
GET /api/conversations/?has_tickets=true    →  count: 539
```

That filter does not exist — the real one is `has_ticket`, and it is not on this
plane at all. Nothing was applied, and the response is the entire result set
wearing the appearance of a filtered one. A typo here does not error; it
**widens** your result set, silently.

Two habits make that survivable: check `count` against what you expected, and
copy filter names from the tables below rather than typing them. This is also
why the [Python client](/api/) refuses filter names it does not recognise before
it sends anything — an error you can see beats a wrong answer you cannot.
:::

## Errors

| Status | Means |
|---|---|
| `200 OK` | done |
| `201 Created` | the row was created |
| `204 No Content` | deleted; the body is empty |
| `400 Bad Request` | the request was malformed, or a parameter was invalid |
| `401 Unauthorized` | missing, unusable or unentitled credential |
| `403 Forbidden` | authenticated, and not allowed to do this |
| `404 Not Found` | no such row — or one belonging to another agent |
| `405 Method Not Allowed` | that verb is not offered on that path |
| `429 Too Many Requests` | slow down; see below |
| `500 Internal Server Error` | our fault |

**Errors come in two body shapes.** A whole-request problem names a `detail`:

```json
{ "detail": "Method \"POST\" not allowed." }
```

A problem with specific parameters maps field to message. The value is
sometimes a string and sometimes a list of them, so read both:

```json
{ "sentiment": ["\"meh\" is not a valid choice."] }
```

```json
{ "group_by": "Must be one of: model, conversation, day." }
```

:::info Another agent's row answers `404`
An id that belongs to another agent answers `404`, indistinguishable from a row
that does not exist — which is the point. This holds on every detail route.
You will only see it if you are handling ids that did not come from your own
key.

A `403` is about you rather than about the row: a `read` key attempting a
write, or asking for something this plane does not serve at all.
:::

### Rate limiting

A `429` response carries a **`Retry-After`** header in seconds. Honour it: it is
the server's own pacing, and it is more accurate than any backoff curve you
would write against it.

```http
HTTP/1.1 429 Too Many Requests
Retry-After: 30
```

```json
{ "detail": "Request was throttled. Expected available in 30 seconds." }
```

Rates are capacity controls rather than contract, so no numbers are published
here and none should be inferred from what you observe. Retry reads; do not
blindly retry writes, since nothing on this API is idempotent — a replayed
feedback create is a second row, not a retried one.

## Conversations

A conversation is one exchange between your agent and one person: its
transcript, the tools that ran inside it, the files that moved through it, and
the feedback left on it.

### List conversations

<span class="api-method get">GET</span> `/api/conversations/` — *read role*

```bash
curl "https://api.agentsight.io/api/conversations/?full=false&page_size=2" \
  -H "Authorization: Api-Key ags_YOUR_KEY"
```

<details>
<summary><code>200 OK</code> — with <code>?full=false</code></summary>

```json
{
  "count": 539,
  "page_size": 2,
  "total_pages": 270,
  "current_page": 1,
  "next": "https://api.agentsight.io/api/conversations/?full=false&page=2&page_size=2",
  "previous": null,
  "results": [
    {
      "id": 737,
      "agent": 20,
      "conversation_id": "demo-envdefault-1786973547",
      "name": null,
      "customer_id": null,
      "customer_ip_address": null,
      "device": null,
      "language": null,
      "environment": "production",
      "environment_id": 39,
      "metadata": null,
      "started_at": "2026-08-17T13:32:32.985597Z",
      "ended_at": "2026-08-17T13:32:32.985700Z",
      "message_count": 2,
      "feedback_count": 0,
      "is_marked": false,
      "is_used": true,
      "is_deleted": false,
      "deleted_at": null,
      "geo_location": null
    },
    {
      "id": 736,
      "agent": 20,
      "conversation_id": "demo-dev-metadata-956f",
      "name": "Dev-environment metadata demo",
      "customer_id": "staging.tester",
      "customer_ip_address": null,
      "device": "desktop",
      "language": "en",
      "environment": "development",
      "environment_id": 40,
      "metadata": {
        "build": "c9c304e",
        "region": "eu-central",
        "checked": true
      },
      "started_at": "2026-08-17T10:32:35.442274Z",
      "ended_at": "2026-08-17T10:32:35.443243Z",
      "message_count": 2,
      "feedback_count": 0,
      "is_marked": false,
      "is_used": true,
      "is_deleted": false,
      "deleted_at": null,
      "geo_location": null
    }
  ]
}
```

</details>

:::warning `?full=false` is not the default, and you almost always want it
Without `?full=`, this endpoint sends an API key **the entire transcript of
every row it returns** — messages, their attachments, their action logs, their
button clicks, plus feedback and geolocation. At a hundred rows a page over a
busy agent that is hundreds of megabytes to answer "which conversations were
marked".

`?full=false` gives you the lean row shape above: the labels,
`message_count`, `feedback_count`, and nothing you did not ask for. Pass it on
every list request that is not specifically exporting transcripts.

The default is what it is because changing it would break silently — no error,
just `messages` gone from the response — for integrations we cannot see. The
[Python client](/api/conversations) sends `full=false` on every list path for
you and offers `list_full()` as the named opt-in.
:::

#### Filters

| Filter | Selects on |
|---|---|
| `conversation_id` | the exact business id you passed to `agentsight.conversation(...)` |
| `customer_id` | exact match |
| `customer_id__icontains` | part of it, case-insensitive |
| `customer_ip_address` | the recorded IP, exactly |
| `name` | part of the display name, case-insensitive |
| `device`, `language` | what was recorded about the conversation |
| `environment` (or `env`) | `production`, `development`, `prod` or `dev` |
| `is_marked` | flagged conversations |
| `include_deleted` | include soft-deleted rows — see [Deleting](#deleting-is-soft) |
| `include_tickets` | **narrows to conversations with at least one ticket, and puts each row's tickets on the payload in full** — see the warning below |
| `has_messages` | conversations that recorded any message |
| `has_action` | conversations in which any tool or task ran |
| `action_name` | conversations in which a *named* tool or task ran |
| `has_feedback` | conversations with feedback on them |
| `feedback_sentiment` | `positive`, `neutral` or `negative` |
| `message_contains` | text inside the transcript |
| `search` | name, business id, customer id and message content at once |
| `metadata` | `key:value` pairs, comma-separated — see below |
| `metadata_key` + `metadata_value` | one key, spelled out as two parameters |
| `started_at_after`, `started_at_before` | when it began |
| `ordering` | `started_at`, `ended_at`, `id`, `customer_id`, `is_marked`, `language` |

:::warning `include_tickets=true` filters as well as includes
It does two things at once: each returned conversation carries its `tickets`
(title, status, priority, tags, timestamps and the full discussion thread
under `comments`), **and the result set drops every conversation that has no
ticket** — with no error. An agent with a thousand conversations and three
ticketed ones answers with three rows, and the envelope's `count` is that
ticketed count. Do not add it "just to see tickets" on a listing you expect to
stay complete.

The accepted spellings are `1`/`true`/`yes`/`on` and `0`/`false`/`no`/`off`;
anything else — the empty string included — answers `400` naming the
parameter, rather than silently ignoring what you asked for. On
[Get one conversation](#get-one-conversation) the parameter is accepted and
ignored: detail carries tickets unconditionally.
:::

Combining them narrows:

```bash
curl -G "https://api.agentsight.io/api/conversations/" \
  -H "Authorization: Api-Key ags_YOUR_KEY" \
  --data-urlencode "full=false" \
  --data-urlencode "environment=production" \
  --data-urlencode "feedback_sentiment=negative" \
  --data-urlencode "started_at_after=2026-08-01T00:00:00Z" \
  --data-urlencode "ordering=-started_at"
```

**Metadata filtering** takes `key:value`, comma-separated for several at once,
and dot notation for nested keys:

```
?metadata=plan:pro
?metadata=plan:pro,resolved:true
?metadata=analysis.room_name:kitchen
```

Values are typed as they look: `1` becomes a number, `true` a boolean, `null` a
null. `?metadata_key=plan&metadata_value=pro` is the same filter written as two
parameters, for the one nested key whose value contains a comma or a colon.

`environment` accepts only the four spellings named above on this route. That is
narrower than what the agent may actually own — usage and span filtering accept
any slug — and a slug outside the list is a `400` rather than an empty page:

```json
{ "environment": ["Select a valid choice. staging is not one of the available choices."] }
```

### Finding the numeric id

Every route below this one is keyed by the **integer primary key**, not by the
`conversation_id` your application knows. One filtered list request resolves it:

```bash
curl -G "https://api.agentsight.io/api/conversations/" \
  -H "Authorization: Api-Key ags_YOUR_KEY" \
  --data-urlencode "conversation_id=demo-order-tracking-956f" \
  --data-urlencode "full=false" \
  --data-urlencode "include_deleted=true" \
  --data-urlencode "page_size=1"
```

<details>
<summary><code>200 OK</code></summary>

```json
{
  "count": 1,
  "page_size": 1,
  "total_pages": 1,
  "current_page": 1,
  "next": null,
  "previous": null,
  "results": [
    {
      "id": 732,
      "conversation_id": "demo-order-tracking-956f",
      "name": "Order tracking — Maja K.",
      "…": "…"
    }
  ]
}
```

</details>

`results[0].id` is the number every detail and management route wants.
`include_deleted=true` is there on purpose: without it a soft-deleted
conversation cannot be named, which makes exactly the rows someone is trying to
inspect the ones they cannot reach.

Every row of every list already carries both ids, so if you are iterating a list
and then managing rows, you have the number already — no extra request.

### Get one conversation

<span class="api-method get">GET</span> `/api/conversations/{id}/` — *read role*

```bash
curl "https://api.agentsight.io/api/conversations/732/" \
  -H "Authorization: Api-Key ags_YOUR_KEY"
```

<details>
<summary><code>200 OK</code></summary>

```json
{
  "id": 732,
  "agent": 20,
  "conversation_id": "demo-order-tracking-956f",
  "name": "Order tracking — Maja K.",
  "customer_id": "maja.kovac",
  "customer_ip_address": null,
  "device": "mobile",
  "language": "hr",
  "environment": "production",
  "environment_id": 39,
  "metadata": {
    "plan": "pro",
    "channel": "chat-widget",
    "order_id": "A-1042",
    "resolved": true
  },
  "started_at": "2026-08-17T10:32:33.305953Z",
  "ended_at": "2026-08-17T10:32:33.478144Z",
  "is_marked": false,
  "is_used": true,
  "is_deleted": false,
  "deleted_at": null,
  "geo_location": null,
  "messages": [
    {
      "id": 10466,
      "conversation": 732,
      "timestamp": "2026-08-17T10:32:33.306017Z",
      "sender": "end_user",
      "content": "Hi! Where is my order A-1042?",
      "action_name": null,
      "metadata": { "locale": "hr-HR" },
      "attachments": [],
      "action_logs": [],
      "button": null
    },
    {
      "id": 10468,
      "conversation": 732,
      "timestamp": "2026-08-17T10:32:33.306091Z",
      "sender": "agent",
      "content": "Action lookup_order performed",
      "action_name": "lookup_order",
      "metadata": null,
      "attachments": [],
      "action_logs": [
        {
          "id": 3491,
          "action": 7,
          "message": 10468,
          "started_at": "2026-08-17T10:32:33.306091Z",
          "ended_at": "2026-08-17T10:32:33.456393Z",
          "duration_ms": 150.302,
          "tools_used": { "order_id": "A-1042" },
          "response": "{\"order_id\": \"A-1042\", \"status\": \"shipped\", \"carrier\": \"GLS\", \"eta\": \"tomorrow 13:00\"}",
          "error_message": "",
          "metadata": null
        }
      ],
      "button": null
    },
    {
      "id": 10467,
      "conversation": 732,
      "timestamp": "2026-08-17T10:32:33.476573Z",
      "sender": "agent",
      "content": "Order #A-1042 left our Zagreb warehouse this morning and is with the courier — expected delivery tomorrow before 13:00.",
      "action_name": null,
      "metadata": { "latency_ms": 170.639 },
      "attachments": [],
      "action_logs": [],
      "button": null
    }
  ],
  "feedbacks": [
    {
      "id": 1,
      "kind": "conversation",
      "agent": 20,
      "conversation": 732,
      "user": null,
      "environment": "production",
      "environment_id": 39,
      "sentiment": "positive",
      "category": null,
      "comment": "Quick and helpful, delivery moved as asked.",
      "created_at": "2026-08-17T10:32:38.050751Z"
    }
  ],
  "tickets": [
    {
      "id": 61,
      "title": "Courier ETA was wrong",
      "status": "open",
      "priority": "medium",
      "tags": ["delivery"],
      "created_at": "2026-08-18T09:12:04.118330Z",
      "updated_at": "2026-08-18T09:40:11.902514Z",
      "comments": [
        {
          "id": 204,
          "author": "Maja K.",
          "role": "reporter",
          "body": "The bot promised 13:00, parcel came at 18:30.",
          "created_at": "2026-08-18T09:12:04.120944Z"
        },
        {
          "id": 209,
          "author": "Dev team",
          "role": "dev",
          "body": "Carrier feed lag — switching to the live endpoint.",
          "created_at": "2026-08-18T09:40:11.900012Z"
        }
      ]
    }
  ],
  "token_usage": {
    "totals": {
      "prompt_tokens": 8210,
      "completion_tokens": 1650,
      "total_tokens": 9860
    },
    "cost_usd": "0.05242500",
    "cost_sources": ["backend"],
    "models": [
      {
        "model": "claude-sonnet-4-5",
        "cost_source": "backend",
        "cost_usd": "0.05242500",
        "prompt_tokens": 8210,
        "completion_tokens": 1650,
        "total_tokens": 9860
      }
    ]
  }
}
```

</details>

Messages arrive in timestamp order, each carrying its sender, content, any
metadata you recorded, and whichever of `attachments`, `action_logs` or `button`
belongs to it. `sender` is `end_user` or `agent`.

This route always returns the whole conversation — asking for one by id is the
case where you almost certainly want all of it, and `?full=` is a **list-only**
parameter that this route ignores. `tickets` and `token_usage` arrive
unconditionally for the same reason (and `?include_tickets=` is accepted and
ignored here).

`tickets` is every ticket filed against the conversation, discussion thread
included, newest ticket first, thread messages oldest first.

`token_usage` is `null` when nothing was recorded. `totals` names only the
token columns that are non-zero for this conversation (`total_tokens` always),
and `models` breaks the same columns down per model — tokens from different
models are not the same unit. Costs are decimal **strings**, and `cost_source`
is carried through rather than blended: `backend` means priced from the rate
card, `reported` means the SDK's own figure was used, and `unpriced` means no
price row matched — that zero is "we could not price this", never "this was
free". One `models` entry per model *and* pricing source, so a partially
repriced model shows both.

`geo_location` is `null` unless an IP was recorded and resolved.

### Attachments

<span class="api-method get">GET</span> `/api/conversations/{id}/attachments/` — *read role*

Every file on the conversation, with download URLs.

```bash
curl "https://api.agentsight.io/api/conversations/731/attachments/" \
  -H "Authorization: Api-Key ags_YOUR_KEY"
```

<details>
<summary><code>200 OK</code></summary>

```json
{
  "conversation_id": "demo-invoice-attachments-956f",
  "conversation": 731,
  "attachment_count": 2,
  "attachments": [
    {
      "id": 39,
      "message": 10465,
      "type": "text",
      "filename": "invoice-2026-081.txt",
      "mime_type": "text/plain",
      "size_bytes": 89,
      "file_url": "https://<storage-host>/731/d52a83cb8b774691b29d87b0de354d27.txt?token=<signature>&expires=1786995159&token_path=%2F731%2F"
    },
    {
      "id": 40,
      "message": 10465,
      "type": "image",
      "filename": "stamp.png",
      "mime_type": "image/png",
      "size_bytes": 70,
      "file_url": "https://<storage-host>/731/cfef62cf90de411f9b016ed041ad965a.png?token=<signature>&expires=1786995159&token_path=%2F731%2F"
    }
  ]
}
```

</details>

:::warning Download URLs expire after an hour
They are signed and short-lived, so fetch a file when you need it rather than
storing the link. A URL you saved yesterday will not work today — ask again, it
costs one request.
:::

### What metadata is in use

Three routes answer "what keys are even recorded here", which is what you need
before filtering on metadata over data you did not write yourself. All three are
*read role*, and all three cover the agent's recent history rather than only the
current page.

<span class="api-method get">GET</span> `/api/conversations/metadata-keys/`

```json
{ "keys": ["account", "build", "channel", "order_id", "plan", "region", "resolved"] }
```

<span class="api-method get">GET</span> `/api/conversations/metadata-values/?key=plan`

```json
{ "key": "plan", "values": ["enterprise", "pro"] }
```

<span class="api-method get">GET</span> `/api/conversations/message-metadata-keys/`

```json
{ "keys": ["completion_tokens", "embedding_tokens", "latency_ms", "locale", "prompt_tokens", "total_tokens"] }
```

Nested keys appear as dot paths (`analysis.room_name`), which is the same
spelling the `metadata` filter takes. Both lists are capped at 200 entries.

### Mark

<span class="api-method post">POST</span> `/api/conversations/{id}/mark/` — *write role*

The flag your dashboard filters on.

```bash
curl -X POST "https://api.agentsight.io/api/conversations/738/mark/" \
  -H "Authorization: Api-Key ags_YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{"is_marked": true}'
```

```json
{ "id": 738, "conversation_id": "demo-delete-1786992718", "is_marked": true }
```

`is_marked` is required — omitting it is a `400`:

```json
{ "detail": "Missing field 'is_marked'." }
```

### Rename

<span class="api-method patch">PATCH</span> `/api/conversations/{id}/rename/` — *write role*

```bash
curl -X PATCH "https://api.agentsight.io/api/conversations/738/rename/" \
  -H "Authorization: Api-Key ags_YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{"name": "Order tracking — resolved"}'
```

```json
{
  "id": 738,
  "conversation_id": "demo-delete-1786992718",
  "name": "Order tracking — resolved"
}
```

A name is a display label: up to 255 characters, trimmed of surrounding
whitespace, and not allowed to be empty.

```json
{ "detail": "Field 'name' cannot be empty." }
```

### Update several fields

<span class="api-method patch">PATCH</span> `/api/conversations/{id}/update/` — *write role*

| Field | Type |
|---|---|
| `name` | string, max 255 |
| `is_marked` | boolean |
| `customer_id` | string |
| `device` | string |
| `language` | string |
| `metadata` | object |

All optional; send only what you are changing. Everything else is immutable —
the business `conversation_id`, its start time and the agent it belongs to are
what make it that conversation.

```bash
curl -X PATCH "https://api.agentsight.io/api/conversations/738/update/" \
  -H "Authorization: Api-Key ags_YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "customer_id": "user-456",
    "device": "mobile",
    "language": "en",
    "metadata": {"plan": "enterprise", "order_id": "A-1042"}
  }'
```

<details>
<summary><code>200 OK</code></summary>

```json
{
  "id": 738,
  "conversation_id": "demo-delete-1786992718",
  "updated_fields": ["customer_id", "device", "language", "metadata"],
  "customer_id": "user-456",
  "device": "mobile",
  "language": "en",
  "metadata": { "plan": "enterprise", "order_id": "A-1042" }
}
```

</details>

:::warning `metadata` replaces the whole document
Keys you leave out are gone, not preserved. There is no merge and no
partial-update form of this field, so read the conversation, merge locally, and
write the result back — or use
[`update_metadata()`](/api/conversations#changing-metadata-without-replacing-it)
in the Python client, which does exactly that for you.

Note the read-modify-write is not atomic on either path. Two callers merging
into the same conversation at the same moment can lose one of the two updates.
:::

:::info A conversation still open in a tracking process will overwrite you
Every field here except `is_marked` also rides on every span the conversation
emits. If the conversation is *still open* inside a live
`agentsight.conversation(...)` scope somewhere, its next span carries the old
value and writes it straight back over what you just changed.

There is nothing this API can do about that from the outside. Either update
after the conversation has ended, or use the Python client, which pushes the new
value into a live scope in its own process.
:::

### Deleting is soft

<span class="api-method delete">DELETE</span> `/api/conversations/{id}/delete/` — *write role*

```bash
curl -X DELETE "https://api.agentsight.io/api/conversations/738/delete/" \
  -H "Authorization: Api-Key ags_YOUR_KEY"
```

```json
{
  "id": 738,
  "conversation_id": "demo-delete-1786992718",
  "is_deleted": true,
  "deleted_at": "2026-08-17T18:54:08.915891Z"
}
```

The row survives, flagged and hidden from listings. It is still readable the
moment you name it:

```
GET /api/conversations/?conversation_id=…                       → count: 0
GET /api/conversations/?conversation_id=…&include_deleted=true  → count: 1
GET /api/conversations/738/                                     → 200, whole transcript
```

**Nothing on this API destroys a conversation.** Not this route, and not the
plain `DELETE /api/conversations/{id}/` either — that one performs the same soft
delete. It is a decision rather than a missing feature: people delete a
conversation to stop seeing it, not to destroy it, and a destructive call
reachable by an integration is a hazard no convenience justifies. A hard delete
would take the messages, attachments, action logs, spans and token usage with
it, unrecoverably.

There is also **no undelete route**. Permanent removal, and reversal, are
operator actions. If you need either, ask.

## Feedbacks

Feedback is the one thing on this API you can create, and the exception proves
the rule elsewhere. Everything else is telemetry — things that happened, which
the SDK watched happen. Nothing about a run of your agent reveals whether the
person on the other end was satisfied with it. Somebody has to say so, and the
moment they say it is a click in your application, not an event any SDK could
observe.

Two kinds are reachable with an API key: **conversation** feedback (how one
conversation went) and **agent** feedback (how the agent is doing overall,
optionally scoped to an environment).

### List feedback

<span class="api-method get">GET</span> `/api/feedbacks/` — *read role*

```bash
curl "https://api.agentsight.io/api/feedbacks/?sentiment=negative" \
  -H "Authorization: Api-Key ags_YOUR_KEY"
```

<details>
<summary><code>200 OK</code></summary>

```json
{
  "count": 3,
  "page_size": 15,
  "total_pages": 1,
  "current_page": 1,
  "next": null,
  "previous": null,
  "results": [
    {
      "id": 3,
      "kind": "conversation",
      "agent": 20,
      "conversation": 733,
      "conversation_id": "demo-rag-search-956f",
      "user": null,
      "environment": "production",
      "environment_id": 39,
      "sentiment": "neutral",
      "category": null,
      "comment": "Answer was right but a bit terse.",
      "created_at": "2026-08-17T10:32:38.247146Z"
    }
  ],
  "counts": { "all": 3 }
}
```

</details>

Newest first. The envelope carries one extra key, `counts`, which holds how many
rows match the filters — the same number as `count`, and kept only because the
envelope publishes it.

| Filter | Selects on |
|---|---|
| `kind` | `conversation` or `agent` |
| `sentiment` | `positive`, `neutral` or `negative` |
| `conversation` | one conversation, by numeric id |
| `conversation_id` | one conversation, by business id |
| `agent`, `user` | who it is about, and who left it |
| `category` | the server-side category, where one is set |
| `environment` (or `env`) | `production`, `development`, `prod` or `dev` |
| `has_comment` | rows with free text, or rows without |
| `comment_contains` | text inside the comment |
| `created_at_after`, `created_at_before` | when it was left |
| `search` | across the searchable fields |
| `ordering` | `created_at`, `id`, `kind`, `sentiment`, `category` |

To go the other way — conversations that *have* feedback, rather than the
feedback itself — filter conversations on `has_feedback` or
`feedback_sentiment`.

:::info Tickets are not on this surface
`has_ticket` and `ticket_status` are refused rather than ignored:

```json
{ "has_ticket": "Tickets are not available on the API-key plane." }
```

Feedback payloads carry no nested ticket object, and `counts` holds `all` and
nothing else. Tickets are internal workflow state; that is a boundary drawn on
purpose, not a field that has yet to be added.
:::

### Get one

<span class="api-method get">GET</span> `/api/feedbacks/{id}/` — *read role*

Returns a single row in the shape above.

### Create feedback on a conversation

<span class="api-method post">POST</span> `/api/feedbacks/` — *write role*

```bash
curl -X POST "https://api.agentsight.io/api/feedbacks/" \
  -H "Authorization: Api-Key ags_YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "kind": "conversation",
    "conversation_id": "demo-order-tracking-956f",
    "sentiment": "positive",
    "comment": "Fast and clear."
  }'
```

<details>
<summary><code>201 Created</code></summary>

```json
{
  "id": 4,
  "kind": "conversation",
  "agent": 20,
  "conversation": 738,
  "conversation_id": "demo-delete-1786992718",
  "user": null,
  "environment": "development",
  "environment_id": 40,
  "sentiment": "positive",
  "category": null,
  "comment": "Fast and clear.",
  "created_at": "2026-08-17T18:52:44.956984Z"
}
```

</details>

| Field | Required | Notes |
|---|---|---|
| `kind` | yes | `"conversation"` |
| `conversation_id` | either | the business id — resolved for you, no lookup needed |
| `conversation` | either | or the numeric id, if you have it |
| `sentiment` | yes | `positive`, `neutral` or `negative` |
| `comment` | no | free text |

The environment is **derived from the conversation** and cannot be supplied:

```json
{ "environment": ["Derived from the conversation."] }
```

### Create feedback on the agent

<span class="api-method post">POST</span> `/api/feedbacks/` — *write role*

```bash
curl -X POST "https://api.agentsight.io/api/feedbacks/" \
  -H "Authorization: Api-Key ags_YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "kind": "agent",
    "agent": 20,
    "sentiment": "negative",
    "comment": "Slow at peak hours.",
    "environment": "production"
  }'
```

<details>
<summary><code>201 Created</code></summary>

```json
{
  "id": 5,
  "kind": "agent",
  "agent": 20,
  "conversation": null,
  "conversation_id": null,
  "user": null,
  "environment": "production",
  "environment_id": 39,
  "sentiment": "negative",
  "category": null,
  "comment": "Slow at peak hours.",
  "created_at": "2026-08-17T18:52:46.379106Z"
}
```

</details>

`agent` is your key's own agent id, which [`/api/me/`](#who-this-key-is)
reports. `environment` is accepted on this kind only, and takes any slug the
agent has.

An invalid sentiment is a `400` on either kind:

```json
{ "sentiment": ["\"meh\" is not a valid choice."] }
```

There is a third kind, `product`, which is not on this plane. Naming it —
`?kind=product` on the list, or `"kind": "product"` in a payload — answers
`403`. A product row reached by id is a `404` like any other row this key
cannot see.

### Update

<span class="api-method patch">PATCH</span> `/api/feedbacks/{id}/` — *write role*

`sentiment` and `comment` are the changeable fields — plus `environment`, on
agent-kind feedback only.

```bash
curl -X PATCH "https://api.agentsight.io/api/feedbacks/4/" \
  -H "Authorization: Api-Key ags_YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{"sentiment": "neutral", "comment": "Resolved on the second attempt."}'
```

Returns the whole updated row.

### Delete

<span class="api-method delete">DELETE</span> `/api/feedbacks/{id}/` — *write role*

```bash
curl -X DELETE "https://api.agentsight.io/api/feedbacks/4/" \
  -H "Authorization: Api-Key ags_YOUR_KEY"
```

`204 No Content`, and it is gone — unlike a conversation, feedback deletes for
real. It is a statement somebody made, and withdrawing it means withdrawn rather
than hidden. Asking for it afterwards is a `404`.

## Actions

An action is a **definition, not an event** — `lookup_order` the capability,
rather than the eleven times it ran this morning. The tracking SDK creates them
as it goes: the first `@tool` or `@task` span carrying a name brings that action
into being. You can also declare one here, ahead of its first run.

Deleting one is not part of this contract, on any plane. Every recorded
invocation hangs off the definition, so a delete would take that history with
it; `DELETE /api/actions/{id}/` answers `405`.

### List and get

<span class="api-method get">GET</span> `/api/actions/` — *read role*
<span class="api-method get">GET</span> `/api/actions/{id}/` — *read role*

```bash
curl "https://api.agentsight.io/api/actions/?name__icontains=order" \
  -H "Authorization: Api-Key ags_YOUR_KEY"
```

```json
{
  "id": 7,
  "name": "lookup_order",
  "display_name": "lookup_order",
  "description": "",
  "agent": 20
}
```

| Filter | Selects on |
|---|---|
| `name` | the exact name the SDK recorded |
| `name__icontains` | part of that name |
| `display_name` | part of the dashboard label |
| `search` | across name, display name and description |
| `ordering` | `name`, `display_name`, `id` |

### Declare an action

<span class="api-method post">POST</span> `/api/actions/` — *write role*

For a capability you want visible in analytics before — or without — anything
ever performing it.

```bash
curl -X POST "https://api.agentsight.io/api/actions/" \
  -H "Authorization: Api-Key ags_YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "lookup_order",
    "display_name": "Look up an order",
    "description": "Fetches recent orders by customer id."
  }'
```

```json
{
  "id": 7,
  "name": "lookup_order",
  "display_name": "Look up an order",
  "description": "Fetches recent orders by customer id.",
  "agent": 20
}
```

| Field | Required | Notes |
|---|---|---|
| `name` | yes | the name spans are matched on — use the one your `@tool` will carry |
| `display_name` | no | defaults to `name`, exactly as tracking defaults it |
| `description` | no | free text |

The agent comes from your key and is not part of the payload.

:::info The first real invocation adopts this row
Tracking resolves an action by its name, so the first `@tool` or `@task` span
carrying `lookup_order` attaches to the action you declared rather than creating
a second one beside it — and it leaves your `display_name` and `description`
alone. Declare it, ship the tool, and there is still exactly one action.
:::

A name this agent already has answers `400`:

```json
{ "name": ["An action named \"lookup_order\" already exists for this agent."] }
```

It is refused rather than returned, so a client cannot mistake somebody else's
row for the one it just made. Uniqueness is **per agent**: the same name is
accepted for a different agent of yours, and that is the normal case.

### Invocations

<span class="api-method get">GET</span> `/api/actions/{id}/logs/` — *read role*

Every recorded run of one action.

```bash
curl "https://api.agentsight.io/api/actions/7/logs/" \
  -H "Authorization: Api-Key ags_YOUR_KEY"
```

<details>
<summary><code>200 OK</code></summary>

```json
[
  {
    "id": 3491,
    "action": 7,
    "message": 10468,
    "started_at": "2026-08-17T10:32:33.306091Z",
    "ended_at": "2026-08-17T10:32:33.456393Z",
    "duration_ms": 150.302,
    "tools_used": { "order_id": "A-1042" },
    "response": "{\"order_id\": \"A-1042\", \"status\": \"shipped\", \"carrier\": \"GLS\", \"eta\": \"tomorrow 13:00\"}",
    "error_message": "",
    "metadata": null
  }
]
```

</details>

:::warning This one returns a bare array
No envelope, no `count`, no paging — the whole list at once. It is the one read
on this page that does not paginate, so treat a very chatty action with care.
:::

`duration_ms` is measured elapsed time, `tools_used` holds the arguments the
call received, and `error_message` is empty on success.

### Label an action

<span class="api-method patch">PATCH</span> `/api/actions/{id}/` — *write role*

`display_name` and `description` decide how an action reads on the dashboard,
and a span carries neither. This is the only place they can be set.

```bash
curl -X PATCH "https://api.agentsight.io/api/actions/7/" \
  -H "Authorization: Api-Key ags_YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{"display_name": "Search orders", "description": "Looks up a customer'\''s recent orders by id."}'
```

```json
{
  "id": 7,
  "name": "lookup_order",
  "display_name": "Search orders",
  "description": "Looks up a customer's recent orders by id.",
  "agent": 20
}
```

`name` is changeable too, and rarely should be — it is the name incoming spans
are matched against, so renaming it means the next span carrying the old name
creates a second action beside this one. Change the display name instead; that
is what it is for.

## Usage

What your models cost. Read-only — rows are written from the token counts each
provider reports and priced server-side.

### Per-turn rows

<span class="api-method get">GET</span> `/api/token-usage/` — *read role*

```bash
curl "https://api.agentsight.io/api/token-usage/?conversation_id=demo-dev-metadata-956f" \
  -H "Authorization: Api-Key ags_YOUR_KEY"
```

<details>
<summary><code>200 OK</code></summary>

```json
{
  "count": 1,
  "page_size": 15,
  "total_pages": 1,
  "current_page": 1,
  "next": null,
  "previous": null,
  "results": [
    {
      "id": 3474,
      "conversation": 736,
      "conversation_id": "demo-dev-metadata-956f",
      "environment": "development",
      "turn_id": "bd5920c169e03fd9",
      "model": "gpt-4o-mini",
      "prompt_tokens": 142,
      "completion_tokens": 58,
      "embedding_tokens": 0,
      "cache_read_tokens": 0,
      "cache_write_tokens": 0,
      "reasoning_tokens": 0,
      "audio_input_tokens": 0,
      "audio_output_tokens": 0,
      "total_tokens": 200,
      "cost_usd": "0.00005610",
      "cost_usd_reported": "0.00000000",
      "cost_source": "backend",
      "calls": 1,
      "unreported_calls": 0,
      "incomplete": false,
      "incomplete_reason": null,
      "started_at": "2026-08-17T10:32:35.442274Z",
      "ended_at": "2026-08-17T10:32:35.443252Z"
    }
  ]
}
```

</details>

One row per **turn and model** — not per LLM call. A turn's calls are aggregated
by the model that served them, because counts from two models are not the same
unit and a row summing them could never be priced. `calls` says how many went
into the row.

| Filter | Selects on |
|---|---|
| `model` | the resolved model id |
| `conversation` | one conversation, by numeric id |
| `conversation_id` | one conversation, by business id |
| `turn_id` | one exchange |
| `environment` | **any slug the agent has** — and it is spelled `environment`, never `env` |
| `cost_source` | `backend`, `unpriced` or `reported` |
| `incomplete` | turns that did not finish |
| `started_at_after`, `started_at_before` | when the spend happened |
| `ordering` | `started_at`, `ended_at`, `total_tokens`, `cost_usd`, `id` |

:::warning Costs are strings here
`cost_usd` and `cost_usd_reported` arrive as decimal strings — `"0.00005610"` —
so the stored precision survives rather than being rounded through a float.
Parse them as decimals, not as floats, before summing.
:::

#### What `cost_source` tells you

| Value | Meaning |
|---|---|
| `backend` | priced server-side. The number of record |
| `unpriced` | no rate matched this model, so nothing was booked |
| `reported` | a figure a client sent itself, kept rather than booked as zero |

**`unpriced` is not free.** It reads as "we do not know", and it is recoverable:
the token counts are exact, so the row is restated the day a rate for that model
exists.

```json
{
  "id": 3469,
  "conversation_id": "demo-failure-retry-956f",
  "model": "gpt-does-not-exist",
  "total_tokens": 0,
  "cost_usd": "0.00000000",
  "cost_source": "unpriced",
  "calls": 1,
  "…": "…"
}
```

Pricing happens on our side because rates change and published rates are
sometimes wrong. Server-side pricing keeps every caller on one rate table, and
lets a rate that turns out to have been wrong be restated across history.

#### Two fields that look alike and are not

**`incomplete` is about the turn.** True when the exchange ended in an error,
was abandoned mid-stream, hit its deadline or was cut off by shutdown;
`incomplete_reason` says which. That spend was really spent — what is missing is
the rest of the exchange.

**`unreported_calls` is about the tokens.** It counts calls whose stream closed
without the provider ever reporting usage. Those contributed `0` to every token
column as an *unknown*, not a zero. A row with `unreported_calls > 0`
understates both tokens and cost, and no filter selects on it — read it and
decide.

### The rollup

<span class="api-method get">GET</span> `/api/token-usage/summary/` — *read role*

The "what did last month cost me" call. Biggest first.

```bash
curl "https://api.agentsight.io/api/token-usage/summary/?group_by=model" \
  -H "Authorization: Api-Key ags_YOUR_KEY"
```

<details>
<summary><code>200 OK</code></summary>

```json
{
  "group_by": "model",
  "currency": "USD",
  "results": [
    {
      "group": "gpt-4o-mini-2024-07-18",
      "calls": 2591,
      "rows": 2591,
      "prompt_tokens": 207360,
      "completion_tokens": 116585,
      "embedding_tokens": 0,
      "cache_read_tokens": 103560,
      "cache_write_tokens": 0,
      "total_tokens": 427505,
      "cost_usd": 0.108822
    },
    {
      "group": "us.anthropic.claude-sonnet-4-5-20250929-v1:0",
      "calls": 3,
      "rows": 3,
      "prompt_tokens": 360,
      "completion_tokens": 120,
      "embedding_tokens": 0,
      "cache_read_tokens": 0,
      "cache_write_tokens": 0,
      "total_tokens": 480,
      "cost_usd": 0.00288
    }
  ]
}
```

</details>

| Parameter | Default | Accepts |
|---|---|---|
| `group_by` | `model` | `model`, `conversation`, `day` |
| `currency` | `USD` | `usd`, `eur` |

It takes **every filter the row list does**, applied identically — a summary can
never cover rows the matching list would not have shown. It is not paginated; a
rollup is already aggregated.

`group` is the model id, the conversation's **numeric** id, or an ISO date,
depending on `group_by`. Costs here are **numbers**, not strings, because these
ones are computed rather than stored.

An unrecognised `group_by` is a `400`:

```json
{ "group_by": "Must be one of: model, conversation, day." }
```

:::warning `cost_eur` is absent, not zero
Where no exchange rate is on file, the converted key is **missing from the row
entirely** — because a missing rate is an unknown, and a free month is a very
different claim. Read it defensively and treat absence as "not converted", never
as "nothing spent".

`cost_usd` is always present and is the stored truth. Conversion happens at read
time, which is what lets a corrected rate restate history instead of needing a
backfill.
:::

## Spans and traces

Conversations, messages, action logs and usage rows are **projections**. This is
the archive they are projected from: the OpenTelemetry spans the SDK sent, as
stored. Read-only, and the place to look when something rendered in a way you
did not expect.

What spans hold that the projections deliberately drop: exact parent and child
structure, per-call durations and status, tool arguments and responses,
OpenTelemetry resource and scope attributes, and any attribute a newer SDK emits
that has no projection rule yet.

### List spans

<span class="api-method get">GET</span> `/api/spans/` — *read role*

```bash
curl "https://api.agentsight.io/api/spans/?conversation_id=demo-order-tracking-956f&kind=tool" \
  -H "Authorization: Api-Key ags_YOUR_KEY"
```

<details>
<summary><code>200 OK</code></summary>

```json
{
  "count": 1,
  "page_size": 15,
  "total_pages": 1,
  "current_page": 1,
  "next": null,
  "previous": null,
  "results": [
    {
      "id": 10425,
      "conversation": 732,
      "conversation_id": "demo-order-tracking-956f",
      "trace_id": "e54e3abfd172fc283267cbe895446819",
      "span_id": "4a79af0ea4efae79",
      "parent_span_id": "99ea4e95909e189c",
      "kind": "tool",
      "name": "lookup_order",
      "started_at": "2026-08-17T10:32:33.306091Z",
      "ended_at": "2026-08-17T10:32:33.456393Z",
      "duration_ms": 150.302,
      "status": "ok",
      "attributes": {
        "agentsight.span.kind": "tool",
        "agentsight.turn.id": "99ea4e95909e189c",
        "agentsight.tool.name": "lookup_order",
        "agentsight.entity.name": "lookup_order",
        "agentsight.tool.arguments": "{\"order_id\": \"A-1042\"}",
        "agentsight.tool.response": "{\"order_id\": \"A-1042\", \"status\": \"shipped\", \"carrier\": \"GLS\", \"eta\": \"tomorrow 13:00\"}",
        "agentsight.conversation.id": "demo-order-tracking-956f",
        "agentsight.conversation.name": "Order tracking — Maja K.",
        "agentsight.conversation.device": "mobile",
        "agentsight.conversation.language": "hr",
        "agentsight.conversation.customer_id": "maja.kovac"
      },
      "events": []
    }
  ]
}
```

</details>

Newest first. `attributes` and `events` are the substance — tool arguments and
responses, message content, token counts — and they are on every row.
[What the SDK sends](/getting-started/what-the-sdk-sends) documents every
attribute that can appear.

| Filter | Selects on |
|---|---|
| `kind` | `turn`, `llm`, `tool`, `task`, `button`, `attachment`, `conversation` |
| `status` | `ok`, `error`, `unset` |
| `name` | the span's name, **exactly** — there is no substring match here |
| `conversation` | one conversation, by numeric id |
| `conversation_id` | one conversation, by business id |
| `trace_id` | one trace, flat |
| `span_id`, `parent_span_id` | one span, or one span's children |
| `environment` | any slug the agent has — spelled `environment`, never `env` |
| `started_at_after`, `started_at_before` | when it ran |
| `ordering` | `started_at`, `ended_at`, `duration_ms`, `id` |

The set is small on purpose: every filter offered is one the store can serve
efficiently — which is why
there is no substring search on `name` and no way to filter inside `attributes`.
`kind` is not validated: a newer SDK may send a kind this list has never heard
of, and it is stored rather than rejected.

:::warning Rows never carry the verbatim span
`payload` is the largest field a span has, and it repeats `attributes` and
`events` inside itself — a page of them would be most of a stored archive. It is
available one span at a time, and only when you ask.

This is also the one list on this page with no way to ask for everything at
once. Page through it.
:::

### One span, with everything

<span class="api-method get">GET</span> `/api/spans/{id}/?payload=true` — *read role*

`{id}` is the `id` from a list row, **not** the `span_id` — that one is the
OpenTelemetry identifier and is only unique within a conversation.

```bash
curl "https://api.agentsight.io/api/spans/10425/?payload=true" \
  -H "Authorization: Api-Key ags_YOUR_KEY"
```

<details>
<summary><code>200 OK</code> — the <code>payload</code> key, abridged</summary>

```json
{
  "id": 10425,
  "kind": "tool",
  "name": "lookup_order",
  "…": "…",
  "payload": {
    "kind": "tool",
    "name": "lookup_order",
    "span_id": "4a79af0ea4efae79",
    "trace_id": "e54e3abfd172fc283267cbe895446819",
    "parent_span_id": "99ea4e95909e189c",
    "started_at": "2026-08-17T10:32:33.306091+00:00",
    "ended_at": "2026-08-17T10:32:33.456393+00:00",
    "duration_ms": 150.302,
    "status": "ok",
    "attributes": { "…": "…" },
    "events": [],
    "otel": {
      "span_kind": "INTERNAL",
      "is_remote": false,
      "trace_flags": 3,
      "trace_state": null,
      "status_description": null,
      "links": [],
      "dropped": { "links": 0, "events": 0, "attributes": 0 },
      "scope": { "name": "agentsight", "version": "0.1.0", "schema_url": "" },
      "resource": {
        "service.name": "agentsight-python",
        "service.instance.id": "e5b9a874-fcea-402c-a313-b7769d046fda",
        "telemetry.sdk.name": "agentsight-python",
        "telemetry.sdk.version": "0.1.0",
        "telemetry.sdk.language": "python"
      }
    }
  }
}
```

</details>

`payload` is the span exactly as it arrived — resource attributes,
instrumentation scope, links, trace flags and state, the status description and
dropped-record counts. Nothing was discarded on the way in.

Without `?payload=true` this route returns the same row shape the list returns.
The parameter has no default that turns it on: the expensive shape should never
be something a caller arrives at by accident.

### One trace, as a tree

<span class="api-method get">GET</span> `/api/traces/{trace_id}/` — *read role*

The same spans `?trace_id=` lists, arranged the way they happened.

```bash
curl "https://api.agentsight.io/api/traces/e54e3abfd172fc283267cbe895446819/" \
  -H "Authorization: Api-Key ags_YOUR_KEY"
```

<details>
<summary><code>200 OK</code> — abridged to structure</summary>

```json
{
  "trace_id": "e54e3abfd172fc283267cbe895446819",
  "span_count": 3,
  "truncated": false,
  "roots": [
    {
      "id": 10424,
      "kind": "turn",
      "name": "where-is-my-order",
      "span_id": "99ea4e95909e189c",
      "parent_span_id": null,
      "duration_ms": 170.639,
      "status": "ok",
      "attributes": { "…": "…" },
      "events": [],
      "children": [
        {
          "id": 10425,
          "kind": "tool",
          "name": "lookup_order",
          "span_id": "4a79af0ea4efae79",
          "parent_span_id": "99ea4e95909e189c",
          "duration_ms": 150.302,
          "status": "ok",
          "children": []
        },
        {
          "id": 10426,
          "kind": "llm",
          "name": "gpt-4o-mini",
          "span_id": "8c1b2bbfd82c8df3",
          "parent_span_id": "99ea4e95909e189c",
          "duration_ms": 19.844,
          "status": "unset",
          "children": []
        }
      ]
    }
  ]
}
```

</details>

```
turn  where-is-my-order   170.639
  tool  lookup_order      150.302
  llm   gpt-4o-mini        19.844
```

That is the shape to reach for when the question is "what happened inside this
turn" rather than "find me the spans that look like X" — and the answer above
took one request: the tool call is where the time went, not the model.

Each node is a span row plus a `children` list, nested to whatever depth your
agent produced, and never carrying `payload`. A span whose parent is not in the
trace appears as a root rather than being dropped, so `span_count` always equals
the number of nodes in the tree. Not paginated.

:::info `truncated` means spans are missing, not that the trace ended
It is `true` when the trace was larger than one response assembles and the tail
was cut. Page through `/api/spans/?trace_id=…` if you need all of them.
:::

### What spans are good for

**Button clicks**, which have no projection of their own yet:

```
GET /api/spans/?kind=button
```

```json
{
  "agentsight.button.event": "click",
  "agentsight.button.label": "Reschedule delivery",
  "agentsight.button.value": "reschedule"
}
```

**Turns that never finished**, which never reach a transcript by design and are
recorded anyway:

```
GET /api/spans/?kind=turn&status=error
```

```json
{
  "agentsight.turn.complete": false,
  "agentsight.turn.incomplete_reason": "abandoned"
}
```

`incomplete_reason` is `error`, `abandoned`, `deadline` or `shutdown`.

**A tool call whose output looks wrong**, with the arguments it actually
received and the response it actually returned rather than a summary of them —
`agentsight.tool.arguments` and `agentsight.tool.response`, above.

## Not on this surface

Some things are reachable neither by this page nor by any API key, and each
absence is a decision:

| | Why |
|---|---|
| **Recording data** | The [tracking SDK](/getting-started/quick-start) is the only way in. One writer means one set of semantics for how a row reaches your dashboards. Declaring an [action](#actions) is not an exception — that is a definition, not a record of a run. |
| **Tickets** | Internal workflow state. No routes, no nested objects, and the ticket filters are refused rather than ignored. |
| **Buttons** | Recorded completely, but nothing projects them into a readable table yet — a list here would answer "no clicks" to everyone. Read them as [spans](#what-spans-are-good-for). |
| **Message and action-log writes** | Same rule as recording: they belong to the SDK. |
| **Admin and dashboard routes** | Session-authenticated, and not part of any integration contract. |

## Next

- [The API client](/api/) — this surface in Python, with paging, retries and
  typed errors handled
- [What the SDK sends](/getting-started/what-the-sdk-sends) — every attribute
  the spans on this page can carry, and what is never sent
- [Quickstart](/getting-started/quick-start) — the other half of the story: how
  this data comes into being
