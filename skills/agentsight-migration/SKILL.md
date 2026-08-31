---
name: agentsight-migration
description: >
  Bring conversation history into AgentSight — conversation analytics and
  observability for AI agents — from wherever it lives now. Use this skill
  when conversations that already happened somewhere else need to end up in
  AgentSight: a legacy database or conversations table, a previous chat or
  analytics platform, a vendor export, a CSV or JSONL transcript log. It
  covers backfill, bulk import, historical migration, "get my old
  conversations in", "import our chat history", and the dashboard's own
  migrate page. The agent inspects the source read-only, interviews the user
  about the mapping (senders, timestamps and their timezone, every lossy
  row), and produces a JSON import file it validates with a shipped script —
  which the user then uploads themselves, because the import routes are not
  on the API-key plane. For a codebase that does not yet record live traffic
  at all, use the agentsight-integration skill; for working with
  conversations already in AgentSight, use the agentsight skill.
---

# Migrating conversation history into AgentSight

AgentSight records what an AI agent actually did — conversations, exchanges,
tool calls, LLM usage and cost — and turns it into a dashboard the developer
(and their clients) read. The tracking SDK is the only way *live* traffic gets
in. This skill is the other half: transcripts that already exist somewhere
else, brought over once as a bulk import.

**You cannot upload the file.** Every import run route is dashboard-only —
`BlockApiKeyAccess` sits on all six of them, so the `ags_` key you hold gets a
403 no matter how the request is shaped, and there is no other credential to
obtain. **The deliverable is a file on disk**, handed to the user with the
instruction to drop it on `/{agent_id}/migrate` in their dashboard. Say this in
your first reply; do not discover it at step 9, and never ask the user for
dashboard credentials or a password.

**The other skills.** Three skills, split on one axis: the tense and location
of the data. This one is conversations that happened somewhere else.
Conversations that have not happened yet — a codebase that records nothing —
belong to the sibling `agentsight-integration` skill, and a repo usually wants
that first: migration fills in the past, integration starts the present.
Conversations already in AgentSight — reading them back, changing tracking
code, debugging an empty chart — belong to the sibling `agentsight` skill.

Published docs: `https://docs.agentsight.io` — every page has a copy-as-
markdown button and the site serves raw markdown, so fetch pages directly
when you need more than the references here. Never contradict them.

## Reference files

Read them when their subject enters the work — not all up front. The two
`../agentsight/` rows live in the sibling `agentsight` skill (the skills ship
and install together); if those paths are missing, that skill was not
installed alongside this one — install both, or fetch the matching pages from
`docs.agentsight.io`.

| File | Read when |
|---|---|
| [references/mapping-interview.md](references/mapping-interview.md) | always, before asking the user anything — the three waves, the lossy-row protocol, and the `AGENTSIGHT_MIGRATION.md` record |
| [references/contract.md](references/contract.md) | before mapping a single field — file shape, senders, timestamps, metadata, and what an import does not carry |
| [references/extraction.md](references/extraction.md) | writing the exporter — the source shapes and the properties the output must have |
| [references/verification.md](references/verification.md) | always, before handing over any file — running the validator, reading its exit code, and the reconciliation arithmetic |
| [../agentsight/references/metrics-and-fields.md](../agentsight/references/metrics-and-fields.md) | the user asks what an imported conversation will and will not show on the dashboard |
| [../agentsight/references/data-plane.md](../agentsight/references/data-plane.md) | reading imported conversations back afterwards, or checking existing ids before the import |

## The workflow

### 0. Read the record

If the repo has an `AGENTSIGHT_MIGRATION.md`, a previous run wrote it and its
answers are binding: re-ask only what it does not cover. If it has an
`AGENTSIGHT.md` (or `AGENTSIGHT_INTEGRATION.md`), an integration run wrote
that one — read the conversation id it recorded. **That is the only cross-skill
hazard in the product**: live recording and the import dedup on the same
`(agent, conversation_id)` pair, so a scheme that collides silently rejects
rows, and a scheme that diverges splits one customer's history in two.

