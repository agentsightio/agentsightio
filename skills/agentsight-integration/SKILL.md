---
name: agentsight-integration
description: >
  Integrate AgentSight — conversation analytics and observability for AI
  agents — into an application. Use this skill whenever the task involves
  AgentSight in any form: installing or configuring the agentsight Python SDK,
  adding conversation/agent/chatbot analytics or tracking (conversations,
  turns, messages, tools, tokens, cost, escalations, feedback), an
  AGENTSIGHT_* environment variable or ags_ API key, embedding the AgentSight
  client dashboard, reading recorded data via the AgentSight API, or debugging
  why an AgentSight metric or chart is empty — even when the user just says
  "add analytics to my agent" or "instrument my chatbot" without naming a
  file or the word AgentSight appears only in the codebase.
---

# Integrating AgentSight

AgentSight records what an AI agent actually did — conversations, exchanges,
tool calls, LLM usage and cost — and turns it into a dashboard the developer
(and their clients) read. This skill exists because the integration's failure
modes are silent: nothing on the tracking plane ever raises, so a wrong
integration produces plausible wrong data, not errors. Your job is to produce
a **first-pass-correct** integration, and to prove it before reporting done.

Two planes, one product:

- **Tracking** (`import agentsight`) — records; never raises, never blocks.
- **Data** (`from agentsight.api import AgentSight`) — reads and manages;
  always raises. Also the home of feedback creation and action labelling.

Published docs: `https://docs.agentsight.io` — every page has a copy-as-
markdown button and the site serves raw markdown, so fetch pages directly
when you need more than the references here. Never contradict them.

## Reference files

Read them when their subject enters the work — not all up front:

| File | Read when |
|---|---|
| [references/interview.md](references/interview.md) | always, before asking the developer anything — the question protocol, tiers, defaults, and the `AGENTSIGHT.md` record |
| [references/sdk-tracking.md](references/sdk-tracking.md) | always, before writing integration code — the full tracking surface |
| [references/streaming-and-lifetime.md](references/streaming-and-lifetime.md) | any handler streams, defers, queues, uses websockets or thread pools — and for `shutdown()` wiring, which is every integration |
| [references/frameworks.md](references/frameworks.md) | the app calls any LLM — coverage tables, stand-down rules, `model_hint()`, the not-captured list |
| [references/metrics-and-fields.md](references/metrics-and-fields.md) | choosing conversation fields, naming the handoff tool, environments — what powers what on the dashboard |
| [references/data-plane.md](references/data-plane.md) | wiring feedback, labelling actions, reading data back, non-Python services, REST details |
| [references/embed.md](references/embed.md) | the developer wants the client-facing dashboard in their own product |
| [references/verification.md](references/verification.md) | always, before claiming done — the file-exporter loop and checklist |

## The workflow

### 0. Read the record

If the target repo has an `AGENTSIGHT.md` (or the fallback
`AGENTSIGHT_INTEGRATION.md`) at its root, a previous run wrote it. Its
answers are binding: re-ask only what it does not cover, and update it when
the developer changes an answer.

### 1. Pre-flight discovery — silent

Resolve everything code can answer before asking anything. The full list is in
interview.md; the spine of it: framework and provider stack → which
integration rules apply; every entry point's shape → where conversations and
turns go; which handlers return before their work is done → where `wrap()` is
mandatory; whether LangChain/LlamaIndex already report the tools → what must
NOT be decorated; every candidate tool's full signature → the data-consent
question; shutdown hook, worker config, secret handling → deployment wiring;
decision logs/ADRs → a standing decision that touches observability is a
blocking question, not something to integrate over; contract-pinning tests
(golden files, frozen wire bytes, AST walkers, env-file completeness checks)
→ the guardrails the integration must land inside. Work in the live repo
only — skip snapshot/backup copies, vendored code, and virtualenvs.

While reading, also collect the conversation-id candidates and check each
handler for what is reachable there (user id, IP, device, language, source).

### 2. Findings summary, then the interview

Present what you determined as a short findings summary, then run the
interview per interview.md: Tier 1 (blocking) first; Tier 2 plus the
triggered Tier 3 rows as one batch, every question carrying its findings and
its default. Never ask what the code already answered; never ask questions
one at a time; never stall on silence — take the default and name it in the
report.

### 3. Write AGENTSIGHT.md

Persist the answers, defaults taken, and named gaps to the target repo root
using the template in interview.md — before implementing, so the record
exists even if the run stops early.

### 4. Implement

The judgment calls, in the order they usually bite:

- **`init()` once, at startup, in the worker process** — with the shutdown
  hook wired in the same edit (lifespan / `worker_shutdown` / SIGTERM
  handler). SIGTERM does not flush; this is the one thing that needs the
  developer's code.
- **Honest form over shortcut.** `turn(id_from=…, infer=True)` fits only a
  handler that really is `(text) -> str` with the human's own words.
  Everywhere else, explicit `user_message()` / `agent_message()` — the
  one-sentence justification: *inference would put the wrong text in a
  transcript the developer's client reads.*
- **`wrap()` on any handler that returns before the work is done**, and
  `agent_message()` on the generator's last line. Queued/websocket
  completions get `keep_open()` and the held `TurnScope`. Get this from
  streaming-and-lifetime.md, not from memory.
- **Decorate only what the framework cannot see.** Framework-reported tools
  arrive undecorated; decorating them records doubles.
- **Name the handoff tool** one of `fallback_to_human` / `open_ticket` /
  `ticket` / `contact_human` (as the interview settled), or the escalation
  metric stays empty.
- **Respect the consent list.** Functions the developer said to skip stay
  uninstrumented; refactors they approved happen before decoration.
- **Environment per deployment**, QA/eval traffic to `development` or
  `enabled=False`.
- Match the codebase's own style; the integration should read as if the
  repo's authors wrote it.

### 5. Verify — before any claim of success

Run the app with `AGENTSIGHT_FILE_EXPORTER` set, exercise the real entry
points, and work through verification.md's checklist against the JSON it
wrote. With a key, follow with the development-environment smoke test and the
dashboard's Development Mode tracking view. **An integration that has not
been read back is not done.**

### 6. Report

Lead with what now gets recorded and where to see it. Then: every explicit
call justified in one sentence; defaults taken; named gaps with the single
change that closes each; verification evidence; the ship checklist
(shutdown wired · environment set · `export_interval_ms` sized ·
file exporter unset in production).

## Hard rules

- Tracking calls never raise — so **absence of errors is not evidence of
  correctness**. Only the verification loop is.
- Never claim automatic where it isn't. Direct Bedrock/Vertex/Ollama/LiteLLM
  calls, `with_streaming_response`, and unnamed models are gaps to name, not
  to paper over.
- Message content, tool arguments and results leave the process; LLM prompts
  and completions never do; there is no field-level redaction. The consent
  question is asked per function, with real signatures, and any hesitation is
  answered with the file-exporter dump — the actual bytes, offered.
- The conversation id is the developer's durable business id. Never ship a
  generated id for a real thread.
- A wrong `AGENTSIGHT_ENVIRONMENT` fails silently (development is excluded
  from analytics by design). Say where production is configured in the
  report.
- No key is not a blocker: deliver the integration against the file exporter
  with switch-to-live steps.
