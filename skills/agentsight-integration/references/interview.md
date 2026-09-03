# The integration interview

Code answers most questions. This file is about the ones it cannot — and the
discipline that keeps them few, batched, and cheap to answer.

## Contents

- [What you resolve yourself, silently](#what-you-resolve-yourself-silently)
- [Tier 1 — blocking questions](#tier-1--blocking)
- [Tier 2 — shaping questions, each with a default](#tier-2--shaping)
- [Tier 3 — conditional questions](#tier-3--conditional)
- [Rules that make the asking work](#rules-that-make-the-asking-work)
- [The decision record: AGENTSIGHT.md](#the-decision-record-agentsightmd)

## What you resolve yourself, silently

Never ask about any of this. Resolve it from the code during pre-flight and put
it in the findings summary so the developer sees what was already determined:

- Framework and provider stack (OpenAI / Anthropic / LangChain / LlamaIndex /
  direct HTTP), and therefore which integration reference applies.
- Sync vs async, and the shape of every entry point and handler.
- Which endpoints stream or defer work — and therefore where `wrap()` (or the
  decorator form) is required.
- Existing decorators around candidate tools, and where `@agentsight.tool`
  nests among them (closest to the function, so the recorded arguments are the
  real ones).
- Whether LangChain/LlamaIndex already report the tools — and therefore what
  must NOT be decorated (a decorated framework tool records twice).
- Whether a lifespan/shutdown hook exists, and where `shutdown()` would wire in.
- Worker/server configuration if it is in-repo (worker count sizes
  `export_interval_ms`).
- How the CI/deploy pipeline provides secrets (where `AGENTSIGHT_API_KEY`
  would live).
- Queue and websocket completion paths (where a turn's reply actually lands —
  this decides `wrap()` vs `keep_open()`).
- The full signature list of every candidate tool function — names, parameters,
  what each returns. Tier 1 question 4 is built from this list.
- **Recorded decisions and guardrails.** Search the repo's decision log, ADRs,
  and dependency-file comments for standing decisions about observability,
  egress, or vendors — one may forbid exactly this integration (that becomes
  Tier 1 question 8). Find the tests that pin contracts your edits could
  brush against: golden files, byte-frozen wire contracts, AST-walking tests,
  env-file completeness checks. Real production repos guard themselves; the
  integration must land inside those guardrails, not around them.
- **The existing stack.** Whether conversation history is already persisted —
  ORM models or tables named for conversations, messages, chat history, or a
  memory/vector store — and whether an observability or LLM-tracing SDK is in
  the dependency file (`langfuse`, `langsmith`, `opentelemetry-*`,
  `sentry-sdk`, `datadog`, `helicone`, `arize-phoenix`, `braintrust`,
  `weave`). Tier 1 question 1 is built from this.
- Work only in the live repo — skip snapshot/backup copies of it (sibling
  `*.snapshot-*`, `*-backup` directories), vendored code, and virtualenvs.

## Tier 1 — blocking

Wrong guesses here are unrecoverable or unsafe. Ask all of Tier 1 in the first
wave, findings attached.

### 1. Add-on alongside what you already run, or the primary store?

Ask this first: it moves the defaults on almost everything below. Present what
pre-flight found — the conversation tables or ORM models, and any observability
SDK in the dependency file — and offer the two shapes:

- **Add-on.** Their database or observability platform stays the system of
  record; AgentSight adds the analytics, the transcripts, the client-facing
  dashboard and the tickets on top of a system that already works. Nothing is
  replaced, and they can stop at any point without unpicking their storage.
- **Primary.** AgentSight is where conversation data lives — either there is
  nothing else, or the something else is being retired.

Two things to state unprompted, because they change the answer and the
developer cannot know them:

- **Nothing collides.** The SDK uses a private tracer provider and registers no
  global one, so it captures none of an existing tracer's spans and they
  capture none of its. Running both is ordinary, not a workaround.
- **Cutover is where live recording starts; history is a separate job.** The
  tracking SDK is the only way live traffic gets in, so the dashboard begins
  at cutover. Existing transcripts can be brought over afterwards by a
  one-off bulk import the developer uploads in the dashboard — that is the
  `agentsight-migration` skill's job, not this one. Say so rather than
  promising it here, and say what it does *not* carry: an import brings
  conversations and their messages only, so token, cost and geolocation
  charts stay empty for imported history permanently. If the developer wants
  their old data in, finish the integration first and route them there.

*Default: add-on when pre-flight found an existing conversation store or a
tracing SDK; primary when it found neither.* Guessing add-on is recoverable —
the developer asks for more. Guessing primary means plumbing, propagation and
edits across files they never wanted touched.

### 2. Which conversation id do we use?

Propose the candidates found in the code (`session_id`, `thread_id`,
`chat_id`, …) and ask which is the **durable, business-level thread id**. Code
shows the variables; it cannot show which one survives a restart, which is
per-visit, and which id the developer's support team actually quotes. The id is
what the dashboard files everything under and what a client searches — a
generated or per-visit id makes every conversation an orphan.

Follow-up in the same question: **is that id PII?** A WhatsApp thread id is a
phone number. Hashing before sending protects it — and costs the developer
lookup by the id they know. Their call, made explicitly.

*No default.* An integration with the wrong id is not a smaller integration;
it is wrong data.

### 3. One AgentSight agent, or one per end client?

An API key belongs to exactly one agent, and tracking is initialised once per
process. If each of the developer's customers should get their own dashboard,
that is either separate deployments (one key each) or one agent with a tenant
tag in `metadata` — decided now, because it shapes `init()` and every
conversation call. Metadata filters can slice one agent's data by tenant;
separate agents keep the data (and the embed dashboards) fully apart.

*No default.*

### 4. Do you accept what leaves the process?

Message content, tool arguments, tool return values, metadata, and exception
stack traces (which carry file paths) are transmitted and stored. LLM prompts
and completions are never sent — LLM records carry accounting only. There is
**no field-level redaction**: the controls are which functions you decorate,
which messages you record, and `enabled=False` on a scope.

Do not ask this generically — a generic privacy question gets a generic yes.
Present the concrete list from pre-flight: "these 7 functions are tool
candidates; `charge_card(token, amount)` and `verify_identity(national_id)`
would send those argument values." Ask **per function**: instrument, skip, or
refactor the signature so the sensitive value doesn't pass through it.

The per-function choice applies to functions *you* would decorate. Tools a
framework already reports (LangChain, LlamaIndex) are recorded by the
framework handler, **all-or-nothing** — there is no per-tool skip. When the
candidates are framework tools, present that honestly and offer the real
options: record them all (the 16 KB truncation caps bulky returns; name the
risky ones in the report), drop the framework handler entirely (tool spans
and the escalation metric go with it), or refactor the sensitive tool's
signature so the value never enters it.

If there is any hesitation, offer the payload dump: run once with
`AGENTSIGHT_FILE_EXPORTER` set and hand over the actual bytes that would have
been sent. Offer it — don't argue.

*No default for sensitive-looking functions. Functions with plainly harmless
signatures may default to instrument, listed as such in the findings.*

### 5. Which conversation fields can you supply — and for the rest, stub or skip?

Go per field — `customer_id`, `customer_ip_address`, `device`, `language`,
`source` — with what pre-flight found: **available at the handler** / **needs
plumbing** / **not available**. For anything needing plumbing, the choice is:

a. skip the metric (named gap in the report),
b. wire the call now with the value left empty, so it lights up when the
   plumbing lands, or
c. build the propagation — which, if it crosses into another repo or service,
   needs its own answer about access.

For `customer_ip_address` specifically: the code shows whether the app is
behind a proxy, but not **which forwarded element is the real client** — that
is the developer's infrastructure config, so ask. The value must parse as an
IP address; anything else is dropped rather than sent.

*Default: send what is available at the handler; skip the rest as named gaps.*

### 6. Which parts of this codebase must not be touched?

Frozen modules, vendored or generated code, another team's directories,
latency-critical paths. Nothing in a repo says "don't edit me" — ask.

*Default: only the files the integration plan names, listed in the findings
before editing.*

### 7. Which deployment is production, and where does the key live?

Map deployments to environments and settle the secret's home. This is Tier 1
because a mis-set environment fails silently: development data is excluded
from analytics **by design**, so a production deployment recording against
`development` looks like silence, not an error. Ask which deploy target is
production, and where `AGENTSIGHT_API_KEY` / `AGENTSIGHT_ENVIRONMENT` should
be configured for each.

If no key is available yet, fall back to `AGENTSIGHT_FILE_EXPORTER` and
deliver a reviewable payload dump instead of a live integration — a complete
integration minus the key is still a deliverable.

*Default when unanswerable: file exporter, with the switch-to-live steps
written into the report.*

### 8. Does a recorded decision forbid this? *(ask only when pre-flight found one)*

A decision log, ADR, or dependency comment saying "no external observability",
"no AI tracing", or "prompt content may not leave the network" is a standing
decision the developer's team wrote down — integrating over it silently is
never yours to decide, however confident the current request sounds. Present
the decision verbatim with where it lives, state precisely what AgentSight
does and does not send against the concern it encodes (LLM prompts and
completions never travel; message text and tool arguments/results do), and
offer: amend the decision — recording the amendment in the same log, so the
log stays the truth — or integrate in file-exporter mode, which transmits
nothing and leaves the decision intact.

*No default. A written decision outranks an enthusiastic request until its
author amends it.*

## Tier 2 — shaping

Ask these in **one batch** after Tier 1. Every one has a default, so silence
on any of them still produces a working integration — with the default named
in the report.

| Question | Default if unanswered |
|---|---|
| Beyond the automatic metrics, which do you want? | all automatic metrics, plus every conversation field derivable from the code |
| What is `customer_id` in your system — and what for logged-out users? | the user id if one is obvious; omitted otherwise |
| Confirm the human-handoff function (name the candidates found). It must be named exactly one of `fallback_to_human`, `open_ticket`, `ticket`, `contact_human` to count as an escalation. | not renamed — escalation rate stays empty, flagged in the report |
| Do you collect feedback in your UI today, and should I wire it (`feedbacks.create_for_conversation()`)? | not wired, reported as a gap |
| Is there a "widget opened, nobody typed" signal reachable from the backend? (This is about the developer's own chat UI — see note below.) | `open_conversation()` not wired — Unique Interaction unavailable, named gap |
| Users share files — record descriptors only (`record_attachments()`), or upload the bytes (`upload_attachments()`)? | descriptors only; bytes leaving the process is the developer's explicit call |
| Should batch/cron/eval LLM calls be counted, or excluded from client-facing cost? | left untracked (no conversation scope around them records nothing) |
| Metadata keys worth agreeing up front? (Dashboard filters get built on these.) | none beyond what is already obvious in the payload |
| Client-facing names for actions (`actions.update(display_name=…)`)? | function names as-is, with a labelling pass proposed in the report |
| Controlled values for `device` / `language` / `source`? | lowercased, as found in the code; note that charts group the exact strings sent, so `"en"` and `"English"` become two slices |
| Worker count, if not in-repo? | `export_interval_ms` left at 5000, with a sizing note in the report |
| Retention or erasure obligations? | none assumed; the report states plainly: data is kept indefinitely, deletion is soft |
| How should QA and load-test traffic be handled? | recorded against the `development` environment (or `enabled=False` where it should not be recorded at all) |

**How the adoption mode moves these defaults.** Add-on pulls every judgment
call toward the lightest thing that still produces good analytics: fields that
need plumbing get wired-empty or skipped rather than propagated, attachments
stay descriptors because the bytes already live in their store, and the
conversation id has to be the id their own store keys on — otherwise the two
sets of rows cannot be joined, which is the whole reason to run both. Primary
pulls the other way: the plumbing is worth building, because there is no
second place to look anything up.

**The widget-opened note.** The signal for Unique Interaction comes from the
developer's own chat frontend reaching their backend — `open_conversation()`
is a backend SDK call. It has nothing to do with AgentSight's embeddable
dashboard, which displays data and records none.

## Tier 3 — conditional

Ask only the ones whose pre-flight trigger actually fired. They join the same
batch as Tier 2.

| Trigger found in the code | Question |
|---|---|
| Text is transformed before the agent sees it (translation, PII scrub, RAG rewrite) | "I found `raw_text` and `normalized_text`. Which is what the human actually typed?" The transcript is client-facing; recording the rewritten string puts the wrong words in the customer's mouth. This is why `infer=True` is the exception — inference cannot tell these apart. |
| A model wrapper resolves no model name | "What model is behind `MyLLM`?" A call with no name is permanently unpriceable; `model_hint()` needs a value only the developer has. |
| Direct Bedrock / Vertex / Ollama / LiteLLM calls, no framework in the path | These produce no LLM record — nothing in the path announces the call. Route through a framework, wrap the call in `@agentsight.task` for shape and duration only, or accept the gap? |
| `with_streaming_response` in use | Those call sites produce no span and their tokens go uncounted (ordinary `stream=True` is fully recorded). Accept, or switch those call sites? |
| LangChain cache enabled | Cache hits report tokens nobody was billed for; token totals become an upper bound. Accept? |
| No shutdown hook found | "May I add `agentsight.shutdown()` to your lifespan/signal path?" SIGTERM — how containers stop — does not flush; an orderly exit does. |
| Server preloads the app before forking workers | `init()` must run in each worker process, not the parent — it has to move into the post-fork hook. "May I edit that config?" |
| A redelivering channel or a retrying client in front of the handler (webhook redelivery, a frontend that retries failed requests) | Is there idempotency on the retry? The SDK records what the handler runs: a delivery that runs the handler again records the exchange again — and if each retry genuinely re-runs the model, recording it twice is the honest accounting of real spend. |
| A human-takeover path exists | Should a human's reply be recorded as an agent message — and marked as human in message metadata so the transcript stays honest? |
| Multiple services in the conversation path, one repo in scope | Recording goes through the SDK, so: instrument this service and propagate the conversation id and fields into it from the others — or produce a written spec of what the other services must pass along? (Feedback and reads are available to any language over the REST API; recording is not.) |

## Rules that make the asking work

1. **One batch, not a drip.** Tier 1 goes out first (its answers can change
   Tier 2's questions), then Tier 2 plus the triggered Tier 3 rows together.
   In a harness with a structured question tool (Claude Code's
   AskUserQuestion), send consecutive waves of up to four questions with the
   recommended default marked; in any other harness, present the whole
   numbered list in one message. Never one question per message.
2. **Every question arrives with what you already found.** "Which of these
   three ids?" gets answered; "what is your conversation id?" gets a shrug.
   The findings summary travels with the questions.
3. **Every Tier 2/3 question has a default, and the report says which
   defaults were taken.** Silence produces a working integration with named
   gaps — never a stall.
4. **Answers get written down** in `AGENTSIGHT.md` (next section), so a re-run
   reads instead of re-interrogating.
5. **The payload dump is offered, not requested.** Any hesitation on Tier 1
   question 4 → run with `AGENTSIGHT_FILE_EXPORTER` and hand over the actual
   bytes rather than arguing about them.

## The decision record: AGENTSIGHT.md

Write the answers to the target repo's root as `AGENTSIGHT.md` after the
interview, before implementing. If that name is already taken by a file that
is not this record, use `AGENTSIGHT_INTEGRATION.md` instead and say so in the
report — never overwrite a file you did not write. On any later run, read the
record first (checking both names): **answers recorded there are binding** —
re-ask only what it does not cover, and update the file when the developer
changes an answer.

Template:

```markdown
# AgentSight integration record

Written by an integration run on <date>. These answers are binding for
re-runs: update this file rather than re-answering.

## Identity
- Adoption: <add-on alongside <what> | primary store>; existing stack: <what pre-flight found, or none>
- Conversation id: `<variable>` — <why it is the durable thread id>; PII: <no / hashed with …>
- Topology: <one agent | one agent per end client via …>; tenant tag: <metadata key or n/a>
- Environments: production = <deploy target>, key lives in <secret store / env file>
  - `AGENTSIGHT_ENVIRONMENT` per deployment: <mapping>

## What leaves the process
- Instrumented tools: <name(sig)>, …
- Skipped (data consent): <name — reason>, …
- Refactored signatures: <name — what changed>, …

## Conversation fields
| Field | Decision |
|---|---|
| customer_id | <value / skipped / wired-empty> |
| customer_ip_address | <header used / skipped> |
| device | <derivation> |
| language | <derivation> |
| source | <value> |

## Answers and defaults taken
- <question>: <answer, or "default: …">

## Named gaps
- <metric or signal>: <why, and what would close it>
```
