---
outline: deep
---

# Fetch Conversation

The `fetch_conversation()` method allows you to retrieve a single conversation with all its messages, actions, attachments, and feedback. This provides a complete detailed view of a specific conversation.

## Method Signature

```python
agentsight_api.fetch_conversation(
    conversation_id: Union[int, str]
)
```

## Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `conversation_id` | string or integer | **Yes** | Conversation ID (string) or database ID (integer) |

## Usage Example

```python
from agentsight import agentsight_api

# Fetch by string conversation_id
conversation = agentsight_api.fetch_conversation("conv-abc-123") # or database ID

print(f"Conversation: {conversation['name']}")
print(f"Messages: {len(conversation['messages'])}")
print(f"Feedbacks: {len(conversation['feedbacks'])}")
```

## What's Included

The response contains the complete conversation with:

- **Basic Info**: ID, name, customer_id, device, language, environment
- **Timestamps**: started_at, ended_at, deleted_at
- **Status**: is_marked, is_deleted, is_used
- **Messages**: All messages with content, sender, timestamp, metadata
- **Actions**: Action logs with tools_used, duration, response
- **Attachments**: Files with URLs, filenames, sizes, mime types
- **Feedback**: User feedback with sentiment, comments, source
- **Metadata**: Custom conversation metadata
- **Geo Location**: IP-based location data (if available)

## Response Structure

```python
conversation = agentsight_api.fetch_conversation("conv-123")

# Complete response structure:
{
    "id": 42,
    "conversation_id": "conv-abc-123",
    "name": "Support Chat",
    "customer_id": "user-456",
    "customer_ip_address": "203.0.113.45",
    "device": "desktop",
    "language": "en",
    "environment": "production",
    "is_marked": True,
    "is_deleted": False,
    "is_used": True,
    "started_at": "2024-01-15T10:30:00Z",
    "ended_at": "2024-01-15T10:35:00Z",
    "deleted_at": None,
    "metadata": {
        "priority": "high",
        "customer_tier": "premium"
    },
    "geo_location": {
        "ip_address": "203.0.113.45",
        "city": "New York",
        "country": "US",
        "timezone_name": "America/New_York"
    },
    "messages": [
        {
            "id": 101,
            "timestamp": "2024-01-15T10:30:05Z",
            "sender": "end_user",
            "content": "I need help with my account",
            "action_name": None,
            "metadata": {},
            "attachments": [],
            "action_logs": [],
            "button": None
        },
        {
            "id": 102,
            "timestamp": "2024-01-15T10:30:08Z",
            "sender": "agent",
            "content": "Action database_lookup performed",
            "action_name": "database_lookup",
            "metadata": {},
            "attachments": [],
            "action_logs": [
                {
                    "id": 50,
                    "started_at": "2024-01-15T10:30:07Z",
                    "ended_at": "2024-01-15T10:30:08Z",
                    "duration_ms": 150,
                    "tools_used": {
                        "database": "users_db"
                    },
                    "response": "User found",
                    "error_message": "",
                    "metadata": {}
                }
            ],
            "button": None
        }
    ],
    "feedbacks": [
        {
            "id": 5,
            "sentiment": "positive",
            "source": "customer",
            "comment": "Very helpful!",
            "metadata": {},
            "created_at": "2024-01-15T10:35:00Z"
        }
    ]
}
```