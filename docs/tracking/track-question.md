---
outline: deep
---

# Track Question Method
The `track_question()` method allows you to log individual user questions when you want to track a question before having a corresponding answer, or in scenarios with asynchronous or multi-step interactions.

## Method Signature
```python
def track_question(
    question: str,
    conversation_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
```

## Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `question` | `str` | Yes | The user's question or input |
| `conversation_id` | `str` | No | Unique identifier for the conversation (auto-generated if not provided) |
| `metadata` | `Dict[str, Any]` | No | Additional contextual information |

## Complete Usage Example
```python
tracker.track_question(
    question="I'm experiencing issues with my account access",
    conversation_id="support_ticket_456",
    metadata={
        "department": "technical_support",
        "issue_type": "login_problem",
        "priority": "high"
    }
)
```

## Important Notes

:::info Conversation Context
If no `conversation_id` is provided, AgentSight will generate a unique identifier. Consistently using the same ID helps maintain conversation context.
:::

:::tip Conversation ID
Try using `tracker.set_conversation_id('your_conversation_id')` for setting global conversation ID.
:::
