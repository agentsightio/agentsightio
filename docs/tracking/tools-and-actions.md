---
outline: deep
---

<CopyMarkdownButton />

# Tools & Actions

A tool is a unit of work with a measured duration — a search, an order lookup, a
payment API — and it becomes an **action** on the dashboard, which is how "what
did the agent actually do?" gets an answer your client can see. Decorating the
function is the whole integration.

```python
@agentsight.tool
def search_orders(customer_id: str, status: str = "open") -> list:
    ...
```

## Tools and tasks

Two decorators, identical rows, different word:

```python
@agentsight.tool
def search_orders(customer_id: str) -> list:
    ...

@agentsight.task
def rerank(candidates: list) -> list:
    ...
```

A **tool** is something the agent calls out to. A **task** is internal work —
parsing a document, reranking results, building a prompt. Use whichever one
describes the function honestly; nothing downstream treats them differently.

Both take an optional name, and both work bare or configured:

```python
@agentsight.tool(name="fallback_to_human")
def escalate(reason: str) -> str:
    ...
```

Both wrap `async def` functions as well, with no separate decorator and no change
in what is recorded.

## What is recorded for you

| What | Where it comes from |
|---|---|
| Started and ended | the real boundaries of the call |
| Duration | measured, not reported |
| Arguments | bound from the actual call, including defaults |
| Result | the return value |
| Error | the exception, if one was raised |

Arguments are bound the way Python binds them, so a positional call and a keyword
call record the same thing, and a default that was never passed is still recorded
as what the function ran with. On a method, `self` is dropped.

:::warning Arguments and results are captured in full
Whatever the function was called with and whatever it returned is transmitted and
stored, up to the size limits in
[What the SDK sends](/getting-started/what-the-sdk-sends). If a tool takes a
credential or returns a customer's full record, that is what gets recorded.
:::

**A failed tool call is data.** The row is still written, with the error on it,
and **the exception propagates untouched** — the decorator never swallows,
retries, or changes what your caller sees:

```python
@agentsight.tool
def charge_card(token: str, amount: int) -> dict:
    raise PaymentDeclined("insufficient funds")  # recorded, then re-raised
```

Outside a conversation scope, the decorator is a pass-through: your function runs
exactly as it would undecorated and nothing is recorded. That is the usual reason
an action you expected is missing.

## The name is load-bearing

Beyond labelling, the name is what escalation metrics key off. An action named
`fallback_to_human`, `open_ticket`, `ticket` or `contact_human` counts as a human
escalation; the same function named `escalate` does not.

```python
@agentsight.tool(name="fallback_to_human")
def hand_off(reason: str) -> str:
    ...
```

Names are otherwise yours. They default to the function's own name, which is
usually right.

## Tools your framework already reports

If you use [LangChain](/integrations/langchain) or
[LlamaIndex](/integrations/llamaindex), **their tool calls are recorded without
decoration.** The SDK attaches to the framework's own callback system, so tools
defined as framework objects — the ones you never wrote as plain functions, and
could not decorate without editing every class that defines them — arrive
anyway, with the same durations, arguments and results.

Running a provider integration and a framework integration together is normal and
does not double-count: the framework side stands down on any LLM call the
provider side already sees. See [Tokens & Cost](./tokens-and-cost.md) for how
that split works.

:::info One thing that does double
Decorating a tool your framework also reports gives you **two** spans for one
call — the framework's and yours. Decorate the work your framework cannot see:
functions you call directly, and anything that happens outside the agent loop.
:::

## Naming an action for the dashboard

An action's `display_name` and `description` are how it reads on the dashboard,
and neither travels with a tool call — the call carries what happened, not how it
should be labelled. They are set through the API client instead, once the action
exists:

```python
from agentsight.api import AgentSight

ags = AgentSight()
ags.actions.update(action_id, display_name="Order lookup")
```

Tracking is what usually brings an action into being — the first decorated call
carrying the name. You can also declare one up front with
`ags.actions.create("lookup_order", display_name="Order lookup")`, which is
useful when you want the capability on the dashboard before the tool ships. The
first call that runs then adopts that row rather than making a second one, so
you end up with one action either way.

There is no `delete()`: the definition is what every recorded invocation hangs
off. See [Actions](/api/actions) for the full surface.

## Next

- [Turns & Messages](./turns-and-messages.md) — the exchange these nest inside
- [Tokens & Cost](./tokens-and-cost.md) — the LLM calls alongside them, counted
  without any decoration at all
- [What gets traced & why](/getting-started/what-gets-traced) — what an action is
  as a product idea
