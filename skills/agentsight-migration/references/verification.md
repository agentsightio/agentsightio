# Verifying the file

You cannot check a 16 KB metadata rule, a nesting-depth rule or a cross-file
duplicate id by reading the file. **Verification is the validator's exit code**
— running it and pasting the output is the evidence, and your own inspection of
the JSON is not a substitute for it at any point in the workflow.

## Contents

- [Running it](#running-it)
- [Exit codes](#exit-codes)
- [Reading the report](#reading-the-report)
- [What it cannot check](#what-it-cannot-check)
- [Reconciling against the source](#reconciling-against-the-source)
- [The report to the user](#the-report-to-the-user)

## Running it

```bash
export AGENTSIGHT_API_KEY=ags_...
python3 scripts/validate_import.py export-part-01.json export-part-02.json
```

It needs `jsonschema`; if it is missing the script says so and validates
nothing rather than half-checking. It fetches the schema and the limits from
the same routes step 1 used, so what it enforces is what the server enforces
today, not what was true when the script was written.

**Pass every part file in one invocation.** Duplicate conversation ids across
parts are the single failure a per-file run cannot see, and they are common —
a `WHERE` clause with an overlapping boundary produces them silently.

If the environment genuinely cannot reach the API, `--schema path/to/schema.json`
validates against a local copy the user pasted. The report then prints an
`OFFLINE` banner naming every cap that came from the script's fallback table
instead of from the server. Say that in your report too; do not quietly present
an offline run as a checked one.

Other flags: `--endpoint` for a non-default deployment, `--api-key` if the
environment variable is not available (it lands in shell history, so prefer the
variable), `--max-examples` to print more than ten findings per code.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | Every check the script can make ran and found nothing |
| 1 | Findings — the file has contract violations, or is not valid JSON |
| 2 | Usage: bad arguments, or a file that cannot be read |
| 3 | **No verdict.** The contract fetch failed, the key was rejected, or `jsonschema` is missing. **Nothing was validated** |

Exit 3 is not a pass and not a failure. Treat it as a blocked step: fix the
fetch, or use `--schema`, and run again. Never report progress on the strength
of a 3.

## Reading the report

Findings are grouped by the server's own error code, most frequent first, with
the exact total and up to ten examples each. Every example names the file, the
conversation index, its `conversation_id`, and the field path
(`messages[4].timestamp`) so it can be found in the file directly.

The codes are the same ones the dashboard's error glossary explains, so a code
here is a code the user would have seen after uploading. The ones worth
recognising on sight:

- `unknown_sender` — a sender outside the eight aliases. Almost always
  `system` or `tool` rows that a Wave 2 decision was supposed to remove.
- `missing_offset` — a timestamp with no `Z` and no offset. The timezone work
  did not reach this code path.
- `before_started_at` — a message earlier than its conversation's start. Check
  the timezone answer before treating it as a data problem; a partial-range
  timezone error produces exactly this.
- `metadata_too_large` / `metadata_too_deep` — the allow-list is too wide, or
  a nested object was copied wholesale.
- `duplicate_conversation_id` — the report names where the first occurrence
  was, including which part file, so an overlapping export window is obvious.
- `invalid_number` — `NaN` or `Infinity` reached the file. The exporter is
  missing `allow_nan=False`.

**Warnings do not affect the exit code** and are not failures: unknown
top-level keys, and any single conversation too large for the dashboard to pack
into one chunk.

## What it cannot check

The report ends with this list and you should repeat it rather than paraphrase
it:

- **`conversation_already_exists`** — whether an id is already used for that
  agent. That needs the database, and it is the most likely remaining rejection
  for a second or third import.
- Ids held by another open import run.
- Run bookkeeping: declared counts, the per-agent open-run cap.
- The exact chunk byte sizes, which the browser's own serializer measures.
- **Anything at all about the timezone.** A file with every timestamp shifted
  three hours passes cleanly.

So: passing is necessary, never sufficient. Say so in the report, in those
terms.

## Reconciling against the source

At step 9, after the full export validates, compute three numbers from the
files and compare them to the same three queries against the source, with the
scope filters the interview settled:

1. conversation count
2. message count
3. min and max `started_at`

Any gap is either a filter the export applied and the query did not, or a lossy
decision from Wave 2 — and in the second case the gap should equal the counts
in that table exactly. If it does not, something was dropped that nobody
decided to drop, and that is a stop-and-investigate, not a rounding error.

The min/max comparison is also the second-best timezone check available: if the
source's earliest conversation is 09:12 local and the file says 08:12Z, the
offset applied is visible. It confirms the shift you applied; it cannot confirm
the shift was the right one.

## The report to the user

Lead with what to do next — which file to upload, in what order, to which
agent, at `/{agent_id}/migrate`. Then:

- The validator's output, pasted, with its exit code.
- The reconciliation numbers, and any gap explained.
- Every Wave 2 decision and how many rows it affected.
- Every default taken in Wave 3.
- **The timezone, named as an assumption the user owns.** Say which zone was
  applied, that nothing in the pipeline can verify it, and that the pilot's
  clock check was the only opportunity to catch it being wrong.
- What is not migrated, repeated: no tool calls, tokens, cost, actions,
  feedback, attachments or geolocation, permanently.
- That undo exists, is run-scoped, and frees the ids again — which is what
  makes uploading the first part a low-risk thing to do.
