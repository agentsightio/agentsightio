---
outline: deep
---

# Dashboard Metrics Overview

Your AgentSight dashboard provides real-time insights into user engagement, behavior, and agent performance.  
Some metrics are tracked automatically, while others require additional fields to be passed when creating or updating a conversation.

## How Metrics Are Tracked

Your dashboard is populated based on how you track data. Metrics are grouped into three categories:

* **Automatic Metrics** - computed from system data (no extra setup).
* **Conversation-Passed Metrics** - require adding specific fields when creating a conversation.
* **Specialized Metrics** - based on specific actions or feedback.

You provide all contextual and specialized data by passing arguments to `get_or_create_conversation` (or `initialize_conversation`).
> See the difference between these methods [here](../tracking/track-interaction).

```python
def get_or_create_conversation(
    self,
    conversation_id: str,
    customer_id: Optional[str] = None,
    customer_ip_address: Optional[str] = None,
    device: Optional[Literal["desktop", "tablet", "mobile"]] = None,
    source: Optional[str] = None,
    language: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None
)
```

## Automatic Metrics
These metrics are calculated automatically just by using the core tracking methods.

| **Metric**                            | **Description**                                                                      | **Tracking Method**                                                     |
| ------------------------------------- | ------------------------------------------------------------------------------------ | ----------------------------------------------------------------------- |
| **Total Messages**                    | Total number of messages exchanged across all conversations.                         | Automatically counted from all message records linked to conversations. |
| **Total Conversations**               | Number of unique conversations started by users.                                     | Automatically tracked via unique `conversation_id` values.              |
| **Average Agent Response Time**         | Average time the agent takes to respond after receiving a user message.                | Calculated automatically using message timestamps.                      |
| **Peak Hours**                        | Highlights the most active times for user engagement by day and hour.                | Derived automatically from message timestamps.                          |
| **Messages & Conversations Overview** | Daily comparison of total message volume and number of unique conversations.         | Aggregated automatically from conversation and message logs.            |
| **Average Conversation Duration**     | Average time between the start (`started_at`) and end (`ended_at`) of conversations. | Computed automatically from conversation lifecycle timestamps.          |
| **Tool Usage and Average Duration**   | Breakdown of tool usage frequency and average execution duration.                    | Recorded automatically from action logs.          |

## Metrics Passed with Conversation

To enable these metrics, include additional parameters when calling `get_or_create_conversation()` or `initialize_conversation()`.

| **Metric**           | **Description**                                                             | **Required Field / Tracking**                               |
| -------------------- | --------------------------------------------------------------------------- | ----------------------------------------------------------- |
| **World Map**        | Shows the global distribution of users initiating conversations.            | `customer_ip_address`  IP is automatically geolocated.     |
| **Device Usage**     | Breaks down interactions by device type (desktop, tablet, mobile).          | `device`  must be passed when creating the conversation.   |
| **Individual Users** | Counts unique users interacting with the bot.                               | `customer_id`  should be unique per user.                  |
| **Source**           | Tracks which channel started the conversation (web, WhatsApp, Viber, etc.). | `source`  must be passed when creating the conversation.   |
| **Language**         | Measures the language used in the conversation.                             | `language`  must be passed when creating the conversation. |

## Specialized Metrics

These metrics are based on behavioral patterns or explicit user feedback rather than static conversation fields.

| **Metric**                | **Description**                                                               | **Tracking / Data Required**                                                                                                                                  |
| ------------------------- | ----------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Human Escalation Rate** | Percentage of conversations escalated to a human agent.                       | Automatically detected from tool usage: `['fallback_to_human', 'open_ticket', 'ticket', 'contact_human']`.                                                    |
| **Conversation Feedback** | Captures user feedback or satisfaction rating for a conversation.             | Automatically detect conversation feedback if there are any. Use `conversation_manager` to add user feedback.                                                                                           |
| **Unique Interaction**    | Tracks actual user engagement with the AI agent rather than just page visits. | Use `initialize_conversation()` first, then any subsequent call with the same `conversation_id` via `get_or_create_conversation()` counts as one interaction. |