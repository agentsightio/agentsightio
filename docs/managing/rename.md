---
outline: deep
---

<CopyMarkdownButton />

# Rename Conversation

The `rename_conversation()` method allows you to update the name of an existing conversation. Use descriptive names to organize conversations and make them easier to find in your analytics dashboard.

## Method Signature

```python
conversation_manager.rename_conversation(
    conversation_id: Union[int, str],
    name: str
)
```

## Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `conversation_id` | string or integer | **Yes** | Conversation ID (string) or database ID (integer) |
| `name` | string | **Yes** | New conversation name (max 255 characters) |


## Usage Example

```python
from agentsight import conversation_manager

conversation_manager.rename_conversation(
    conversation_id="support-session-456",  # or use database ID
    name="Account Access Issue"
)
```
