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
dashboard credentials or a password. **You also make no request to the
AgentSight API**: the contract you work from ships inside the skill, and
nothing in a file-on-disk deliverable needs it — not an API key, not an
endpoint, not a "check what already exists" read.

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
| [contract/](contract/) | with contract.md — the shipped snapshot of the server's schema, limits and example; `MANIFEST.json` names the backend commit they were taken from |
| [references/extraction.md](references/extraction.md) | writing the exporter — the source shapes and the properties the output must have |
| [references/verification.md](references/verification.md) | always, before handing over any file — running the validator, reading its exit code, and the reconciliation arithmetic |
| [../agentsight/references/metrics-and-fields.md](../agentsight/references/metrics-and-fields.md) | the user asks what an imported conversation will and will not show on the dashboard |
| [../agentsight/references/data-plane.md](../agentsight/references/data-plane.md) | reading imported conversations back afterwards — the sibling skill's job, and never a step of this one |

## The workflow

### 0. Read the record

If the repo has an `AGENTSIGHT_MIGRATION.md`, a previous run wrote it and its
answers are binding: re-ask only what it does not cover. If it has an
`AGENTSIGHT.md` (or `AGENTSIGHT_INTEGRATION.md`), an integration run wrote
that one — read the conversation id it recorded. **That is the only cross-skill
hazard in the product**: live recording and the import dedup on the same
`(agent, conversation_id)` pair, so a scheme that collides silently rejects
rows, and a scheme that diverges splits one customer's history in two.

### 1. Read the contract — from the shipped snapshot, never from memory

The skill ships the server's contract in `contract/`:

| File | What it is |
|---|---|
| `contract/limits.json` | every cap — `max_conversations_per_run`, `max_messages_per_conversation`, `max_content_length`, the metadata caps, `max_open_runs_per_agent`, `max_import_file_bytes` — so no number in this skill is ever written down |
| `contract/import_v1.schema.json` | the JSON Schema the dashboard, the server and the validator all compile from |
| `contract/example_import.json` | a known-good file |
| `contract/MANIFEST.json` | the backend commit and date the three were taken from — quote it in the final report |

Read `limits.json` now and take every cap from it. **Do not curl anything for
these**: not `api.agentsight.io`, not a local instance, not another port. The
three contract routes exist on the API for humans; they are not part of this
workflow, and neither is an API key. If `contract/` is missing, the install is
incomplete — stop and say so; never reconstruct the contract from memory. A
server newer than the snapshot rejects at upload with a named error code, and
the recovery is a refreshed skill, not a fetch.

### 2. Inspect the source — silent and read-only

Resolve everything the data can answer before asking anything: the distinct
sender values **with their counts**; the timestamp columns and their declared
types (is it `TIMESTAMP WITH TIME ZONE`, or a naive local `DATETIME`, or an
integer epoch?); the content-length distribution and its maximum; duplicate
conversation-id counts; the full date range; how many conversations have zero
messages. `SELECT` only — no temp tables, no `ANALYZE`, no writes of any kind
against a system that is still someone's production database.

Connect in a way that *cannot* write, not merely in a way that does not. Ask
for a read-only role or a replica; when all you are given is a read-write
credential, pin the session read-only (`SET default_transaction_read_only =
on` on Postgres, `SET SESSION TRANSACTION READ ONLY` on MySQL, a
`file:...?mode=ro` URI on SQLite) so a slip is an error rather than a change.
Reading through the source application's own ORM is fine; letting it "fix"
anything is not — a framework that reports unapplied migrations is describing
the source, not asking you to change it. The only migration this skill
performs is the one in its name, and it ends in a JSON file. The source is
left exactly as it was found: no schema change, no status column, no
"exported" flag.

### 3. Findings summary, then the interview

Present what you determined, then run the three waves in
mapping-interview.md. Wave 2's counts are only computable once Wave 1 has
settled the sender map and the timezone, so the waves cannot be merged. Each
wave is its own turn — ask, wait for the answer, then ask the next — including
under plan mode: never one questionnaire, and never decisions written into a
plan file on the user's behalf.

### 4. Write AGENTSIGHT_MIGRATION.md

Persist the mapping, the timezone answer, every lossy-category decision, and
the defaults taken — **before** exporting anything, so the record survives a
run that stops early.

### 5. Produce a stratified pilot of ~10

Not `LIMIT 10`. The oldest conversations are the shortest and cleanest, so a
head-of-table sample proves nothing. Take one per lossy category the user
chose to keep, the longest transcript, one with non-ASCII content, the richest
metadata, and one from each end of the date range.

