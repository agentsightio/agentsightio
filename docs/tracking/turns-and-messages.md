---
outline: deep
---

<CopyMarkdownButton />

# Turns & Messages

A turn is one exchange — the user asks, the agent works, the agent answers — and
messages are what was said inside it. This is the page for handlers the
[Quickstart](/getting-started/quick-start) shortcut does not fit, which in
production is most of them. It is a few more lines and it works everywhere.

```python
with agentsight.conversation("wa-3859"):
    with agentsight.turn():
        agentsight.user_message("Where is my order?")
        agentsight.agent_message("Order A-1 ships tomorrow.")
```

**The turn's duration is your answer latency** — measured, not approximated —
and every tool call and LLM call made inside it nests underneath it without
being mentioned.

## Messages have no rules

This is the guarantee, and it is worth stating before anything else: **record as
many messages as you like, in any order, from either sender.** There is no
required shape, no pairing, and **nothing to keep in order** — each message
carries its own timestamp, so recording them as they happen is enough.

| Shape | What it looks like |
|---|---|
| One in, one out | the common case |
| Burst | three `user_message()`, then one `agent_message()` |
| Reply and card | one `user_message()`, two `agent_message()` |
| Silent escalation | a `user_message()`, a tool, and no answer at all |
| Proactive | an `agent_message()` with no user message before it |

The snippets below all run inside a conversation scope like the one above — a
turn outside one records nothing.

A burst — the customer sent three lines before you finished reading the first:

```python
with agentsight.turn("burst"):
    agentsight.user_message("actually")
    agentsight.user_message("two of them")
    agentsight.user_message("the second one is urgent")
    agentsight.agent_message("Got it — both are out for delivery.")
```

A reply followed by a card — one question, two things sent back:

```python
with agentsight.turn("ask"):
    agentsight.user_message("Where is my order?")
    agentsight.agent_message("Order A-1 ships tomorrow.")
    agentsight.agent_message("[tracking card] A-1 · in transit")
```

A silent escalation — the agent handed off to a human and said nothing:

```python
with agentsight.turn("escalate"):
    agentsight.user_message("I want to talk to a person")
    escalate(reason="customer asked")
```

And a proactive message, in a bare conversation scope with no turn at all:

```python
with agentsight.conversation("wa-3859"):
    agentsight.agent_message("Your order shipped this morning.")
```

That last one still lands: a message recorded outside a turn gets a turn of its
own, opened and closed around it, so it always has somewhere to live.

## A real handler

The shape most readers actually need — a payload arrives, you dig the id out of
it, and the agent does the rest:

```python
parsed = MyPayload(**json.loads(data))

with agentsight.conversation(
    parsed.conversation_id,
    device="mobile" if parsed.screen < 640 else "desktop",
    customer_ip_address=get_ip(request),
    language=language,
    source="web",
):
    with agentsight.turn():
        agentsight.user_message(parsed.messages[-1].content)
        response = await agent.run(...)
        agentsight.agent_message(str(response))
```

Twelve lines. Everything inside — tool calls, LLM calls, token counts, cost,
latency — is captured without being mentioned.

The decorator form collapses the same shape: it opens the conversation around
the exchange, resolving the id through `id_from`, and any conversation field
you pass it goes onto that conversation:

```python
@agentsight.turn(id_from="conversation_id", source="web", language="en")
def handle(conversation_id: str, text: str) -> str:
    ...
```

## Why messages are explicit

:::info Why the SDK doesn't infer them
It could. It could read the first string argument, or the text that went into
the LLM, and often it would be right. But inference puts the **wrong text** into
a transcript your client reads: a rewritten prompt instead of what the human
typed, a retrieved document instead of the question, an image description
instead of the caption they wrote. In every production service we looked at, the
user's text had been transformed before it reached a variable.

Two explicit calls are a correctness guarantee, not a missing feature. Where the
handler really is shaped like `(text) -> str`, `turn(infer=True)` opts into the
inference — see the [Quickstart](/getting-started/quick-start).
:::

## Naming a turn

Names are optional and cost nothing:

```python
with agentsight.turn("ask"):
    ...
```

The name is what you will read on the dashboard when an exchange is one of
several kinds — `ask`, `escalate`, `follow_up` — and it is worth spending when
the kinds are meaningfully different.

## Reusing and nesting turns

A `turn(...)` bound to a variable can be entered more than once, and turns nest:

```python
ask = agentsight.turn("ask")

with ask:
    agentsight.user_message(first)
    agentsight.agent_message(answer_one)

with ask:
    agentsight.user_message(second)
    agentsight.agent_message(answer_two)
```

Two exchanges, two turns, each with its own duration. Both forms also work as
`async with`.

## Message metadata

Either call takes a metadata dictionary, for the things that belong to one
message rather than to the conversation:

```python
agentsight.agent_message(reply, metadata={"model_route": "fast", "cached": True})
```

## When the work outlives the block

A turn ends when its `with` block ends — **unless the handler returns before the
work is done**, which is what happens the moment you stream. The block has
closed; the framework drains the response afterwards; and without handing the
turn's lifetime over, the exchange is recorded with a near-zero duration and no
answer. Nothing raises. The data is simply wrong.

```python
return agentsight.wrap(StreamingResponse(event_generator()))
```

[Streaming](/tracking/streaming) is the page for that, and it is worth reading
before you ship a streaming endpoint.

## Next

- [Conversations](./conversations.md) — the scope these live in, and the fields
  that make them filterable
- [Streaming](/tracking/streaming) — required reading before you ship a
  streaming endpoint
- [Tools & Actions](./tools-and-actions.md) — recording what the agent *did*
  between the two messages
- [Core Concepts](/getting-started/core-concepts) — how conversations, turns,
  messages and tools nest
