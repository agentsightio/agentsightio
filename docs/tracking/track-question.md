---
outline: deep
---

# Track Human Message Method
The `track_human_message()` method allows you to log individual user messages when you want to track a question before having a corresponding answer, or in scenarios with asynchronous or multi-step interactions.

## Method Signature
```python
def track_human_message(
    message: str,
    conversation_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
```

## Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `message` | `str` | Yes | The user's question or input |
| `metadata` | `Dict[str, Any]` | No | Additional contextual information |

## Complete Usage Example
```python
tracker.track_human_message(
    message="I'm experiencing issues with my account access",
    metadata={
        "department": "technical_support",
        "issue_type": "login_problem",
        "priority": "high"
    }
)
```
