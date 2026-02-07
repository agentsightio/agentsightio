---
outline: deep
---

# Track Agent Message Method

The `track_agent_message()` method allows you to log individual AI responses when you want to track an answer separately from its corresponding question, or in scenarios with complex, multi-step interactions.

## Method Signature

```python
def track_agent_message(
    message: str,
    conversation_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
```

## Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `message` | `str` | Yes | The AI agent's response |
| `metadata` | `Dict[str, Any]` | No | Additional contextual information |

### Complete Usage Example

```python
tracker.track_agent_message(
    message="Based on your requirements, I suggest using our Enterprise solution.",
    metadata={
        "consultation_stage": "recommendation",
        "product_category": "enterprise_software",
        "customer_segment": "large_business"
    }
)
```