### 1. Fetch the contract — live, never from memory

```bash
curl -H "Authorization: Api-Key $AGENTSIGHT_API_KEY" \
     https://api.agentsight.io/api/imports/schema/
```

Same for `/api/imports/limits/` and `/api/imports/example/`. The trailing
slash is mandatory. These three are the only import routes an `ags_` key can
read; anonymous is a 401, so the key must be sent. **If the fetch fails, stop
and ask the user to paste the schema** — do not reconstruct it. `/limits/`
carries every cap including `max_open_runs_per_agent` and
`max_import_file_bytes`, so no number in this skill is ever written down.

### 2. Inspect the source — silent and read-only

Resolve everything the data can answer before asking anything: the distinct
sender values **with their counts**; the timestamp columns and their declared
types (is it `TIMESTAMP WITH TIME ZONE`, or a naive local `DATETIME`, or an
integer epoch?); the content-length distribution and its maximum; duplicate
conversation-id counts; the full date range; how many conversations have zero
messages. `SELECT` only — no temp tables, no `ANALYZE`, no writes of any kind
against a system that is still someone's production database.

### 3. Findings summary, then the interview

Present what you determined, then run the three waves in
mapping-interview.md. Wave 2's counts are only computable once Wave 1 has
settled the sender map and the timezone, so the waves cannot be merged.

### 4. Write AGENTSIGHT_MIGRATION.md

Persist the mapping, the timezone answer, every lossy-category decision, and
the defaults taken — **before** exporting anything, so the record survives a
run that stops early.

### 5. Produce a stratified pilot of ~10

Not `LIMIT 10`. The oldest conversations are the shortest and cleanest, so a
head-of-table sample proves nothing. Take one per lossy category the user
chose to keep, the longest transcript, one with non-ASCII content, the richest
metadata, and one from each end of the date range.

### 6. Validate

```bash
python3 scripts/validate_import.py pilot.json
```

**Run it and paste its output.** Exit 0 is the only pass; see
verification.md for what each code means.

### 7. Pilot gate — stop here

Hand the file to the user and name exactly what to look at: message **order**,
**speaker attribution** (is the assistant's text really on the assistant
side?), and *do the clock times match what you remember happening* — that last
one is the only check in the whole workflow that catches a wrong timezone.
Wait for their answer. Do not export the full history first.

### 8. Full export

Numbered part files split on conversation boundaries — never mid-conversation
— plus a manifest recording, per part, its conversation count, message count,
and id range. One file is one upload, so the parts are also the user's upload
plan.

### 9. Re-validate, reconcile, report

Run the validator over **all parts at once** — cross-file duplicate ids are
invisible to a per-file run. Then reconcile against the source: conversation
count, message count, and min/max timestamp, computed from the files and
compared to the same three queries against the database. Report the numbers,
the decisions taken, and the timezone as an assumption the user owns.

## Hard rules

- **You cannot upload.** The file is the deliverable. Never claim an import
  was performed, and never ask for dashboard credentials.
- **Read-only against the source.** It is a live system belonging to someone
  who has not agreed to let you write to it.
- **Never assume a timezone.** Ask, always, even when the column looks
  obvious. Localize with `zoneinfo.ZoneInfo`, never a fixed `timedelta`
  offset — a fixed offset is wrong for half of every year in any region with
  DST, and silently so.
- **`json.dump(..., allow_nan=False)`.** Python writes bare `NaN` and
  `Infinity` by default; both are invalid JSON and the server rejects them.
- **`sender: "agent"` is the assistant side of the transcript**, not the
  AgentSight agent that owns the import. They are unrelated concepts with the
  same word, and confusing them mislabels every message in the file.
- **Exported files are full customer transcripts.** Write them outside the
  repo, or add them to `.gitignore` in the same edit that creates them.
- **Verification is the validator's exit code, never your reading of the
  file.** You cannot check a 16 KB metadata rule or a depth rule by eye.
- **Passing the validator is necessary, never sufficient.** It cannot see
  whether an id already exists, and it cannot see a wrong timezone at all.
