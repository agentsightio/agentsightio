---
outline: deep
---

# Mark Conversation

The `mark_conversation()` method allows you to mark or unmark a conversation as favorite/important. Use this to highlight conversations.

## Method Signature

```python
conversation_manager.mark_conversation(
    conversation_id: Union[int, str],
    is_marked: bool
)
```

## Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `conversation_id` | string or integer | **Yes** | Conversation ID (string) or database ID (integer) |
| `is_marked` | boolean | **Yes** | `True` to mark, `False` to unmark |

## Usage Example

```python
from agentsight import conversation_manager

# Mark as favorite
conversation_manager.mark_conversation(
    conversation_id="conv-123", # or use database ID
    is_marked=True
)

# Unmark
conversation_manager.mark_conversation(
    conversation_id="conv-123", # or use database ID
    is_marked=False
)
```
