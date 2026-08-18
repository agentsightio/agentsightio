---
outline: deep
---

<CopyMarkdownButton />

# Buttons

A click happens **in the browser, not in your call stack**. Nothing on the server
can observe it, which is why recording one takes a call:

```python
with agentsight.conversation("wa-3859"):
    agentsight.button("feedback", "Was this helpful?", "yes")
```

Three required values, and an optional dictionary:

| Parameter | Type | Default |
|---|---|---|
| `button_event` | `str` | required |
| `label` | `str` | required |
| `value` | `str` | required |
| `metadata` | `dict` | — |

**`button_event`** — what this button is *for*: `feedback`,
`contact_human_agent`, `product_selection`. It groups the buttons belonging to
one prompt.

**`label`** — the text the user actually saw on the button.

**`value`** — what the click meant to your application.

**`metadata`** — anything else worth keeping with the click.

A click is recorded as a button interaction in its own right. It does **not**
write a `Button clicked: …` sentence into the transcript — the click was real, a
sentence describing it would not be, and a transcript your customers read is not
the place to invent one.

It needs an active conversation scope. Outside one there is nothing to attach the
click to, and the call does nothing.

## Recording a set of buttons

Record the button that was **clicked**, not the ones that were merely rendered.
When one prompt offers several, give them the same `button_event` and let the
label and value tell them apart:

```python
agentsight.button("contact_human_agent", "Create ticket", "create-ticket")
```

```python
agentsight.button("contact_human_agent", "Copy conversation", "copy-conversation")
```

That shared event is what keeps the set legible later — two clicks a week apart
are recognisably answers to the same question rather than two unrelated events.

:::warning Recorded and archived, not yet readable back
A click is archived complete — event, label, value, metadata and the conversation
it belongs to — but **nothing surfaces it back today**. There is no dashboard
view and no API that returns clicks, so treat this as history you are keeping,
not as something to go and query. Keep calling it if you want the record; do not
build a feature that depends on reading it back.
:::

## Next

- [Conversations](./conversations.md) — the scope a click has to be recorded
  inside
- [Turns & Messages](./turns-and-messages.md) — the exchange around it
- [What gets traced & why](/getting-started/what-gets-traced) — why a click is
  the one thing that needs an explicit call
