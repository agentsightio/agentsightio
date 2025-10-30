---
outline: deep
---

# Get or Create Conversation Method

The `get_or_create_conversation()` method initializes or retrieves a conversation context for tracking user interactions. This method establishes the conversation scope for all subsequent tracking operations and ensures proper data organization within AgentSight.

## Conversation Tracking

Conversations are uniquely identified to help you maintain context across multiple interactions. Once you create a conversation with your ID, use that same ID to reference your tracking methods with that conversation.

:::info Conversation ID Requirement
The `conversation_id` parameter is required when calling `get_or_create_conversation()`. If you don't call this method at all, AgentSight will auto-generate a conversation ID for you, which could result in creating new conversations on each iteration.
:::

## Method Signature

```python
def get_or_create_conversation(
    self, 
    conversation_id: str,
    customer_id: Optional[str] = None,
    customer_ip_address: Optional[str] = None,
    device: Optional[str] = None,
    source: Optional[str] = None,
    language: Optional[str] = None,
    environment: Literal["production", "development"] = "production",
    metadata: Optional[Dict[str, Any]] = None
):
```

## Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `conversation_id` | `str` | Yes | Unique identifier for the conversation |
| `customer_id` | `str` | No | Unique identifier for the customer/user |
| `customer_ip_address` | `str` | No | IP address of the customer for geographical tracking |
| `device` | `str` | No | Device type or identifier (e.g., "mobile", "desktop", "tablet") |
| `source` | `str` | No | Source platform or channel (e.g., "whatsapp", "web", "mobile_app") |
| `language` | `str` | No | Language code for the conversation (e.g., "en-US", "es-ES") |
| `environment` | `Literal["production", "development"]` | No | Specifies the environment in which the conversation is taking place. Defaults to `production`. |
| `metadata` | `Dict[str, Any]` | No | Additional contextual information about the conversation |

## Complete Usage Example

### Basic Conversation Creation

```python
# Initialize conversation with specific ID and customer
conversation_id = "test_1"
tracker.get_or_create_conversation(
    conversation_id=conversation_id,
    customer_id="1"
)
```

### Advanced Conversation Creation with Context

```python
# Create conversation with full context information
tracker.get_or_create_conversation(
    conversation_id="support_ticket_12345",
    customer_id="customer_abc",
    customer_ip_address="192.168.1.100",
    device="mobile",
    source="whatsapp",
    language="en-US",
    metadata={
        "user_agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 14_6 like Mac OS X)",
        "session_start": "2024-01-15T10:30:00Z"
    }
)
```

### Multi-Channel Conversation Examples

```python
# WhatsApp conversation
tracker.get_or_create_conversation(
    conversation_id="whatsapp_chat_789",
    customer_id="user_456",
    customer_ip_address="203.0.113.45",
    device="mobile",
    source="whatsapp",
    language="en-US",
    metadata={
        "phone_number": "+1234567890",
        "whatsapp_business": True
    }
)

# Web chat conversation
tracker.get_or_create_conversation(
    conversation_id="web_session_101",
    customer_id="user_789",
    customer_ip_address="198.51.100.25",
    device="desktop",
    source="web",
    language="en-US",
    metadata={
        "browser": "Chrome",
        "page_url": "https://example.com/support",
        "referrer": "https://google.com"
    }
)
```

### Conversation ID Management Examples

```python
# Example 1: Using your own conversation ID
conversation_id = "user_session_12345"
tracker.get_or_create_conversation(
    conversation_id=conversation_id,
    customer_id="customer_abc",
    device="tablet",
    source="web"
)

# Example 2: Using generated conversation ID
conversation_id = generate_conversation_id()
tracker.get_or_create_conversation(
    conversation_id=conversation_id,
    customer_id="customer_xyz",
    customer_ip_address="192.168.1.50",
    source="mobile_app"
)
```

## Conversation ID Generation

You can use the built-in helper function to generate unique conversation IDs:

```python
from agentsight.helpers import generate_conversation_id

# Generate a unique conversation ID
conversation_id = generate_conversation_id()
tracker.get_or_create_conversation(
    conversation_id=conversation_id
)
```

## Important Notes

:::info Conversation Context
All subsequent tracking methods (`track_question`, `track_answer`, `track_action`, etc.) will be associated with the conversation established by this method.
:::

:::info Passing Additional Information
When you pass additional information for a new conversation, we will save them but when the conversation already exists, those information will not override the existing info as those should be unique.
:::

:::tip Best Practices
- Use meaningful conversation IDs that help you identify sessions or interactions
- Always provide additional information from the conversation for extensive analytics
- Call this method before any other tracking operations
- Use consistent ID formats across your application
:::

:::warning Auto-Generated IDs
If you don't call `get_or_create_conversation()` at all, AgentSight will auto-generate a conversation ID for you. This may result in creating new conversations on each iteration, which could fragment your analytics.
:::
