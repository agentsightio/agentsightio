# Metrics: what powers what

Every metric the dashboard shows, mapped to the code that feeds it. Use this
to answer "why is this chart empty?" before it gets asked — and to make any
question to the developer about fields and metrics concrete.

## Three categories

- **Automatic** — computed from what the SDK already records. No setup.
- **Conversation-passed** — need a field only the application has, passed on
  the conversation (or as kwargs to a decorated handler — same fields).
- **Specialized** — keyed to specific actions, calls, or feedback.

## Automatic metrics

| Metric | Fed by |
|---|---|
| Total Messages | every recorded message |
| Total Conversations | unique `conversation_id` values |
| Average Agent Response Time | the turn itself — the exchange is timed, not inferred from timestamps |
| Peak Hours | message timestamps |
| Messages & Conversations Overview | daily aggregates |
| Average Conversation Duration | conversation lifecycle timestamps |
| Tool Usage & Average Duration | each `@tool` / `@task` call (and framework-reported tools) — the decorator times the function |
| Token Usage & Cost | instrumented providers/frameworks; priced server-side; an unknown model reads **unpriced**, never free |

Consequence worth stating: a missing `wrap()` corrupts Average Agent Response
Time (near-zero turns) — automatic does not mean unbreakable.

## Conversation-passed metrics

| Metric | Field | Notes |
|---|---|---|
| Individual Users | `customer_id` | unique per user; omit it and the card reads 0 |
| World Map | `customer_ip_address` | geolocated on the dashboard; must parse as an IP or it is dropped |
| Device Usage | `device` | `"desktop"` / `"mobile"` / `"tablet"` or the product's own vocabulary |
| Agent Language | `language` | charts group the exact strings sent — pick one code style and stick to it |
| Source | `source` | **recorded but not yet surfaced** — no dashboard, filter, or API response shows it today. Worth sending for the record; not something to build on. Say this honestly. |

For each field, establish from the code: available at the handler / needs
plumbing / not available — and where plumbing is needed, the developer
chooses: skip, wire-empty, or build the propagation.

## Specialized metrics

### Human Escalation Rate

Detected **from action names**. An action named exactly one of:

```
fallback_to_human   open_ticket   ticket   contact_human
```

counts as a human escalation. The same function named `escalate`,
`transfer_to_agent`, or `handoff` shows up in tool usage and scores zero
escalations. The fix costs one line:

```python
@agentsight.tool(name="fallback_to_human")
def hand_off(reason: str) -> str: ...
```

Name the handoff candidates found in the code and let the developer confirm.
Default if unanswered: not renamed, escalation rate stays empty, flagged.

### Conversation Feedback

Collected wherever users give it — the developer's chat UI — and delivered via
the API client: `feedbacks.create_for_conversation(conversation, sentiment,
comment=None)` with sentiment `positive` / `neutral` / `negative`. See
[data-plane.md](data-plane.md). Not wired by default; reported as a gap.

### Unique Interaction

The one metric a decorator cannot express: by the time a handler fires,
somebody already typed, so the visit has become an interaction.
`agentsight.open_conversation(id, **fields)` records that the conversation
exists **before** any exchange does; the first turn is what marks it engaged.
That separates "the widget loaded" from "the user said something". Needs a
backend-reachable "widget opened" signal from the developer's own frontend —
ask whether one exists. It arrives within one export interval, which for a
widget-loaded event changes nothing.

## Environments and where numbers land

Every agent has **production** and **development** (custom slugs possible
server-side; the SDK learns them at startup). Conversations record against
**production unless an environment is selected.**

| | Development | Production |
|---|---|---|
| Transcripts, messages, actions, attachments | ✅ | ✅ |
| Analytics & reports | ❌ excluded by design | ✅ |

Development Mode in the dashboard shows **which metrics are receiving data**
instead of charts — the way to confirm an integration is landing without test
runs skewing production numbers. This is also why a mis-set environment fails
silently: a production deploy recording to `development` produces no
analytics and no error.

Set once per deployment (`AGENTSIGHT_ENVIRONMENT` or `init(environment=…)`;
`dev`/`prod` accepted as shorthand). A single conversation can override it —
`conversation("eval-41", environment="development")` — which is the right home
for QA and load-test traffic (or `enabled=False` when it should not be
recorded at all). An unrecognised slug errors in the logs at startup; on a
conversation it costs the environment tag, never the data.

## Data entities: one agent, many clients

One central agent serving many clients, each with its own data: one
hotel-booking agent, many hotels. This is the native shape for it. Each
conversation carries a key the developer chooses, the dashboard filters by it,
and an embed token can be pinned to one client. `metadata` gives none of that,
and one agent per client multiplies agents and keys.

```python
with agentsight.conversation(session_id, data_entity=hotel_code):
    ...
```

| Situation | Result |
|---|---|
| No key | Unassigned; nothing is created. Existing conversations are all here. |
| Unknown key | entity created on first sight, named after its key |
| Known key, any casing | linked; `"Hotel-Paris"` and `"hotel-paris"` are one entity, first spelling kept |
| Key of a deleted entity | linked anyway; flagged as still receiving traffic, with Restore |
| Unknown key, agent at 500 active | Unassigned, and the agent's overflow counter goes up; known keys keep working |
| Later key, different from the one set | ignored; the first stays |
| Later key, none set yet | linked now, and earlier usage moves with it |

- **Choose the source carefully, because both the key and the link are permanent.**
  A key cannot be renamed (its display `name` can), and a conversation cannot be
  moved to another entity. Use a stable identifier, never a session or user id.
  Ask the developer which one; do not guess.
- **A default or per-conversation keys, not both.** `init(data_entity=…)` /
  `AGENTSIGHT_DATA_ENTITY` means the deployment serves one client. A key named on
  the conversation, or on a turn before anything is recorded, beats the default.
  Anything recorded first goes out under the default and the first key sticks:
  `open_conversation(cid)` without the key is the usual case.
- **Uploads.** `upload_attachments()` sends the key only inside the conversation's
  own scope. Elsewhere it sends none, and the next span supplies it.
- **Independent of environments.** One entity list per agent, across environments,
  and filters compose. Analytics stay production-only, and the entity filter
  narrows that report. The Development Mode probe stays agent-wide.
- **Filters are not isolation.** An API key sees its whole agent, so a filter only
  narrows what the developer's own code reads. To show a client only its own
  data, use a scoped embed token: [embed.md](embed.md).
- **Coverage.** Analytics report, conversations, feedback, tickets, token usage,
  saved reports. Agent-level feedback and tickets without a conversation appear
  only under All. Imported history has no entity today.
