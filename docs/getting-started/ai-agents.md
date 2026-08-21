---
outline: deep
---

<CopyMarkdownButton />

# Use with AI agents

Increasingly, the thing integrating AgentSight is not a developer reading this
site — it is a coding agent working in your repository. These docs are built
for that reader too, and there is a packaged skill that makes the whole
integration a task an agent completes correctly on the first pass.

## The integration skill

The SDK repository ships a skill —
[`skills/agentsight-integration`](https://github.com/agentsightio/agentsightio/tree/main/skills/agentsight-integration)
— in the emerging agent-skills convention: a `SKILL.md` entry point plus
reference files. It contains the full tracking and API surface, and, more
importantly, the judgment calls the docs teach a human: when the quickstart
shortcut fits and when the explicit form is required, why
[`wrap()`](/tracking/streaming) is not optional on a streaming handler, where
[`shutdown()`](/getting-started/deployment) must be wired, and which tools a
framework already reports.

An agent following it will:

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

## Installing it

With the [skills CLI](https://skills.sh) — works with Claude Code, Cursor,
Codex, and most other coding agents:

```bash
npx skills add agentsightio/agentsightio
```

In Claude Code, the repository is also a plugin marketplace, which gets you
update tracking through the plugin manager:

```
/plugin marketplace add agentsightio/agentsightio
/plugin install agentsight@agentsight
```

Either way, then ask for the integration in plain words — "add AgentSight to
this service". Any harness that can read files can use the skill without an
installer too: copy `skills/agentsight-integration` from the repository into
your project and point the agent at its `SKILL.md` — it pulls in the
reference files as it needs them.

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
