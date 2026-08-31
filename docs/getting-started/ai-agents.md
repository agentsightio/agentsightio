---
outline: deep
---

<CopyMarkdownButton />

# Use with AI agents

Increasingly, the thing integrating AgentSight is not a developer reading this
site — it is a coding agent working in your repository. These docs are built
for that reader too, and the SDK repository ships three packaged skills that
cover the whole lifecycle: getting integrated correctly on the first pass,
bringing your existing history over, and working with the integration every
day after.

## The three skills

Both live in the repository in the emerging agent-skills convention — a
`SKILL.md` entry point plus reference files — and they install together:

[**`skills/agentsight-integration`**](https://github.com/agentsightio/agentsightio/tree/main/skills/agentsight-integration)
is the integration workflow, for a codebase that does not yet record to
AgentSight (or a new service being brought online). An agent following it
will:

- **Read your code first and ask only what code cannot answer** — which of
  the ids it found is your durable conversation id, which tool functions you
  consent to record, which deployment is production. Every question arrives
  with what was already determined, and every optional question has a
  default, so silence still produces a working integration with its gaps
  named.
- **Write the answers down** in an `AGENTSIGHT.md` at your repo root, so a
  later run continues instead of re-interrogating.
- **Verify before claiming success**: run your app with
  [`AGENTSIGHT_FILE_EXPORTER`](/getting-started/configuration) set and read
  back the spans it recorded — checking turn durations, message text, tool
  names and token counts against what the integration promised. No key needed
  for that loop, and the dump doubles as a byte-level answer to "what would
  leave my process?"

[**`skills/agentsight-migration`**](https://github.com/agentsightio/agentsightio/tree/main/skills/agentsight-migration)
covers the conversations that happened *before* you integrated — in a legacy
database, a previous chat platform, or a vendor export. Point an agent at that
source and it inspects it read-only, interviews you about the mapping (which
field is the conversation id, which timezone the timestamps are in, what
happens to every row that cannot be represented), and produces a JSON file it
validates with a script the skill ships. You upload the file yourself on the
dashboard's migrate page — the import routes are deliberately not on the
API-key plane, so the agent builds the file and never sends it. See
[Importing existing history](/getting-started/importing-history).

[**`skills/agentsight`**](https://github.com/agentsightio/agentsightio/tree/main/skills/agentsight)
is the knowledge base, for everything after: the full tracking and API
surface, the judgment calls the docs teach a human — when the quickstart
shortcut fits and when the explicit form is required, why
[`wrap()`](/tracking/streaming) is not optional on a streaming handler, where
[`shutdown()`](/getting-started/deployment) must be wired, which tools a
framework already reports — plus what powers every dashboard metric, the
embeddable dashboard, and a symptom-to-cause table for debugging an empty
chart. Day-to-day work in an integrated repo loads only this skill, not the
integration workflow.

The split is deliberate, and it runs along one axis: the tense and location of
the data. Conversations that have not happened yet are the integration skill's;
conversations that happened somewhere else are the migration skill's;
conversations already in AgentSight are the knowledge skill's. An interview and
verification protocol matters enormously once and is dead weight in every
session after, so each skill tells the agent when another one applies, and both
workflow skills link into the knowledge skill's reference files — which is why
they should be installed together.

## Installing them

With the [skills CLI](https://skills.sh) — works with Claude Code, Cursor,
Codex, and most other coding agents; it will offer all three, install all
three:

```bash
npx skills add agentsightio/agentsightio
```

In Claude Code, the repository is also a plugin marketplace, which gets you
all three skills plus update tracking through the plugin manager:

```
/plugin marketplace add agentsightio/agentsightio
/plugin install agentsight@agentsight
```

Either way, then ask in plain words — "add AgentSight to this service" runs
the integration; "can I get my old conversations in?" runs the migration;
later, "why is the escalation chart empty?" or "record feedback from our UI"
draws on the knowledge skill. Any harness that can read files can use the
skills without an installer too: copy **all three** folders
(`skills/agentsight-integration`, `skills/agentsight-migration` and
`skills/agentsight`) from the repository side by side into your project and
point the agent at a `SKILL.md` — both workflow skills link into the base
skill's reference files, so either one without it is incomplete.

## If you'd rather feed it the docs

Every page on this site has a **Copy as Markdown** button and serves its raw
markdown, so pasting a page into a conversation loses nothing. The pages an
integrating agent gets the most from, in order:
[Quickstart](/getting-started/quick-start),
[Turns & Messages](/tracking/turns-and-messages),
[Streaming](/tracking/streaming),
[Deployment & limitations](/getting-started/deployment), and
[What the SDK sends](/getting-started/what-the-sdk-sends) for the privacy
conversation.
