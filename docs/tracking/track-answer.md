---
outline: deep
---

# Track Answer Method

The `track_answer()` method allows you to log individual AI responses when you want to track an answer separately from its corresponding question, or in scenarios with complex, multi-step interactions.

## Method Signature

```python
def track_answer(
    answer: str,
    conversation_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
```

## Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `answer` | `str` | Yes | The AI agent's response |
| `conversation_id` | `str` | No | Unique identifier for the conversation (auto-generated if not provided) |
| `metadata` | `Dict[str, Any]` | No | Additional contextual information |

### Complete Usage Example

```python
tracker.track_answer(
    answer="Based on your requirements, I suggest using our Enterprise solution.",
    conversation_id="sales_consultation_789",
    metadata={
        "consultation_stage": "recommendation",
        "product_category": "enterprise_software",
        "customer_segment": "large_business"
    }
)
```
