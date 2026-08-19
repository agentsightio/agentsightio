---
outline: deep
---

<CopyMarkdownButton />

# The SDK on its own

[`examples/01_plain.py`](https://github.com/agentsightio/agentsightio/blob/main/examples/01_plain.py)
uses no provider, no framework and no auto-instrumentation. This is the floor:
everything it records comes from the explicit surface alone, and every other
example adds spans on top of exactly this shape.

```bash
python examples/01_plain.py
```

## A visit before anyone speaks

Somebody loaded the widget and typed nothing. A decorator or a turn only fires
once someone has engaged, so it cannot express "loaded but silent" — which is
why [`open_conversation()`](/tracking/conversations#the-visit-phase) is a
separate, explicit call:

```python
import agentsight as ags

ags.open_conversation("demo-visitor", device="mobile", source="web", language="en")
```

## One conversation, several shapes of turn

The conversation scope takes its metadata once, at the top. Inside it the
script runs through the shapes real traffic produces:

```python
with ags.conversation(
    "demo-plain",
    customer_id="user-12345",
    device="desktop",
    source="web",
    language="en",
    environment="development",
    name="Order questions",
):
    # the common shape: one message in, one out, a tool call between
    with ags.turn("ask"):
        ags.user_message("Where is my order?")
        search_orders("user-12345")          # @ags.tool
        ags.agent_message("Order A-1 ships tomorrow.")

    # messages have no rules: three in, two out, internal work between
    with ags.turn("burst"):
        ags.user_message("actually")
        ags.user_message("two of them")
        ags.user_message("the second one is urgent")
        rerank(["b", "a"])                   # @ags.task
        ags.agent_message("Got it — checking both.")
        ags.agent_message("The urgent one is already out for delivery.")
```

`search_orders` and `rerank` are ordinary functions wearing
[`@ags.tool` and `@ags.task`](/tracking/tools-and-actions); the decorated call
inside an active turn is all it takes for the span to appear in the right
place.

## Things no call stack can observe

A button click happens in the browser; a file arrived through your upload
endpoint. Neither is visible from the Python call stack, so both are explicit:

```python
ags.button("feedback", "Was this helpful?", "yes")
ags.record_attachments([{"filename": "receipt.pdf", "mime_type": "application/pdf"}])
```

`record_attachments()` only notes that a file exists.
[`upload_attachments()`](/tracking/attachments) is the one that moves bytes —
this script writes spans to disk rather than talking to the API, so it uses the
recorder.

## Metadata learned late

What the conversation turned out to be about was not known at the top, where
the scope took its metadata. `update_metadata()` merges rather than replaces —
`customer_id` and everything else set earlier survives:

```python
ags.update_metadata({"topic": "delivery", "self_served": False})
```

A falsy value like `False` is stored as data; `remove=` is the only thing that
deletes a key.

## Turns that do not end well

The script closes with three endings the dashboard has to distinguish: a silent
escalation (a turn with a user message and a tool call but no agent message at
all), an [abandoned turn](/tracking/streaming#when-the-customer-closes-the-tab),
and a turn that raised:

```python
with ags.turn("abandoned"):
    ags.user_message("wait, never mind")
    ags.abandon_turn()

try:
    with ags.turn("boom"):
        ags.user_message("do the thing")
        raise RuntimeError("the thing exploded")
except RuntimeError:
    pass
```

Neither writes transcript rows — there was no complete exchange — but the
spans, their durations and any spend they carried are all recorded, marked as
what they are.

## What to look for in the output

The printed span tree shows each turn `complete` or
`INCOMPLETE(abandoned)` / `INCOMPLETE(error)`, the tool spans nested under
their turns, and the visit conversation in a file of its own. The JSON under
`examples/traces/01_plain/` is the payload itself.
