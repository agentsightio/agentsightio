---
outline: deep
---

# Core Concepts
Understanding AgentSight's core concepts will help you effectively track and analyze your AI agent conversations. In the following we'll explain how the system works.

## ConversationTracker
The `ConversationTracker` is your main entry point to the AgentSight system. Think of it as the control center for all conversation logging activities. It handles authentication, configuration, and provides specialized methods for different types of tracking scenarios.

```python
tracker = ConversationTracker(
    api_key='your_api_key'
)
```

The tracker manages your connection to AgentSight's backend and ensures all your conversation data is properly formatted and transmitted.

:::info Agent Identity & Organization
Every interaction is associated with a specific AI agent identity which is linked to API key, allowing you to differentiate performance between different AI agents or configurations.
:::

## Conversations & Context
A conversation represents a **logical grouping of related interactions** between users and your AI agent. Each conversation maintains context through a unique conversation ID that ties related messages together and maintains the sequence of interactions.

We recommend storing the conversation ID on your side where you have the UI for your AI agent. Each time users starts a new conversation or continues an existing one, you should use that same conversation ID for passing data to AgentSight. This ensures all related interactions are properly grouped together.

**Common Implementation Patterns:**
- **Web Applications:** Store conversation IDs in localStorage or cookies to persist across browser sessions
- **WhatsApp/SMS Bots:** Use the user's phone number as the conversation ID since that is one ongoing conversation thread
- **Mobile Apps:** Store conversation IDs in the device's local database or app storage, with separate IDs for different conversation threads within the app
- **Voice Agents:** You can use built in `generate_conversation_id` helper function since one call session would be one conversation

## In-Memory Data Storage with Batch Processing
AgentSight is built with an **in-memory-first architecture** that maximizes performance by storing all tracking data in memory until you're ready to send it. This design preserves the exact order of your conversation flow while using virtually no processing power or network resources during AI agent execution.

### How It Works
AgentSight stores all tracked data in memory with precise timestamps and maintains the sequential order of operations. Network calls only happen when you explicitly send the data:

```python
# All these operations are instant - no network calls
tracker.track_question("What is machine learning?")
tracker.track_action("research", tools_used={"search": "enabled"})
tracker.track_answer("Machine learning is a subset of AI...")
tracker.track_button("helpful", "👍", "positive_feedback")

# Only when you're ready - send everything at once
tracker.send_tracked_data()
```

### Performance Benefits
This architecture ensures that your AI agent runs at maximum performance while maintaining perfect conversation tracking and chronological accuracy. By separating the tracking operations from network communication, AgentSight provides:

- **Non-blocking tracking**: Never interrupts your AI agent's processing
- **Guaranteed order**: Chronological sequence is always preserved
- **Resource efficiency**: Minimal memory footprint and CPU usage
- **Flexible sending**: Send data when it makes sense for your application
- **Comprehensive monitoring**: Track everything without performance penalties

### Sequential Order Preservation
AgentSight automatically preserves the order of operations with microsecond precision:

```python
tracker.track_question("Solve this math problem: 2+2")    # Timestamp: 12:00:00.001Z
tracker.track_action("calculate", duration_ms=50)        # Timestamp: 12:00:00.055Z  
tracker.track_answer("The answer is 4")                  # Timestamp: 12:00:00.120Z
tracker.track_button("correct", "✓", "mark_correct")     # Timestamp: 12:00:00.125Z

# When sent, data arrives in exact chronological order
response = tracker.send_tracked_data()
```

:::warning Maintain Proper Order
The sequence in which you track interactions directly impacts how your conversation data appears in the dashboard and analytics. Always ensure you're tracking interactions in the exact order they occur in your application. Out-of-order tracking can lead to confusing conversation flows and inaccurate analytics.
:::

### Multi-Conversation Support
The system handles multiple concurrent conversations independently, maintaining separate ordered timelines for each:

```python
# Different conversations maintain separate order
tracker.track_question("Q1", conversation_id="user_123")
tracker.track_question("Q1", conversation_id="user_456") 
tracker.track_answer("A1", conversation_id="user_123")
tracker.track_answer("A1", conversation_id="user_456")

# Each conversation maintains its own chronological sequence
```

### When to Send Data
You have complete control over when to send your tracked data:

```python
# Option 1: Send after each complete interaction
def handle_user_query(query):
    tracker.track_question(query)
    response = await agent.process(query)
    tracker.track_answer(response)
    tracker.send_tracked_data()  # Send immediately
    return response

# Option 2: Batch multiple interactions
def handle_conversation_session():
    # Handle multiple interactions
    for query in user_queries:
        tracker.track_question(query)
        response = await agent.process(query)
        tracker.track_answer(response)
    
    # Send all at once at the end
    tracker.send_tracked_data()

# Option 3: Send periodically or on specific events
def periodic_send():
    # Send every 10 interactions or 5 minutes
    if interaction_count >= 10 or time_since_last_send >= 300:
        tracker.send_tracked_data()
```

## Rich Metadata System
Metadata provides the context that transforms raw conversation logs into actionable insights. You can attach contextual information like user types, language preferences, difficulty levels, and resolution statuses to any interaction.

### Metadata Usage
Metadata can be passed to each tracking method separately, allowing you to add specific context to individual interactions:
```python
# Add metadata to a specific question
tracker.track_question(
    question="How do I reset my password?",
    metadata={
        "user_type": "premium",
        "language": "en",
        "support_category": "account_management"
    }
)
```

> You can add `metadata` to any tracking method

## AgentSight Dashboard Overview
The AgentSight dashboard gives you and your clients real-time visibility into AI conversations. With built-in white-labeling, each client gets a branded view of their own data without any extra setup required.

Behind the scenes, you gain a powerful record of agent behavior. Every tracked interaction is processed into actionable insights, from response times and message flow to engagement trends. Easily audit performance, troubleshoot issues, and fine-tune agents across clients.

<!-- For full usage details, see the [Dashboard User Guide](/link). -->
