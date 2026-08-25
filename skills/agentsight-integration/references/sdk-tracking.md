# The tracking SDK

The recording half of AgentSight. `import agentsight` — every call on this
plane **never raises and never blocks**; misuse is dropped (with a debug log),
not thrown at the application. The read/write API client is the other plane —
see [data-plane.md](data-plane.md).

Install: `pip install agentsight` (Python ≥ 3.9). If `python-dotenv` is
installed, importing `agentsight` loads `.env` automatically.

## Contents

- [init() and configuration](#init-and-configuration)
- [Environment variables](#environment-variables)
- [Conversations](#conversations)
- [Turns](#turns)
- [Messages](#messages)
- [Tools and tasks](#tools-and-tasks)
- [The visit phase: open_conversation()](#the-visit-phase-open_conversation)
- [Metadata after the fact](#metadata-after-the-fact)
- [Buttons](#buttons)
- [Attachments](#attachments)
- [Limits and what is sent](#limits-and-what-is-sent)

## init() and configuration

Call once per process, at startup, in the process that does the work:

```python
agentsight.init(
    api_key=None,            # else AGENTSIGHT_API_KEY
    endpoint=None,           # else AGENTSIGHT_API_ENDPOINT; default https://api.agentsight.io
    environment=None,        # else AGENTSIGHT_ENVIRONMENT; "production"/"development" (+ "prod"/"dev")
    auto_instrument=True,    # True | False | list from: "openai", "anthropic", "langchain", "llama_index"
    export_interval_ms=5000, # batch send interval — size to worker count, see below
    max_queue_size=2048,
    turn_timeout_ms=300_000, # the deadline for handed-off turns; 0 disables
    span_exporter=None,      # any OTel SpanExporter; replaces HTTP transport
    verify_key=True,
)
```

- Returns `bool` — whether tracking is active. **Never raises.** A missing or
  malformed key logs an error and leaves the SDK a pass-through, so the app
  runs identically either way.
- A keyword argument always beats the matching environment variable.
- A second `init()` in the same process is ignored (logged at DEBUG). One
  process, one initialisation — in pre-fork servers that preload the app,
  `init()` belongs in the post-fork/worker-startup hook, not module import in
  the parent.
- `verify_key=True` checks the key in a background thread and logs loudly for
  the failures worth catching at startup: refused key, inactive subscription,
  and a **read-role key** (recording needs write). It never blocks or raises.
  The same call teaches the SDK the agent's environment list, so custom
  environment slugs resolve.
- A pattern worth copying in apps whose test suite boots the app: gate the
  `init()` call on configuration being present — call it only when
  `AGENTSIGHT_API_KEY` or `AGENTSIGHT_FILE_EXPORTER` is set. A keyless
  `init()` already stays a safe pass-through, but skipping it entirely keeps
  test logs free of missing-key errors and makes activation a deployment
  fact: configuration decides *whether* anything records, code decides
  *what*.
- `auto_instrument` misspellings are skipped silently — copy target names
  exactly from the list above.

**Sizing `export_interval_ms`:** sending is a per-process rate spent against a
per-agent allowance, so what matters is the interval divided across worker
count. Raise it as workers grow; lower it when the count is small and the
dashboard should keep up. The SDK warns on the `agentsight` logger (once a
minute) before the queue fills, naming `max_queue_size`,
`export_interval_ms`, and API reachability. Nothing reads its own data back —
the only cost of a longer interval is freshness.

## Environment variables

| Variable | Effect |
|---|---|
| `AGENTSIGHT_API_KEY` | the key (`ags_…`), when not passed to `init()` |
| `AGENTSIGHT_API_ENDPOINT` | base URL; default `https://api.agentsight.io` |
| `AGENTSIGHT_ENVIRONMENT` | deployment-wide environment slug |
| `AGENTSIGHT_FILE_EXPORTER` | a **directory** — spans are written there as JSON and **nothing is transmitted**; `init()` says so at INFO. The verification loop is built on this: see [verification.md](verification.md). Must be unset in production. |

## Conversations

The thread a customer would recognise, and the only thing the developer names
themselves. Everything else files under it.

```python
with agentsight.conversation("wa-3859", customer_id="user-456", device="mobile"):
    ...
```

- The id is a **business string the developer controls** — the same id
  tomorrow is the same conversation, across restarts, deploys and processes.
  Omitting it generates a throwaway id nothing can ever tie back to a
  customer; never do that for a real thread. (This is Tier 1 question 2.)
- Works as context manager, async context manager, and decorator. The
  decorator builds a fresh scope per call — without an explicit id that means
  one conversation per invocation, so pass an id or use `turn(id_from=…)`.
- The scope produces no span of its own; its fields are stamped on everything
  recorded inside it. **Nothing records outside a conversation scope**:
  decorators become pass-throughs, `button()` / `record_attachments()` /
  `update_metadata()` are dropped with a debug line. That is the usual reason
  an expected action is missing.

Fields (all optional, keyword-only): `customer_id`, `customer_ip_address`
(must parse as an IP or it is dropped), `device` (`"desktop"`, `"mobile"`,
`"tablet"`, or the product's own vocabulary — free text), `source`,
`language`, `name` (human-readable title), `environment` (per-conversation
override, wins over the deployment default), `metadata` (free-form dict),
`enabled` (pass `False` and everything inside the scope is a no-op — for test
and eval traffic that must not land in customer numbers).

What each field powers on the dashboard: [metrics-and-fields.md](metrics-and-fields.md).
Note there that `source` is recorded but not yet surfaced.

## Turns

One exchange: the user asks, the agent works, the agent answers. The turn's
duration **is** the answer latency — measured, not approximated — and every
tool and LLM call inside nests under it without being mentioned.

Three call shapes:

```python
with agentsight.turn():                    # context manager (also async with)
    ...

@agentsight.turn                           # bare decorator
def handle(...): ...

@agentsight.turn(id_from="session_id", source="web")   # configured decorator
def handle(session_id: str, text: str) -> str: ...
```

- `turn("ask")` — an optional name, worth spending when exchanges come in
  meaningfully different kinds (`ask`, `escalate`, `follow_up`).
- `id_from=` names the handler parameter that carries the conversation id — or
  takes a callable over the bound arguments for ids nested in payloads:
  `id_from=lambda args: json.loads(args["data"])["conversation_id"]`. The
  decorator opens the conversation around the exchange; any conversation
  field passed to it goes onto that conversation.
- `infer=True` opts into inference: first string argument → user message,
  return value → agent message. **The exception, not the rule** — it is only
  right when the handler really is `(text) -> str` with the human's own words.
  If the text was translated, scrubbed, or rewritten before reaching the
  variable, inference records the wrong string in a client-facing transcript.
  When in doubt, use explicit messages.
- Used as a decorator, `turn()` sees the return value and hands the turn's
  lifetime over by itself when the handler returns a streaming response,
  generator, or future. The `with` form cannot see the return value — that is
  what `wrap()` is for: [streaming-and-lifetime.md](streaming-and-lifetime.md).
- A `turn(...)` bound to a variable can be re-entered (two exchanges, two
  turns), and turns nest.

## Messages

```python
agentsight.user_message("Where is my order?")
agentsight.agent_message("Order A-1 ships tomorrow.", metadata={"model_route": "fast"})
```

**Messages have no rules**: any count, any order, either sender. Bursts,
reply-plus-card, silent escalations (a user message, a tool call, no answer),
proactive agent messages — all legal shapes. Each message carries its own
timestamp; recording them as they happen is enough. A message recorded outside
a turn gets a one-off turn opened and closed around it, so it always has
somewhere to live.

They are explicit by design. The one-sentence justification to give the
developer: *inference would put the wrong text in a transcript your client
reads — a rewritten prompt instead of what the human typed — so the SDK only
records the strings you hand it.*

## Tools and tasks

A tool is a unit of work with a measured duration, and it becomes an
**action** on the dashboard — how "what did the agent actually do?" gets an
answer the client can see.

```python
@agentsight.tool
def search_orders(customer_id: str, status: str = "open") -> list: ...

@agentsight.task
def rerank(candidates: list) -> list: ...
```

- Identical rows, different word: a **tool** is something the agent calls out
  to; a **task** is internal work. Nothing downstream treats them differently.
- Both work bare or configured (`@agentsight.tool(name="…")`), sync or
  `async def`.
- Recorded: real start/end boundaries, measured duration, the bound arguments
  (defaults applied, `self` dropped), the return value, the error if raised.
  **A failed call is still recorded and the exception propagates untouched.**
- **Arguments and results are captured in full** (up to size limits). A tool
  that takes a credential or returns a full customer record sends exactly
  that — which is why Tier 1 question 4 goes function by function.
- **The name is load-bearing**: an action named `fallback_to_human`,
  `open_ticket`, `ticket` or `contact_human` counts as a human escalation;
  the same function named `escalate` does not.
- **Never decorate a tool LangChain or LlamaIndex already reports** — that
  records two spans per call. Decorate only what the framework cannot see:
  functions called directly, work outside the agent loop.
  See [frameworks.md](frameworks.md).
- Overhead ≈ 100 µs per call — only relevant on instant functions in tight
  loops.
- Dashboard labels (`display_name`, `description`) do not travel with calls;
  set them once via the API client: `ags.actions.update(id, display_name=…)`.

## The visit phase: open_conversation()

Someone loaded the widget and typed nothing. No decorator can record that — a
decorator fires only after somebody engaged:

```python
agentsight.open_conversation("wa-3859", device="mobile", source="web")
```

Takes the same fields as `conversation()`, records that the conversation
exists, marks nothing as engaged. Any tracked activity — in practice, the
first turn — marks engagement. That difference is what the Unique Interaction
metric measures. This is a call on the developer's **backend**, reached from
their own chat frontend's "widget opened" signal; it is unrelated to
AgentSight's embeddable dashboard.

## Metadata after the fact

The scope takes metadata at the top of the handler — before most of what is
worth recording has happened. `update_metadata()` is the same field afterwards:

```python
agentsight.update_metadata({"topic": "delivery", "self_served": False})
agentsight.update_metadata(remove=["awaiting_reply"])
```

Four rules: it merges (does not replace); the merge is shallow (a nested dict
is replaced whole); no value is filtered (`False`, `0`, `""`, `None` are
data); `remove=` is the only deletion. Needs an active conversation scope. The
merge is against what this process knows — when the previous state lives only
on the server (conversation already closed, other process wrote it), use the
API client's `conversations.update_metadata()`, which reads before it writes.

## Buttons

```python
agentsight.button("clicked", label="Track order", value="track_a1")
```

Recorded and archived with the conversation — but **not yet surfaced**: no
dashboard view or read API today. Wire it only if the developer wants the
record; do not promise a view.

## Attachments

Two calls with different trust models — this is the descriptors-vs-bytes
question in Tier 2:

- `agentsight.record_attachments(files, sender="end_user", metadata=None)` —
  tracking plane; records **descriptors only** (filename, type, size), never
  bytes; never raises; needs an active conversation scope.
- `agentsight.upload_attachments(files, conversation_id=None, sender="end_user",
  metadata=None, timeout=30, message_id=None)` — **the one SDK call that blocks
  and raises.** `message_id` attaches the files to an existing message instead
  of the backend creating a `[Attachments]` message for them (404 →
  `UploadError` if it is not in that conversation). Without it the created
  message is stamped at upload time; no parameter overrides that, so a
  background upload that must land in its own turn passes `message_id`.
  Uploads the actual bytes over HTTP. Raises `ValueError` for caller mistakes
  and `agentsight.UploadError` (with `.status_code`, `.response`) when the
  backend refuses or the network fails. Limits: 25 MB per file, 10 files per
  request, 40 MB per request. Accepts paths, open file objects, or
  `{"filename": …, "data": …}` dicts. Requires the real HTTP transport — a
  file exporter cannot carry bytes.

Default to descriptors; bytes leaving the process is the developer's explicit
call.

## Limits and what is sent

The full wire disclosure is the docs page "What the SDK sends"
(`docs.agentsight.io/getting-started/what-the-sdk-sends`) — point the
developer at it for the privacy conversation. The load-bearing facts:

- Message content, tool arguments/results, and error strings are truncated at
  16 384 characters. Conversation string fields are clamped at 255. Metadata
  has a 16 KB JSON budget (oversized entries dropped largest-first, marked,
  always leaving valid JSON). Values are kept honest on the way out — nothing
  raises, nothing else in the batch is lost.
- **LLM prompts, completions, and embedding vectors are never sent.** LLM
  records carry accounting only (model, token counts, timing, error class).
- Exception stack traces are sent and carry the app's file paths.
- The SDK sends no service identity of the app: `service.name` is
  `agentsight-python`, not the app's name.
- **There is no field-level redaction.** The controls are: don't instrument a
  function, don't record a message, `enabled=False` on the scope, narrow
  `auto_instrument`, or no key at all.
- Data is kept indefinitely; deletion via the API is soft. Say this plainly
  when retention comes up.
