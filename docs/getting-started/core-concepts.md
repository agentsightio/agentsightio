---
outline: deep
---

<CopyMarkdownButton />

# Core Concepts

There are four things to model. Everything else in the SDK is mechanism in
service of them.

| | |
|---|---|
| **Conversation** | a business entity — a thread with one customer |
| **Turn** | one exchange within it — ask, work, answer |
| **Message** | a point in time — something was said |
| **Tool** | a unit of work — something was done |

They nest, and the nesting is the whole design: a conversation contains turns, a
turn contains messages and the work that produced the answer. Get those four
right and the dashboard follows.

This page is the model you write code against. For what each one records and why
it is captured that way, see
[What gets traced & why](/getting-started/what-gets-traced).

## Conversation

A conversation is **identified by a string you control** — whatever id your own
system already uses for that thread:

```python
with agentsight.conversation("wa-3859"):
    ...
```

It is a business entity, not a trace. It can last hours, survive restarts and
deploys, and pass through as many processes as your architecture involves; you
open the same id again tomorrow and it is the same conversation. Omit the id and
one is generated, which is what you want for a throwaway session and never what
you want for a real thread.

A conversation produces no span of its own. What it does is establish scope: its
fields — customer, device, language, metadata — are stamped onto
everything recorded inside it, which is what makes them filterable later without
you passing context down your call stack.

The scope works as a context manager, an async context manager, or a decorator:

```python
@agentsight.conversation(customer_id="user-456")
def nightly_summary():
    ...
```

Passing `enabled=False` turns everything inside into a no-op — useful for test
traffic and evaluation runs.

## Turn

A turn is **one exchange**, and it is a span:

```python
with agentsight.conversation("wa-3859"):
    with agentsight.turn():
        ...
```

**Its duration is your answer latency** — measured, not approximated. Tool calls
and LLM calls made inside it nest underneath it, so "how much of the wait was
tools, and how much was the model?" is answerable for every exchange without any
extra instrumentation.

Name it if the name is useful. Turns can nest, and one `turn(...)` bound to a
variable can be entered more than once:

```python
with agentsight.turn("ask"):
    ...
```

## Message

A message is **a point in time**: something was said, by the user or the agent.

```python
agentsight.user_message("How do I reset my password?")
agentsight.agent_message("Click 'Forgot Password' on the login page.")
```

Record as many as you like, in any order, from either sender — a burst of three
user messages, an answer followed by a card, an exchange where the agent escalates
and never replies. There is no required shape and **nothing to keep in order**:
each message carries its own timestamp, so recording them as they happen is
enough.

Messages are explicit because inference would put the wrong text into a
transcript your customers read — a rewritten prompt instead of what the human
typed. The module-level calls attach to whichever turn is currently active.

## Tool

A tool is **a unit of work**, and it becomes an action on the dashboard:

```python
@agentsight.tool
def search_orders(customer_id: str) -> list:
    ...

@agentsight.task(name="rerank")
def rerank(docs: list) -> list:
    ...
```

Decorating the function records when it started, when it ended, what it was
called with, and what it returned — or the error it raised, which is data too and
is re-raised untouched. A **tool** is something the agent calls out to; a **task**
is internal work. Identical rows, different word.

The name matters beyond labelling: escalation metrics key off specific action
names, so `@agentsight.tool(name="fallback_to_human")` is what makes an escalation
count as one.

## How they fit together

```
conversation "wa-3859" ─────────────────────────────────►  hours, many processes
   ├── turn ──► messages + nested tool/llm spans   [duration = answer latency]
   ├── turn ──► ...
   └── turn ──► ...
```

A conversation outlives any one process. A turn lives inside one.

## When a turn ends

A turn ends when its `with` block ends — **unless you hand its lifetime to
something else with `wrap()`, which you must do whenever the handler returns
before the work is done.**

This is the one thing worth knowing before you integrate anything that streams. A
handler that returns a streaming response has returned; the block has closed; and
without `wrap()` the turn is recorded with a near-zero duration and no answer.
Nothing raises — the data is simply wrong.

```python
return agentsight.wrap(StreamingResponse(event_generator()))
```

[Streaming](/tracking/streaming) is the page for that, and it is worth reading
before you ship a streaming endpoint. A turn whose lifetime has been handed off
also gets a deadline — five minutes by default, tunable with
`turn_timeout_ms` — so a stream nobody drains cannot leave it open forever.

## Next

- [Turns & Messages](/tracking/turns-and-messages) — the explicit form, for
  handlers the quickstart shortcut does not fit
- [Configuration](./configuration.md) — the whole `init()` surface
- [Deployment & limitations](./deployment.md) — what to wire up before you ship
