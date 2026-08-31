# The mapping interview

An import is irreversible in one direction only — it can be undone, but a
wrong answer that nobody notices becomes the user's history. Three of the
questions here have no recoverable default, and one of them (the timezone) is
unverifiable by anything downstream. So the interview is not a formality
before the real work; it *is* the part of this workflow that decides whether
the result is correct.

Three waves, in order. They cannot be merged: two of Wave 2's counts are only
computable once Wave 1 has settled the sender map and the timezone.

## Contents

- [Resolve these silently first](#resolve-these-silently-first)
- [Wave 1 — no defaults](#wave-1--no-defaults)
- [Wave 2 — the lossy report](#wave-2--the-lossy-report)
- [Wave 3 — each with a default](#wave-3--each-with-a-default)
- [The record file](#the-record-file)

## Resolve these silently first

Never ask what the data already answers. Before the first question, know: the
distinct sender values and **how many rows carry each**; every timestamp
column's declared type and whether it is offset-aware; the content-length
distribution and its maximum; the count of duplicate conversation ids; the
full date range; the count of conversations with zero messages; which columns
are always null. Each of these turns a question the user has to think about
into a question they can confirm.

Every question below arrives with its finding attached. "I found 41,882
`user`, 41,109 `assistant` and 3,204 `system` rows — the first two map
automatically; what should happen to the 3,204?" is answerable. "How are your
senders structured?" is not.

## Wave 1 — no defaults

Four questions. None has a safe default, and all four are unrecoverable
without an undo and a re-import.

**1. Which agent, and which environment?** Dedup is scoped per agent, so this
choice decides which existing ids the import can collide with. Environment
matters more than it looks: non-production environments are excluded from
analytics reports by design, so history imported to `development` is present
in the transcripts and absent from every chart, which reads as a bug. Ask;
never infer it from the agent's name.

**2. Which field is `conversation_id`, and does it need a prefix?** Present
the candidates you found. Then three follow-ups, because the column being
unique in the source is not the question:

- Is it **stable** — does the same thread keep the same id across a restart,
  a re-open, a support handoff?
- Is it **PII**? Ids built from an email or a phone number end up in a URL
  and in the customer-facing dashboard.
- Could it **collide with live tracking**? If AgentSight is already recording
  for this agent, or is about to, an overlapping id is rejected, not merged.
  A `legacy-` prefix is the usual answer and it cannot be changed later
  without undoing the whole run.

**3. The sender mapping**, presented as the real distinct values with their
counts. The eight standard spellings map themselves; what needs an answer is
everything else. Do not offer a default for `system`/`tool` rows — see Wave 2,
where they are counted alongside every other lossy category.

**4. What timezone are these timestamps in?**

Ask this every time. Ask it even when the column is `TIMESTAMP WITH TIME
ZONE`, because the value stored there is often naive local time that was
written through a driver that stamped UTC on it. Ask it when the answer looks
obvious from the company's address, because the database may have been
provisioned elsewhere.

Two follow-ups, both of which catch real errors:

- **Did the source ever change how it stored time?** A migration, a framework
  upgrade, a server move. If yes, the answer is a date and two zones, not one
  zone, and the exporter needs a branch.
- **Does the zone observe DST?** If so, take the IANA name (`Europe/Madrid`),
  not the offset, and localize with `zoneinfo.ZoneInfo`. A fixed offset is
  wrong for half of every year, silently.

State plainly, in the same message, that **you cannot verify this answer and
nothing downstream will reveal it.** The pilot's clock check at step 7 is the
only opportunity to catch it, and it depends on the user actually recognising
the times.

## Wave 2 — the lossy report

Every category here is a row or a conversation that **cannot go into the file
as it stands**. The user decides what happens to each; you decide nothing
silently.

Lead with the count. One table, all thirteen categories, zero-count rows
included so the user can see what was checked and found clean:

```
Category                                  Affected
------------------------------------------------------
Conversations with no messages                   412
Conversations over the message cap                 3
Messages with empty content                    1,109
Messages over the content cap                      0
Unmappable senders (system: 3,204)             3,204
timestamp earlier than started_at                 17
Timestamps outside the plausibility window         0
NUL bytes in text                                  2
Metadata over the size cap                        88
Metadata nested too deep                           0
Metadata key count / length / reserved names       0
NaN or Infinity in numeric fields                  6
Duplicate ids / text fields over the cap          31
```

Then one decision per **non-zero** row. Do not walk the user through nine
clean categories; do not silently skip a dirty one.

The usual shapes of the answer, per category:

- **Zero-message conversations** — drop, or synthesize nothing (there is no
  legal empty conversation; at least one message is required). Almost always
  drop, but say how many.
- **Over the message cap** — split into numbered parts with a suffixed id, or
  keep the first N. Splitting changes what "a conversation" means on the
  dashboard; keeping the first N loses the end of the thread.
- **Empty content** — drop the message, or substitute a placeholder. A
  placeholder puts text in a transcript the user's own client will read.
- **Over the content cap** — truncate with a marker, or drop.
- **Unmappable senders** — drop the rows, or fold their text into the
  adjacent `agent` message. Folding preserves context and changes message
  counts and per-message timings.
- **`timestamp` before `started_at`** — usually the conversation's start was
  recorded late; clamp `started_at` to `min(timestamp)`, or drop the offending
  message. This one is often a symptom of the timezone answer being wrong for
  part of the range, so check before choosing.
- **Timestamps outside the plausibility window** — nearly always epoch
  arithmetic or a two-digit year. Investigate before deciding; a "drop" here
  usually discards data that a fixed parse would have kept.
- **NUL bytes** — strip them. There is no other option; Postgres cannot store
  them.
- **Metadata over the size cap / too deep / bad keys** — this is what the
  Wave 3 allow-list is for. Narrow the fields rather than truncating values.
- **`NaN` / `Infinity`** — to `null`, or drop the key. Both are legal; `null`
  keeps the field's presence, which sometimes matters to whoever reads it.
- **Duplicate ids** — suffix them, or keep the first. Suffixing splits one
  thread in two on the dashboard; keeping the first loses the other.
- **Text fields over the cap** — truncate. They are labels, not content.

**One standing note to state once, at the top of this wave:** dropped messages
move the metrics. Conversation duration is first-to-last message, and
first-response time is the first `end_user` → first `agent` gap, so dropping
`system` rows or empty messages changes both. This is a data decision the user
owns, not a cleanup you perform on their behalf.

## Wave 3 — each with a default

Take the default on silence, and name every default taken in the final report.

**Confirm what is not migrated — no default.** The one exception in this
wave. Conversations and their messages only: no tool calls, no token usage or
cost, no actions, no feedback, no attachments, no IP and therefore no
geolocation. Token, cost and map charts stay empty for this history
**permanently**. Get an explicit acknowledgement; do not proceed on silence.

**Field mapping, plus a named metadata allow-list.** Which source column
becomes `name`, `customer_id`, `language`, `device` — and then, specifically:
which fields go into `metadata`, **by name**. *Default: the fields you can
justify one by one, and nothing else.* Never "the rest of the row" — that is
exactly what makes the size cap fire, and it fires on your widest
conversations, halfway through a large upload.

**`started_at`: the source's own column, or `min(timestamp)`?** *Default: the
source column when one exists, `min(timestamp)` when it does not.* They differ
whenever a thread was opened before anyone spoke, and the difference lands in
the conversation-duration metric.

**Scope, and open conversations.** How far back, and what about threads that
are still active in the source right now? *Default: everything, and exclude
conversations updated in the last 24 hours* — an open thread imported today
cannot receive its later messages, because live tracking will be rejected as a
duplicate id.

**Part sizing.** *Default: parts comfortably under the served
`max_conversations_per_run` and `max_import_file_bytes`, sized so each upload
finishes in a few minutes.* Mention the open-run cap
(`max_open_runs_per_agent`) if the history needs more parts than that — it
bounds how many uploads can be in flight, not how many can be done in total.

## The record file

Write `AGENTSIGHT_MIGRATION.md` at the repo root **before** exporting
anything, so the record survives a run that stops at the pilot gate.

```markdown
# AgentSight migration record

Written by the agentsight-migration skill on <date>. Update it when an
answer changes; a later run treats it as binding.

## Target
- Agent: <name / id>
- Environment: <slug>  (non-production is excluded from analytics reports)

## Source
- System: <what it is>
- Read from: <table / export / connection, read-only>
- Scope: <date range, filters, what was excluded and why>

## Identity
- conversation_id: <source field>  prefix: <none | legacy->
- Stable across restarts: <yes/no>   Contains PII: <yes/no>
- Collides with live tracking: <yes/no — and how that was settled>

## Timestamps
- Source storage: <column type, naive or aware>
- Timezone (user-supplied, UNVERIFIED): <IANA name>
- Handling changed on: <date + old zone, or "no">
- started_at from: <source column | min(timestamp)>

## Field mapping
| AgentSight | Source | Notes |
|---|---|---|
| name | | |
| customer_id | | |
| language | | |
| device | | |

## Metadata allow-list
- <field>: <why it earns its place>

## Sender mapping
| Source value | Count | Mapped to |
|---|---|---|

## Lossy decisions
| Category | Affected | Decision |
|---|---|---|

## Not migrated
Acknowledged by the user on <date>: no tool calls, token usage, cost,
actions, feedback, attachments or geolocation. Those charts stay empty for
imported history permanently.

## Export
- Parts: <n> files, split on conversation boundaries
- Manifest: <path>
- Files are customer transcripts — <gitignored / written outside the repo>
```
