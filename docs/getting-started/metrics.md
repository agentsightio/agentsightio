---
outline: deep
---

<CopyMarkdownButton />

# Dashboard Metrics Overview

Your AgentSight dashboard provides real-time insights into user engagement, behavior, and agent performance.  
Most metrics are tracked automatically; a few need context only your application has.

## How Metrics Are Tracked

Your dashboard is populated based on how you track data. Metrics are grouped into three categories:

* **Automatic Metrics** - computed from what the SDK already records (no extra setup).
* **Conversation-Passed Metrics** - require adding specific fields to the conversation.
* **Specialized Metrics** - based on specific actions or feedback.

Contextual data is passed on the conversation, either on the scope itself or as
keyword arguments to a decorated handler — they are the same fields either way:

```python
with agentsight.conversation(
    "chat-123",
    customer_id="user_001",
    customer_ip_address="203.0.113.7",
    device="mobile",          # desktop | tablet | mobile
    source="whatsapp",
    language="en",
    metadata={"plan": "pro"},
):
    ...
```

```python
@agentsight.turn(id_from="session_id", device="mobile", source="web")
def handle_message(session_id: str, text: str) -> str:
    ...
```

> See [Conversations](/tracking/conversations) for the full set of fields and when
> to pass them.

## Automatic Metrics

These metrics are calculated automatically from the turns, tools and LLM calls the SDK records.

| **Metric**                            | **Description**                                                                      | **Tracking Method**                                                     |
| ------------------------------------- | ------------------------------------------------------------------------------------ | ----------------------------------------------------------------------- |
| **Total Messages**                    | Total number of messages exchanged across all conversations.                         | Automatically counted from all message records linked to conversations. |
| **Total Conversations**               | Number of unique conversations started by users.                                     | Automatically tracked via unique `conversation_id` values.              |
| **Average Agent Response Time**         | Average time the agent takes to respond after receiving a user message.                | Measured from the turn itself — the exchange is timed, not inferred from message timestamps. |
| **Peak Hours**                        | Highlights the most active times for user engagement by day and hour.                | Derived automatically from message timestamps.                          |
| **Messages & Conversations Overview** | Daily comparison of total message volume and number of unique conversations.         | Aggregated automatically from conversation and message logs.            |
| **Average Conversation Duration**     | Average time between the start and end of conversations. | Computed automatically from conversation lifecycle timestamps.          |
| **Tool Usage and Average Duration**   | Breakdown of tool usage frequency and average execution duration.                    | Measured from each `@agentsight.tool` / `@agentsight.task` call — the decorator times the function. |
| **Token Usage and Cost**              | Tokens consumed and what they cost, by model.                                        | Recorded automatically for instrumented providers and frameworks, including the evaluator and router calls nobody hand-tracks. Cost is priced server-side; a model with no known rate is reported as unpriced rather than free. |

## Metrics Passed with Conversation

These need context that only your application has, so they are passed on the conversation.

| **Metric**           | **Description**                                                             | **Required Field / Tracking**                               |
| -------------------- | --------------------------------------------------------------------------- | ----------------------------------------------------------- |
| **World Map**        | Shows the global distribution of users initiating conversations.            | `customer_ip_address`  IP is automatically geolocated.     |
| **Device Usage**     | Breaks down interactions by device type (desktop, tablet, mobile).          | `device`  must be passed on the conversation.   |
| **Individual Users** | Counts unique users interacting with the bot.                               | `customer_id`  should be unique per user.                  |
| **Source**           | Which channel started the conversation (web, WhatsApp, Viber, etc.). Recorded today; not yet surfaced in the dashboard. | `source`  may be passed on the conversation.   |
| **Language**         | Measures the language used in the conversation.                             | `language`  must be passed on the conversation. |

## Specialized Metrics

These metrics are based on behavioral patterns or explicit user feedback rather than static conversation fields.

| **Metric**                | **Description**                                                               | **Tracking / Data Required**                                                                                                                                  |
| ------------------------- | ----------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Human Escalation Rate** | Percentage of conversations escalated to a human agent.                       | Detected from tool names: `['fallback_to_human', 'open_ticket', 'ticket', 'contact_human']`. Name the decorator accordingly — `@agentsight.tool(name="fallback_to_human")` — and escalations count themselves. |
| **Conversation Feedback** | Captures user feedback or satisfaction rating for a conversation.             | Collected wherever your users give it — the chat widget, or `feedbacks.create_for_conversation()` on the [API client](/api/feedbacks) from your own UI. |
| **Unique Interaction**    | Tracks actual user engagement with the AI agent rather than just page visits. | Call `agentsight.open_conversation()` when the conversation is opened; the first turn is what marks it engaged. |

:::info Why Unique Interaction needs a call
It is the one metric a decorator cannot express. A decorated handler only fires
once somebody has already typed something — so by the time the SDK sees anything,
the visit has become an interaction. `open_conversation()` records that the
conversation exists before any exchange does, which is what separates "the widget
loaded" from "the user engaged".
:::
