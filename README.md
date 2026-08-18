# Introduction
**AgentSight** is a conversation tracking and analytics platform built to provide your **clients** with access to their conversational AI data, including **dashboards, transcripts, analytics overviews and more**.

Unlike traditional observability platforms built for developers, AgentSight focuses on **client visibility** and meaningful insights, not just logs or traces.

Besides the client-facing platform, you also get a **fully managed database backend** for your conversational AI, so you do not need to build or maintain any infrastructure or dashboards, which lets you focus on your AI.

The **Python SDK** makes this integration possible. You will be sending your metrics and tracking in just a few lines of code.

Visit the [landing page](https://agentsight.io) for more information.

## What It's Used For
AgentSight’s core purpose is to help you **share real-time conversation data, transcripts, and analytics directly with your clients**.

Clients gain direct access to:  
- **Conversation transcripts** - see exactly how users interact  
- **Usage analytics** - engagement trends, token usage, performance metrics  
- **Custom reports** - build reports based on filters, metrics, timeframes  
- **Data export** - download or integrate the raw data for internal use  

> This transforms your offering from just building AI solutions to delivering a full, data-driven platform your clients can actively use.

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
| Automatic Token & Cost Tracking | ✅ | ✅ | ✅ |
| Raw Trace Data via API | ✅ | ✅ | ✅ |
| Trace Debugging UI¹ | ❌ | ✅ | ✅ |
| Data Export | ✅ | ✅ | ✅ |

¹ AgentSight records complete OpenTelemetry spans and makes them readable through its API, but its dashboards are built for client visibility, not internal debugging.

AgentSight complements observability platforms. It’s not built for debugging, but for **giving clients insight into their own AI systems** *and* **providing developers a simple database and API for conversation persistence**.

## Installation

```bash
pip install agentsight
```

Or with your package manager of choice — `poetry add agentsight`, `uv add agentsight`.

## Quick start
Track complete conversations in a few lines of code:
```python
import agentsight

agentsight.init(api_key="ags_...")  # or set AGENTSIGHT_API_KEY

with agentsight.conversation("your_conversation_id"):
    with agentsight.turn():
        agentsight.user_message("What's the weather like today?")
        reply = my_agent.run(...)  # token usage, cost and tool calls captured automatically
        agentsight.agent_message(reply)
```

Sending happens in the background — there is nothing to flush in a long-running service. LLM calls made through OpenAI, Anthropic, LangChain or LlamaIndex inside a turn are captured without any extra code, and `agentsight.upload_attachments(...)` delivers files shared in the conversation.

## Learn More
Visit the docs to learn more: [docs](https://docs.agentsight.io)