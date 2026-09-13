---
outline: deep
---

<CopyMarkdownButton />

# Importing existing history

Once AgentSight is recording, the dashboard starts at cutover: the tracking SDK
is the only way live traffic gets in, so everything that happened before is
still wherever it happened. If that history matters — because the charts are
thin without it, or because the transcripts your clients read should not begin
abruptly one Tuesday — you can bring it over as a one-off bulk import.

It is a file upload, done once per batch, in the dashboard.

## What the file is

One JSON document: a `schema_version` marker and a list of conversations, each
with an id, a start time, and its messages. Every timestamp carries an explicit
UTC offset. The dashboard's migrate page publishes the exact contract —
[the format guide](https://app.agentsight.io) has field tables generated from
the live schema, a downloadable example, and the error glossary — and the same
three documents are readable over the API:

```bash
curl -H "Authorization: Api-Key $AGENTSIGHT_API_KEY" \
     https://api.agentsight.io/api/imports/schema/
```

`/api/imports/limits/` and `/api/imports/example/` alongside it. These three
are the only import routes an API key can read. They are there for a human
with `curl`, or for tooling that wants the live document; an agent using the
migration skill below works from the skill's own shipped copy of the same
three documents and makes no request at all.

## Where the file comes from

Your own database, most of the time — a conversations table, a messages table,
and a mapping problem. Sometimes a vendor export from a platform you are
leaving, or a JSONL transcript log.

The intended route is to let a coding agent do it. The SDK repository ships an
`agentsight-migration` skill for exactly this: point the agent at your source
and it inspects it read-only, interviews you about the parts it cannot infer,
writes the exporter, and validates the result with a script it ships.

::: tabs
== skills CLI
```bash
npx skills add agentsightio/agentsightio
```
== Claude Code plugin
```
/plugin marketplace add agentsightio/agentsightio
/plugin install agentsight@agentsight
```
:::

Then: *"import my conversation history into AgentSight from this database"*.

**The agent produces the file. It cannot upload it.** The import routes are
dashboard-only — an API key gets a 403 on every one of them — so the agent
hands you a file and you drop it on the migrate page yourself. That is
deliberate: an import writes tens of thousands of rows into a customer-facing
dashboard, and a human starts it. The skill is offline by design: it needs no
API key and makes no request to AgentSight, because the contract it validates
against ships inside it and the server re-validates everything on upload.

## What it asks you

Three answers decide whether the result is right, and none of them can be read
out of the data:

- **Which field is the conversation id.** Imports deduplicate on
  `(agent, conversation_id)`, so this decides what a thread is, and whether
  imported rows can collide with what live tracking is already writing.
- **What timezone the timestamps are in.** Most databases store naive local
  time. Nothing downstream can detect a wrong answer — every chart will look
  plausible and be shifted — so the skill always asks, and it asks again about
  daylight saving and about whether the source ever changed how it stored time.
- **What happens to every row that cannot be represented.** `system` and `tool`
  messages, empty messages, conversations with nothing in them, oversized
  metadata. Each is a decision that moves your metrics, so the skill counts
  them, shows you the table, and takes an answer per category rather than
  quietly dropping anything.

## What is not migrated

Conversations and their messages. Nothing else.

No tool calls, no token usage or cost, no actions, no feedback, no attachments,
no IP address and therefore no geolocation. **The token, cost and map charts
stay empty for imported history permanently** — those fields have no place in
the file and no way in afterwards. Live traffic recorded through the SDK is
unaffected.

## How a large history arrives

One file is one import, and the caps are published in
`/api/imports/limits/` (and shipped with the migration skill as
`contract/limits.json`) — conversations per import, a browser-side file size,
and how many imports can be open at once for an agent. A history past any of
them is split into numbered parts and uploaded in sequence.

Splitting is safe because of the dedup rule: a `conversation_id` that already
exists is **rejected, never merged**, so re-uploading a part cannot
double-import it. Each run is also all-or-nothing — the first error fails it
and writes nothing — and a committed run can be undone from the dashboard's
History, which deletes everything it created and frees the ids again.

## Reading it back

Imported conversations are ordinary conversations. They appear in the
dashboard, in the embeddable client dashboard, and on the
[API client](/api/conversations) like any other — `ags.conversations.list()`
and `ags.conversations.get(...)` do not distinguish them.
