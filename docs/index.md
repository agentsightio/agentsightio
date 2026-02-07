---
outline: deep
---

# Introduction

**AgentSight** is a conversation tracking, analytics, and **database platform** built to provide your **clients** with access to their conversational AI data, including **dashboards, transcripts, and analytics overviews**.

Unlike traditional observability platforms built for developers, AgentSight focuses on both **client visibility** and **developer utility**. It provides a persistent, queryable **database backend** for your conversation data, not just logs or traces.

The **Python SDK** simplifies integration, enabling you to instrument tracking, token usage, and event capture with minimal effort, **storing it all in a managed database you can query via API**.

## What It's Used For

AgentSight’s core purpose is two-fold:

1.  To **help you share real-time conversation data, transcripts, and analytics directly with your clients** in an easy-to-use dashboard.
2.  To **provide a fully managed database backend** for your conversational AI, saving you from building and maintaining your own database for transcripts, messages, and long-term memory.

### As a **client-facing platform**, your clients gain direct access to:
  - **Conversation transcripts** - see exactly how users interact
  - **Usage analytics** - engagement trends, token usage, performance metrics
  - **Custom reports** - build reports based on filters, metrics, timeframes
  - **Data export** - download or integrate the raw data for internal use
  > See all [available metrics to track](/getting-started/metrics)

::: tip Provide Value
Offering client-facing platform transforms your offering from just building AI solutions to delivering a full, data-driven solution with a persistent backend and a UI your clients can actively use.
:::

### As a **database and API solution**, developers can:
  - **Store all conversation data** (transcripts, messages, attachments, user actions) without setting up or managing their own database.
  - **Retrieve full conversation transcripts via simple API endpoints** for use in other applications.
  - **Use AgentSight as a long-term memory store** for their AI agents.
  - **Integrate as an add-on** to an existing system (like a separate database or observability platform) or use it as the **primary, all-in-one database** for a new conversational system.

::: info You choose how to use it
It can be used as an add-on to your existing system (e.g., just for the client platform), as your primary database system for conversational AI, or as a complete solution for both.
:::

## Dashboard

![Dashboard preview](/images/dashboard.png)

The **AgentSight Dashboard** is the web interface where your clients explore their conversational data and insights.

It offers:

  - Full access to all conversation transcripts
  - Analytics for token usage, message volumes, response times
  - Custom report generation and export capabilities
  - White-labeled, client-specific dashboard views under your branding

Clients can filter by date, explore trends, and visualize performance.

## How Can My Clients View the Dashboard?

There are two ways your clients can access the dashboard:

1.  **Via Direct Invitation:** you can invite your clients to view the dashboard hosted on your specific subdomain under our main domain.

> Example: yourcompany.agentsight.com

2.  **Via Embedded Dashboard:** you can embed the dashboard directly into your own or your clients platforms such as WordPress sites or custom-built applications using our embeddable code snippet. (This one is not available yet but we are working on it)

## Who It's For

AgentSight is built for:

  - Developers, agencies, and teams delivering conversational AI solutions **who need a client-facing dashboard *and/or* a managed conversation database**.
  - Freelancers managing multiple AI clients.
  - Organizations wanting to offer **clients transparent, usable insights** into their AI systems.

It makes internal performance data useful to **you (via API)** and accessible to your **clients (via the dashboard)**.

### Migrate

AgentSight supports seamless migration from your current transcription or monitoring system via JSON data imports.

> Learn how to [migrate your data]()

## What You Can Track

AgentSight allows developers to track various types of activity and store it for client analysis or internal use:

  - **Conversation Data:** track full question–answer pairs with automatic threading and metadata.
  - **User Actions:** monitor execution times, tool usage, and error rates for performance insights.
  - **Button Interactions:** capture engagement metrics for UI-based actions.
  - **File Attachments:** track uploads, downloads, and file usage.
  - **Token Usage:** manually pass token data or use one of our automatic token handlers.
  - **Custom Metadata:** attach contextual or business-relevant information to any event.

All this data is stored in the AgentSight database, ready to be analyzed in the client dashboard or **fetched via API for your own applications (e.g., for long-term memory)**.

## Comparison with Observability Platforms

| Feature | AgentSight | Langfuse | Phoenix Arize |
| :--- | :---: | :---: | :---: |
| **Primary Focus** | Conversation analytics & client dashboards | AI Observability | LLM tracing, evaluation |
| **Designed For** | **Clients & End Users** | Developers | Developers |
| **Client Dashboard Access** | ✅ | ❌ | ❌ |
| Actionable performance reports | ✅ | ❌ | ❌ |
| Conversation analytics dashboard | ✅ | ❌ | ❌ |
| Shareable Transcripts | ✅ | ❌ | ❌ |
| White-Label Support | ✅ | ❌ | ❌ |
| Usage Metrics Tracking | ✅ | ❌ | ❌ |
| Usage Analytics & Reports | ✅ | ❌ | ❌ |
| Token Usage Tracking | ✅ | ✅ | ✅ |
| Developer Debugging Tools¹ | ❌ | ✅ | ✅ |
| LLM Performance Tracing | ❌ | ✅ | ✅ |
| Data Export & Migration | ✅ | ✅ | ✅ |

¹ AgentSight focuses on client visibility, not internal debugging.

AgentSight complements observability platforms. It’s not built for tracing or debugging, but for **giving clients insight into their own AI systems** *and* **providing developers a simple database and API for conversation persistence**.

## Quick start

Get up and running with just a few lines of code to track complete conversations:

```python
from agentsight import ConversationTracker

# Initialize tracker
tracker = ConversationTracker(
    api_key="your_api_key_here"
)
tracker.get_or_create_conversation(
    conversation_id="your_conversation_id"
)
tracker.track_human_message(
    message="What's the weather like today?",
)
tracker.track_agent_message(
    message="It's sunny with clear skies."
)
tracker.send_tracked_data()
```

Once tracked, this data is instantly available in the client dashboard and can be retrieved using our API endpoints, allowing you to use AgentSight as your primary conversation database.