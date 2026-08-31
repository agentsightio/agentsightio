---
name: agentsight
description: >
  AgentSight — conversation analytics and observability for AI agents: the
  SDK, tracking plane, and data/API plane, for a codebase that already
  records to AgentSight. Use this skill whenever agentsight is already wired
  into the repo — an agentsight.init() call, an AGENTSIGHT.md record, an
  AGENTSIGHT_* environment variable or ags_ API key present — and the task
  touches it in any form: writing or changing tracking code (conversations,
  turns, messages, tools, streaming handlers), reading or managing recorded
  data via the API client or REST (feedback, actions, usage and cost,
  spans), embedding the client dashboard, debugging why a metric or chart
  is empty, or answering any question about the SDK or API surface. For a
  codebase not yet integrated, or bringing a new service online, use the
  agentsight-integration skill instead; for loading conversations that
  already happened in a previous system into AgentSight — backfill, bulk
  import, historical migration — use the agentsight-migration skill.
---

# AgentSight: the SDK and API

AgentSight records what an AI agent actually did — conversations, exchanges,
tool calls, LLM usage and cost — and turns it into a dashboard the developer
(and their clients) read. This skill is the knowledge home: the full tracking
and API surface, what powers each metric, and how to debug what was recorded.

Two planes, one product:

- **Tracking** (`import agentsight`) — records; never raises, never blocks.
- **Data** (`from agentsight.api import AgentSight`) — reads and manages;
  always raises. Also the home of feedback creation and action labelling.

Published docs: `https://docs.agentsight.io` — every page has a copy-as-
markdown button and the site serves raw markdown, so fetch pages directly
when you need more than the references here. Never contradict them.

**The other skills.** Three skills, split on one axis: the tense and location
of the data. Conversations that have not happened yet — a codebase with no
AgentSight, or a new service being brought online — belong to the sibling
`agentsight-integration` skill: code-first discovery, a consent interview, and
verification before any claim of success. Conversations that happened
somewhere else — a previous platform, a legacy database, a vendor export —
belong to the sibling `agentsight-migration` skill, which builds the
historical import file the developer uploads in the dashboard. This skill owns
conversations that are already in AgentSight. Switch to the right one rather
than improvising either workflow from the references here.

## Hard rules

These hold for every line of tracking code, not just the first integration:

- **`AGENTSIGHT.md` at the repo root is binding.** A previous integration run
  recorded the developer's decisions there (conversation id, consented
  functions, environments, named gaps). Read it before changing
  instrumentation; update it when a decision changes.
- **Consent is per function.** Decorating a tool sends its real argument and
  return values; message content and metadata leave the process; there is
  **no field-level redaction**. Before instrumenting anything that handles
  sensitive values, ask — and offer the file-exporter dump (the actual bytes)
  rather than arguing. LLM prompts and completions are never sent.
- **Never decorate a tool LangChain or LlamaIndex already reports** — that
  records two spans per call.
- **Tracking calls never raise**, so absence of errors is not evidence of
  correctness. After any change, read back what was recorded —
  [references/debugging.md](references/debugging.md).
- **The conversation id is the developer's durable business id.** Never ship
  a generated id for a real thread.
- **A handler that returns before its work is done needs `wrap()`** (or
  `keep_open()`) — otherwise latency records as ~0 and the answer lands in an
  orphan exchange. Get the shapes from
  [references/streaming-and-lifetime.md](references/streaming-and-lifetime.md).
- **The escalation metric is name-keyed**: only actions named exactly
  `fallback_to_human`, `open_ticket`, `ticket`, or `contact_human` count.
- **A wrong environment fails silently**: `development` is excluded from
  analytics by design, so a mis-set deployment looks like silence, not an
  error. QA and eval traffic goes to `development` or `enabled=False`.

## Changing instrumentation in a wired repo

1. Read `AGENTSIGHT.md` (fallback name: `AGENTSIGHT_INTEGRATION.md`) — the
   recorded decisions govern your change.
2. Match the existing integration's patterns: the same id source, the same
   explicit-vs-inferred message style, decorators nested where they already
   are.
3. New tool or new fields = new data leaving the process — the consent rule
   above applies as if this were day one.
4. Verify with the file-exporter loop before reporting done
   ([references/debugging.md](references/debugging.md)).

## Reference files

Read them when their subject enters the work — not all up front:

| File | Read when |
|---|---|
| [references/sdk-tracking.md](references/sdk-tracking.md) | writing or reviewing any tracking code — init(), conversations, turns, messages, tools, attachments, limits |
| [references/streaming-and-lifetime.md](references/streaming-and-lifetime.md) | any handler streams, defers, queues, uses websockets or thread pools — and for `shutdown()`/`flush()` wiring |
| [references/frameworks.md](references/frameworks.md) | the app calls any LLM — coverage tables, stand-down rules, `model_hint()`, the not-captured list |
| [references/metrics-and-fields.md](references/metrics-and-fields.md) | choosing conversation fields, naming the handoff tool, environments — what powers what on the dashboard |
| [references/data-plane.md](references/data-plane.md) | wiring feedback, labelling actions, reading data back, non-Python services, REST details |
| [references/embed.md](references/embed.md) | the client-facing dashboard embedded in the developer's own product |
| [references/debugging.md](references/debugging.md) | any "why is this empty/wrong?" question, and after any change to tracking code — the file-exporter loop and the symptom table |
