# Introduction
**AgentSight** is a conversation tracking and analytics platform built to provide your **clients** with access to their conversational AI data, including **dashboards, transcripts, analytics overviews and more**.

Unlike traditional observability platforms built for developers, AgentSight focuses on **client visibility** and meaningful insights, not just logs or traces.

Besides the client-facing platform, you also get a **fully managed database solution** for you conversation AI, meaning you do not need to build or maintain any infrstructure or dashboard which allows you to focus on your AI.

The **Python SDK** makes this integration possible. You will be passing your metrics and tracking in just few lines of code.

Visit [landing page](https://agentsight.io) from more information.

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
tracker.track_question(
    question="What's the weather like today?",
)
tracker.track_answer(
    answer="It's sunny with clear skies."
)
tracker.send_tracked_data()
```

## Learn More
Visit the docs to learn more: [docs](https://docs.agentsight.io)