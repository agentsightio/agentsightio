---
outline: deep
---

<CopyMarkdownButton />

# Core Concepts

Understanding AgentSight's architecture will help you effectively track and analyze your AI agent conversations.

## Three SDK Clients

AgentSight provides three specialized clients, each designed for specific use cases. All clients are **automatically initialized as singletons** - just import and use them.

### 1. ConversationTracker
**Purpose:** Track conversations in real-time as they happen

```python
from agentsight import conversation_tracker

# Track data in memory
conversation_tracker.track_human_message("Hello!")
conversation_tracker.track_agent_message("Hi there!")

# Send when ready
conversation_tracker.send_tracked_data()
```

**Use cases:**
- Real-time conversation logging
- Tracking questions, answers, actions, buttons, attachments
- Token usage monitoring
- Batch processing of conversation events

### 2. ConversationManager
**Purpose:** Manage and update existing conversations

```python
from agentsight import conversation_manager

# Rename conversation
conversation_manager.rename_conversation(
    conversation_id="conv-123",
    name="Resolved: Password Reset"
)

# Submit user feedback
conversation_manager.submit_feedback(
    conversation_id="conv-123",
    sentiment="positive",
    comment="Very helpful!"
)
```

**Use cases:**
- Renaming conversations
- Adding user feedback
- Marking conversations as important
- Deleting conversations
- Updating conversation metadata

### 3. AgentSightAPI
**Purpose:** Fetch and query conversation data

```python
from agentsight import agentsight_api

# Fetch with filters
conversations = agentsight_api.fetch_conversations(
    feedback_sentiment="positive",
    page_size=10
)

# Get specific conversation
conversation = agentsight_api.fetch_conversation(42)
```

**Use cases:**
- Building analytics dashboards
- Querying conversations by filters
- Fetching conversation details
- Generating reports
- Integration with other systems

:::info Singleton Pattern
All three clients are initialized as singletons. You can import and use them anywhere in your code without worrying about multiple instances or configuration conflicts.
:::

## Conversations & Context

A **conversation** represents a logical grouping of related interactions between users and your AI agent. Each conversation has (if you pass this data):

- **Unique ID:** String identifier you control (e.g., `"chat-session-123"`)
- **Database ID:** Integer primary key assigned by AgentSight
- **Metadata:** Custom fields like customer_id, device, language, environment
- **Messages:** Ordered sequence of user questions and agent answers
- **Actions:** Tool usage, database queries, API calls
- **Attachments:** Files, images, documents
- **Feedback:** User ratings and comments

:::info Agent Identity & Organization
Every interaction is associated with a specific AI agent identity which is linked to API key, allowing you to differentiate performance between different AI agents or configurations.
:::

### Common Implementation Patterns

- **Web Apps:** Store in localStorage/cookies - one ID per browser session
- **WhatsApp/SMS Bots:** Use phone number - naturally groups all messages
- **Mobile Apps:** Store in local database - separate ID per conversation thread
- **Voice Agents:** Generate new ID per call using `generate_conversation_id()`

```python
from agentsight.helpers import generate_conversation_id

# Generate unique ID
conversation_id = generate_conversation_id()  # e.g., "conv_a3f8bc9d"
```

## In-Memory Tracking & Batch Processing

AgentSight uses an **in-memory-first architecture** for maximum performance. All tracking operations are instant - data is stored locally with precise timestamps until you're ready to send it.

### How It Works

```python
# ⚡ All instant - no network calls
conversation_tracker.track_human_message("What is machine learning?")
conversation_tracker.track_action("search_knowledge_base", duration_ms=150)
conversation_tracker.track_agent_message("Machine learning is...")
conversation_tracker.track_token_usage(prompt_tokens=45, completion_tokens=32)

# 🌐 Single network call sends everything
response = conversation_tracker.send_tracked_data()
```

### Benefits

✅ **Zero latency** - Tracking never slows down your AI agent  
✅ **Order preserved** - Chronological sequence maintained with microsecond precision  
✅ **Resource efficient** - Minimal memory and CPU usage  
✅ **Flexible batching** - Send when it makes sense for your app  
✅ **Atomic operations** - All data sent in one transaction  

### Sequential Order Preservation

Every tracked event gets a timestamp. When sent, events appear in your dashboard in exact chronological order:

```python
# Tracked in this order...
conversation_tracker.track_human_message("2 + 2 = ?")      # 12:00:00.001Z
conversation_tracker.track_action("calculate")             # 12:00:00.055Z
conversation_tracker.track_agent_message("The answer is 4") # 12:00:00.120Z
conversation_tracker.track_button("helpful", "👍", "yes")   # 12:00:00.125Z

# ...appears in dashboard in the same order
```

:::warning Track in Order
Always track events in the order they occur. Out-of-order tracking leads to confusing conversation flows and inaccurate analytics.
:::

### When to Send Data

You control when to send. Common patterns:

```python
# Pattern 1: Send after each interaction
def handle_query(query):
    conversation_tracker.track_human_message(query)
    answer = agent.process(query)
    conversation_tracker.track_agent_message(answer)
    conversation_tracker.send_tracked_data()  # Send immediately

# Pattern 2: Batch multiple interactions
def handle_session(queries):
    for query in queries:
        conversation_tracker.track_human_message(query)
        answer = agent.process(query)
        conversation_tracker.track_agent_message(answer)
    
    conversation_tracker.send_tracked_data()  # Send all at once
```

### Multi-Conversation Support

Track multiple conversations concurrently - each maintains its own independent timeline:

```python
# Conversation A
conversation_tracker.configure(conversation_id="user-123")
conversation_tracker.track_human_message("Hello")

# Conversation B  
conversation_tracker.configure(conversation_id="user-456")
conversation_tracker.track_human_message("Hi there")

# Conversation A
conversation_tracker.configure(conversation_id="user-123")
conversation_tracker.track_agent_message("How can I help?")

# Each conversation maintains separate chronological order
```

## Rich Metadata System

Add context to any tracked event using metadata. This transforms raw logs into actionable insights.

```python
# Add metadata to messages
conversation_tracker.track_human_message(
    message="How do I reset my password?",
    metadata={
        "user_type": "premium",
        "language": "en",
        "support_category": "account",
        "priority": "high"
    }
)

# Add metadata to actions
conversation_tracker.track_action(
    action_name="database_query",
    duration_ms=150,
    metadata={
        "query_type": "SELECT",
        "cache_hit": False,
        "rows_returned": 10
    }
)

# Add metadata to conversations
conversation_tracker.get_or_create_conversation(
    conversation_id="support-123",
    metadata={
        "session_id": "abc123",
        "referrer": "help_page",
        "user_agent": "Chrome/91.0"
    }
)
```

**Every tracking method accepts metadata** - use it to capture context that matters for your analytics.

## AgentSight Dashboard

The AgentSight dashboard provides real-time visibility into your AI agent's performance:

**Key Features:**
- 📊 **Analytics** - Response times, message flow, engagement trends
- 🔍 **Search & Filter** - Find conversations by sentiment, actions, metadata
- 💬 **Conversation Viewer** - See full conversation transcripts with timestamps
- 📈 **Token Usage** - Monitor LLM costs and optimize usage
- ⭐ **Feedback Analysis** - Track user satisfaction and identify issues
- 🏷️ **White-Labeling** - Branded dashboard for each client

<!-- For full usage details, see the [Dashboard User Guide](/dashboard). -->