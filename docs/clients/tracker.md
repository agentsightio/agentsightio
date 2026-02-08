---
outline: deep
---

<CopyMarkdownButton />

# ConversationTracker

The `ConversationTracker` is your primary tool for tracking AI agent conversations in real-time. It stores all events in memory with precise timestamps, then sends them in chronological order when you're ready.

## Installation

```bash
pip install agentsight python-dotenv
```

## Quick Start

The tracker is **automatically initialized as a singleton** - just import and use:

```python
from agentsight import conversation_tracker
from dotenv import load_dotenv

load_dotenv()  # Loads AGENTSIGHT_API_KEY from .env

# Create conversation
conversation_tracker.get_or_create_conversation(
    conversation_id="chat-123",
    name="Support Chat"
)

# Track events
conversation_tracker.track_human_message("Hello!")
conversation_tracker.track_agent_message("Hi! How can I help?")

# Send to AgentSight
conversation_tracker.send_tracked_data()
```

## Configuration

### Automatic Initialization (Default)

The tracker automatically reads configuration from environment variables:

```bash
# .env file
AGENTSIGHT_API_KEY="your_api_key"
AGENTSIGHT_API_ENDPOINT="https://api.agentsight.io"  # Optional
AGENTSIGHT_LOG_LEVEL="INFO"  # Optional
```

No initialization code needed - just import and use!

## Creating Conversations

### Store in Memory

```python
conversation_tracker.get_or_create_conversation(
    conversation_id="support-123",
    customer_id="user-456",
    name="Password Reset",
    device="desktop",
    environment="production",
    metadata={"session_id": "abc123"}
)
```
> 📖 **[Learn more: Track Conversations →](../tracking/track-conversations.md)**

### Create Immediately

```python
# Sends to API right away
conversation_tracker.initialize_conversation(
    conversation_id="support-123",
    name="Password Reset"
)
```

> 📖 **[Learn more: Track Interaction →](../tracking/track-interaction.md)**

## Tracking Methods

### Track User Messages

```python
conversation_tracker.track_human_message(
    message="How do I reset my password?",
    metadata={"message_id": "msg_001"}
)
```

> 📖 **[Learn more: Track User Messages →](../tracking/track-question.md)**

### Track Agent Responses

```python
conversation_tracker.track_agent_message(
    message="Click 'Forgot Password' on the login page.",
    metadata={"model": "gpt-4"}
)
```

> 📖 **[Learn more: Track Agent Responses →](../tracking/track-answer.md)**

### Track Actions

```python
conversation_tracker.track_action(
    action_name="database_lookup",
    duration_ms=150,
    tools_used={"database": "PostgreSQL"},
    response="User found"
)
```

> 📖 **[Learn more: Track Actions →](../tracking/track-actions.md)**

### Track Buttons

```python
conversation_tracker.track_button(
    button_event="user_confirmation",
    label="Confirm Order",
    value="order_123"
)
```

> 📖 **[Learn more: Track Buttons →](../tracking/track-buttons.md)**

### Track Attachments

**Base64 Mode:**
```python
import base64

with open('report.pdf', 'rb') as f:
    file_data = base64.b64encode(f.read()).decode('utf-8')

conversation_tracker.track_attachments(
    attachments=[{
        'filename': 'report.pdf',
        'data': file_data,
        'mime_type': 'application/pdf'
    }],
    mode='base64'
)
```

**Form Data Mode:**
```python
with open('document.pdf', 'rb') as f:
    file_bytes = f.read()

conversation_tracker.track_attachments(
    attachments=[{
        'data': file_bytes,
        'filename': 'document.pdf'
    }],
    mode='form_data'
)
```

> 📖 **[Learn more: Track Attachments →](../tracking/track-attachments.md)**

### Track Token Usage

```python
conversation_tracker.track_token_usage(
    prompt_tokens=100,
    completion_tokens=25,
    total_tokens=125
)

# Get current usage
usage = conversation_tracker.get_token_usage()
print(f"Total tokens: {usage['total_tokens']}")
```

> 📖 **[Learn more: Track Token Usage →](../tracking/track-tokens.md)**

## Sending Tracked Data

```python
# Send all tracked data at once
response = conversation_tracker.send_tracked_data()

# Check results
print(f"Questions: {response['summary']['questions']}")
print(f"Answers: {response['summary']['answers']}")
print(f"Actions: {response['summary']['actions']}")
print(f"Errors: {response['summary']['errors']}")
```

### Response Structure

```python
{
    "items": [
        {
            "index": 0,
            "type": "conversation",
            "timestamp": "2024-01-15T10:30:00Z",
            "success": True
        }
    ],
    "summary": {
        "questions": 3,
        "answers": 3,
        "actions": 2,
        "buttons": 1,
        "attachments": 1,
        "errors": 0
    }
}
```

## View Tracked Data

```python
# View what's in memory before sending
summary = conversation_tracker.get_tracked_data_summary()

print(f"Total items: {summary['summary']['total']}")

# View chronological order
for item in summary['items']:
    print(f"{item['index']}. [{item['type']}] {item['timestamp']}")
```

## Best Practices

### 1. Track Events in Order

```python
# ✅ Correct chronological order
conversation_tracker.track_human_message("Question")
conversation_tracker.track_action("search")
conversation_tracker.track_agent_message("Answer")
```

### 2. Send at Appropriate Times

```python
# Option 1: After each interaction
def handle_query(query):
    conversation_tracker.track_human_message(query)
    answer = agent.process(query)
    conversation_tracker.track_agent_message(answer)
    conversation_tracker.send_tracked_data()

# Option 2: Batch multiple interactions
def handle_session(queries):
    for query in queries:
        conversation_tracker.track_human_message(query)
        conversation_tracker.track_agent_message(agent.process(query))
    conversation_tracker.send_tracked_data()
```

## Key Features

✅ **In-Memory Storage** - Zero performance impact during tracking  
✅ **Order Preservation** - Events sent in exact chronological order  
✅ **Singleton Pattern** - Automatically initialized, use anywhere  
✅ **Batch Processing** - Send multiple events in one API call  
✅ **Rich Metadata** - Add context to any tracked event  
✅ **Token Tracking** - Monitor LLM usage and costs  
✅ **Multi-Conversation** - Handle multiple conversations simultaneously  
