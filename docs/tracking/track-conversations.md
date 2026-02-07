---
outline: deep
---

# Track Conversations

The `get_or_create_conversation()` method creates or retrieves a conversation context for tracking. This establishes the conversation scope for all subsequent tracking operations.

## Method Signature

```python
tracker.get_or_create_conversation(
    conversation_id: str,
    customer_id: Optional[str] = None,
    customer_ip_address: Optional[str] = None,
    device: Optional[Literal["desktop", "mobile"]] = None,
    source: Optional[str] = None,
    language: Optional[str] = None,
    name: Optional[str] = None,
    environment: Literal["production", "development"] = "development",
    metadata: Optional[Dict[str, Any]] = None
)
```

## Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `conversation_id` | string | **Yes** | Unique identifier for the conversation |
| `customer_id` | string | No | Customer/user identifier |
| `customer_ip_address` | string | No | Customer IP address for geo-tracking |
| `device` | string | No | Device type: `desktop` or `mobile` |
| `source` | string | No | Source platform (e.g., `web`, `whatsapp`, `mobile_app`) |
| `language` | string | No | Language code (e.g., `en`, `es-ES`) |
| `name` | string | No | Conversation name/title |
| `environment` | string | No | `production` or `development` (default: `development`) |
| `metadata` | dict | No | Additional custom data |

## Basic Usage

```python
from agentsight import conversation_tracker

# Simple conversation
conversation_tracker.get_or_create_conversation(
    conversation_id="chat-123",
    customer_id="user-456"
)
```

## With Full Context

```python
conversation_tracker.get_or_create_conversation(
    conversation_id="support-ticket-789",
    customer_id="customer-abc",
    customer_ip_address="203.0.113.45",
    device="mobile",
    source="whatsapp",
    language="en-US",
    name="Password Reset Support",
    environment="production",
    metadata={
        "phone_number": "+1234567890",
        "session_start": "2024-01-15T10:30:00Z",
        "user_tier": "premium"
    }
)
```

## Multi-Channel Examples

### Web Chat

```python
conversation_tracker.get_or_create_conversation(
    conversation_id="web-session-101",
    customer_id="user-789",
    device="desktop",
    source="web",
    language="en",
    metadata={
        "browser": "Chrome",
        "page_url": "https://example.com/support"
    }
)
```

### WhatsApp Bot

```python
conversation_tracker.get_or_create_conversation(
    conversation_id=phone_number,  # Use phone number as ID
    customer_id=phone_number,
    device="mobile",
    source="whatsapp",
    language="en"
)
```

### Mobile App

```python
conversation_tracker.get_or_create_conversation(
    conversation_id=f"app-{user_id}-{session_id}",
    customer_id=user_id,
    device="mobile",
    source="ios_app",
    language="en",
    metadata={
        "app_version": "2.1.0",
        "os_version": "iOS 17.2"
    }
)
```

### Voice Agent

```python
from agentsight.helpers import generate_conversation_id

# Generate unique ID for each call
conversation_id = generate_conversation_id()

conversation_tracker.get_or_create_conversation(
    conversation_id=conversation_id,
    customer_id=caller_id,
    source="voice_call",
    language="en",
    metadata={
        "call_duration": 0,
        "phone_number": "+1234567890"
    }
)
```

## Generate Conversation ID

```python
from agentsight.helpers import generate_conversation_id

# Generate unique conversation ID
conversation_id = generate_conversation_id()

conversation_tracker.get_or_create_conversation(
    conversation_id=conversation_id
)
```

## Store vs Create Immediately

### Store in Memory (Default)

```python
# Stored in memory, sent with send_tracked_data()
conversation_tracker.get_or_create_conversation(
    conversation_id="support-123",
    name="Password Reset"
)

# ... track messages, actions, etc ...

# Send everything at once
conversation_tracker.send_tracked_data()
```

### Create Immediately

```python
# Sends to API right away
conversation_tracker.initialize_conversation(
    conversation_id="support-123",
    name="Password Reset"
)
```

:::tip When to Use Each
- **`get_or_create_conversation()`** - Store in memory, send later with batch
- **`initialize_conversation()`** - Create immediately in database (use when you want to track if users are acctually engaging wiht your agents, e.g. using on web page or not)
:::

## Important Notes

:::warning Auto-Generated IDs
If you don't call `get_or_create_conversation()`, AgentSight will auto-generate a conversation ID. This may create a new conversation on each iteration, fragmenting your analytics.
:::

:::info Conversation Context
All subsequent tracking methods (`track_human_message`, `track_agent_message`, etc.) are associated with this conversation.
:::

:::tip Data Persistence
When creating a **new** conversation, all parameters are saved. When the conversation **already exists**, the parameters won't override existing data.
:::

## Best Practices

### 1. Provide Rich Context

```python
# ✅ Good - detailed context for analytics
conversation_tracker.get_or_create_conversation(
    conversation_id="support-123",
    customer_id="user-456",
    customer_ip_address="203.0.113.45",
    device="mobile",
    source="whatsapp",
    language="en",
    metadata={
        "user_tier": "premium",
        "previous_tickets": 2,
        "account_age_days": 365
    }
)
```

### 2. Call Before Tracking

```python
# ✅ Correct order
conversation_tracker.get_or_create_conversation(conversation_id="chat-123")
conversation_tracker.track_human_message("Hello")
conversation_tracker.track_agent_message("Hi!")

# ❌ Wrong - no conversation context
conversation_tracker.track_human_message("Hello")
```