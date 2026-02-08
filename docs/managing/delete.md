---
outline: deep
---

<CopyMarkdownButton />

# Delete Conversation

The `delete_conversation()` method allows you to **SOFT** delete a conversation. Soft deletion sets `is_deleted=True` and adds a `deleted_at` timestamp, but the conversation remains in the database and can be retrieved if needed.

## Method Signature

```python
conversation_manager.delete_conversation(
    conversation_id: Union[int, str]
)
```

## Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `conversation_id` | string or integer | **Yes** | Conversation ID (string) or database ID (integer) |

## Usage Example

```python
from agentsight import conversation_manager

# Soft delete conversation
conversation_manager.delete_conversation(
    conversation_id="conv-123" # or use database ID
)
```

## Soft Delete Behavior

:::info What is Soft Delete?
Soft delete **does not permanently remove** the conversation. Instead:
- Sets `is_deleted=True`
- Adds `deleted_at` timestamp
- Hides from default queries
- Can be retrieved with `include_deleted=true` filter
:::

```python
from agentsight import agentsight_api

# Delete conversation
conversation_manager.delete_conversation("conv-123")

# Still retrievable with special filter
conversations = agentsight_api.fetch_conversations(
    include_deleted=True
)
```
