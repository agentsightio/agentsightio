# The import file contract

What the file has to look like, and what each field costs you if you get it
wrong. Everything here is the *shape* of the contract; **every number lives in
the served `/api/imports/limits/` document and none of them are written down
in this file.** Fetch that document in step 1 and read the caps off it. A cap
restated in prose is a cap that drifts, and the failure it produces is a file
the user waits through an upload to have rejected.

The authority is `GET /api/imports/schema/` — a JSON Schema (draft 2020-12)
that the dashboard, the server and the shipped validator all compile from.
This file explains it; it does not replace it.

## Contents

- [The file](#the-file)
- [Each conversation](#each-conversation)
- [Each message](#each-message)
- [Senders](#senders)
- [Timestamps](#timestamps)
- [Metadata](#metadata)
- [What an import does not carry](#what-an-import-does-not-carry)
- [Dedup, undo, and the environment](#dedup-undo-and-the-environment)
- [The rules JSON Schema cannot express](#the-rules-json-schema-cannot-express)

## The file

One JSON object, two keys:

```json
{
  "schema_version": 1,
  "conversations": [ ... ]
}
```

`schema_version` is the integer the served limits document reports as
`schema_version` — the literal `1` in a string (`"1"`) is a rejection, not a
coercion. `conversations` is a non-empty array. There is a cap on its length
(`max_conversations_per_run`) and an advisory cap on the file's byte size
(`max_import_file_bytes`) that the browser enforces before anything is sent;
past either, the history is split across several uploads.

Nothing else belongs at the top level. Extra keys are ignored by the upload
path rather than rejected, but the schema forbids them and they mean the
exporter is writing something nobody reads.

## Each conversation

Required: `conversation_id`, `started_at`, `messages`.

| Field | Notes |
|---|---|
| `conversation_id` | string, non-empty, capped at `max_conversation_id_length` in the schema. **This is the dedup key** — see below |
| `started_at` | ISO 8601 with an explicit offset. When the conversation began, not when you exported it |
| `messages` | array, at least one, capped at `max_messages_per_conversation` |
| `name` | optional string or `null` — a human label for the thread |
| `customer_id` | optional string or `null` — the end user's id in the source system |
| `language` | optional string or `null` |
| `device` | optional string or `null` |
| `metadata` | optional object or `null` |

The four optional text fields share one length cap. `null` and *absent* are
equivalent; write whichever is natural for your exporter.

## Each message

Required, all three: `sender`, `content`, `timestamp`. Optional: `metadata`.

`content` must have at least one non-whitespace character and is capped at
`max_content_length` **characters**, not bytes. A message whose text is empty
in the source has nowhere to go — it is a Wave 2 decision, not something to
paper over with a space.

Message order in the array is the order they are stored. Sort by timestamp in
the exporter; do not rely on the source's natural row order, which is
insertion order and is not the same thing after an edit or a re-send.

## Senders

Exactly two sides exist. The schema accepts eight spellings, matched
case-insensitively with surrounding whitespace stripped:

| Write any of | Stored as |
|---|---|
| `user`, `human`, `customer`, `end_user` | `end_user` |
| `assistant`, `bot`, `ai`, `agent` | `agent` |

Anything else is `unknown_sender` and fails the whole run. `system`, `tool`
and `function` rows are the common case and they genuinely have nowhere to
go — that is a Wave 2 decision (drop them, or fold their text into the
adjacent agent message, and either way say what it does to the counts).

**`agent` here means the assistant side of this transcript.** It has nothing
to do with the AgentSight agent the import is uploaded to. Read the alias
table off the served schema's `x-agentsight-alias-map` annotation rather than
from memory if you need to show it to the user.

## Timestamps

Both levels are required, and both need an **explicit UTC offset or `Z`**.
This is the single rule real exports get wrong most often, because most
databases store naive local time and most exporters serialize it naively.

Accepted: `2025-11-03T14:22:05Z`, `2025-11-03T16:40:00+01:00`,
`2025-11-04T09:05:30-05:00`. A space instead of `T` is accepted, as are
one-digit month/day/hour components and fractional seconds. Rejected:
`2025-11-03T14:22:05` — no offset, reported as `missing_offset`.

There is a plausibility window: timestamps far in the past or in the future
are `timestamp_out_of_range`. It exists to catch epoch arithmetic gone wrong
(a `0` that becomes 1970, a two-digit year that becomes 2019) rather than to
police your data.

The conversion, once the user has answered which timezone the source is in:

```python
from zoneinfo import ZoneInfo
aware = naive.replace(tzinfo=ZoneInfo("Europe/Madrid"))
aware.isoformat()      # '2025-11-03T16:40:00+01:00'
```

Never `timezone(timedelta(hours=1))`. A fixed offset is correct for half the
year in any DST region and wrong for the other half, and nothing downstream
reveals the error.

## Metadata

Optional at both levels, an object or `null`. Values may be strings, numbers,
booleans, `null`, nested objects, or arrays of those.

Four rules bound it, all read from the served limits document:
`max_metadata_bytes` on its serialized size, `max_metadata_depth` on nesting,
a per-level key count, and a key-length cap. Three reserved key names
(`__proto__`, `constructor`, `prototype`) are refused anywhere.

Two things about the size rule that matter when you are choosing what to put
in it. It is measured on the **compact** serialization
(`separators=(",", ":")`) in **UTF-8 bytes**, so pretty-printing does not
count against you but non-ASCII text does — more than you would guess from the
character count. And the depth rule counts **objects only**: an array is not a
nesting level, so a list of lists of lists costs nothing.

This is why Wave 3 asks for a named allow-list rather than accepting "put the
rest of the row in metadata". "The rest of the row" is exactly what makes the
size rule fire, on the widest conversations, halfway through a large upload.

`NaN` and `Infinity` are not JSON. Python's `json.dump` writes them anyway
unless you pass `allow_nan=False`, and the server rejects them as
`invalid_number`. A `NULL` in a numeric source column should become `null`,
not `NaN`.

NUL bytes (`U+0000`) are rejected anywhere in any string — content, ids, text
fields, metadata keys and values alike. Postgres cannot store them. They turn
up in exports from systems that stored binary in a text column.

## What an import does not carry

Conversations and their messages. That is all.

**No token usage, no cost, no tool calls, no actions, no feedback, no
attachments, no IP address and therefore no geolocation.** The dashboard's
token, cost and map charts stay empty for imported history — not until you
add something, but permanently, because those fields have no place in the file
and no route in afterwards.

Tell the user this before they map a single field, and get it acknowledged.
It is the one thing in the whole workflow that cannot be fixed later.

## Dedup, undo, and the environment

**Dedup is on `(agent, conversation_id)`.** An id that already exists for that
agent is rejected — `conversation_already_exists` — and never merged into. Two
consequences worth stating to the user: re-uploading a part file is safe
(it cannot double-import), and a `conversation_id` scheme that collides with
what live tracking already writes will reject rows rather than combine them.
If the source ids could collide, a `legacy-` prefix is the usual answer, and
it is a Wave 1 question because it cannot be changed afterwards without an
undo.

**An import is all-or-nothing and undoable as a unit.** The first error fails
the whole run and nothing is written; a committed run can be undone from the
dashboard's History, which deletes every conversation it created and frees the
ids again.

**The user picks an environment per run.** Non-production environments never
appear in analytics reports — deliberately — so history imported to
`development` will look like it vanished. Ask, do not default.

## The rules JSON Schema cannot express

Four rules live only in the server's Python and are invisible to any schema
check:

1. metadata serialized size
2. metadata nesting depth
3. a message `timestamp` being at or after its conversation's `started_at`
4. `NaN` / `Infinity` anywhere in metadata

plus every duplicate check, which needs the database. This is precisely why
this skill ships `scripts/validate_import.py` instead of asking you to re-read
the rules — see [verification.md](verification.md).