It lands at `agentsight_migration/pilot.json`. This is the first transcript
file the run creates, so the `agentsight_migration/*.json` line goes into
`.gitignore` **before** it does — check whether an existing rule already
covers it, and add it if not.

### 6. Validate

```bash
python3 scripts/validate_import.py pilot.json
```

No key, no flags, no network: it reads the shipped snapshot. **Run it and
paste its output.** Exit 0 is the only pass; see verification.md for what each
code means.

### 7. Pilot gate — stop here

Hand the file to the user and name exactly what to look at: message **order**,
**speaker attribution** (is the assistant's text really on the assistant
side?), and *do the clock times match what you remember happening* — that last
one is the only check in the whole workflow that catches a wrong timezone.
Wait for their answer. Do not export the full history first.

### 8. Full export

Numbered part files split on conversation boundaries — never mid-conversation
— plus `manifest.json` recording, per part, its conversation count, message
count and id range. One file is one upload, so the parts are also the user's
upload plan. Everything goes in `agentsight_migration/` beside the exporter
that wrote it. Delete the pilot once the parts supersede it: a pilot that is
a subset of a part would fail the run on `conversation_already_exists`.

### 9. Re-validate, reconcile, report

Run the validator over **all parts at once** — cross-file duplicate ids are
invisible to a per-file run. Then reconcile against the source: conversation
count, message count, and min/max timestamp, computed from the files and
compared to the same three queries against the database — and assert that
every `conversation_id` in the files carries the prefix agreed in Wave 1; a
file without it does not leave your hands. Report the numbers, the decisions
taken, and the timezone as an assumption the user owns.

## Hard rules

- **You cannot upload.** The file is the deliverable. Never claim an import
  was performed, and never ask for dashboard credentials.
- **No request to the AgentSight API.** The contract ships with the skill,
  the file is the deliverable, and the server re-validates on upload — so
  there is no request to make: no contract fetch, no API key, no endpoint, no
  probing of local ports. A newer server contract shows up at upload as a
  named rejection, never as a wrong file here.
- **Every id is prefixed.** The prefix is agreed in Wave 1 (`legacy-` or the
  user's own); bare source ids never go into the file. Collisions after
  upload are the server's `conversation_already_exists` plus run-scoped undo —
  there is no pre-check, and you do not query for one.
- **Read-only against the source.** It is a live system belonging to someone
  who has not agreed to let you write to it. "Migration" here means moving
  data *out* into a file; it never means a schema migration, and you never
  run one — not `manage.py migrate`, not `alembic upgrade`, not a hand-written
  `ALTER` — whatever the source framework says about unapplied changes.
  Prefer a credential that cannot write over a promise not to.
- **Never assume a timezone.** Ask, always, even when the column looks
  obvious. Localize with `zoneinfo.ZoneInfo`, never a fixed `timedelta`
  offset — a fixed offset is wrong for half of every year in any region with
  DST, and silently so.
- **`json.dump(..., allow_nan=False)`.** Python writes bare `NaN` and
  `Infinity` by default; both are invalid JSON and the server rejects them.
- **`sender: "agent"` is the assistant side of the transcript**, not the
  AgentSight agent that owns the import. They are unrelated concepts with the
  same word, and confusing them mislabels every message in the file.
- **The export stays in the project, in `agentsight_migration/`, and the
  ignore rule lands first.** One directory at the repo root holds the whole
  job — the exporter, the manifest and the part files:

  ```
  agentsight_migration/export_import_file.py     the exporter — tracked, it is code
  agentsight_migration/manifest.json             per-part counts and id ranges
  agentsight_migration/pilot.json                the step-5 sample
  agentsight_migration/<agent>-legacy-part-01.json   the parts
  ```

  `agentsight_migration/*.json` goes into `.gitignore` **before** the first
  JSON is written, so there is never a moment when a transcript is untracked
  and unignored. The glob covers the pilot, every part and the manifest —
  which is ignored too, because ids can be PII — and leaves the exporter
  trackable, which is what you want: it is the repeatable half. Do not write
  any of it outside the project. The user has to find these next to the code
  they came from, an absolute path under `/home` is invisible to anyone else
  who clones the repo, and nothing in the project would record that the
  export ever happened.
- **Verification is the validator's exit code, never your reading of the
  file.** You cannot check a 16 KB metadata rule or a depth rule by eye.
- **Passing the validator is necessary, never sufficient.** It cannot see
  whether an id already exists, and it cannot see a wrong timezone at all.
