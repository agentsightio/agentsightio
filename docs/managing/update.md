---
outline: deep
---

# Update Conversation

The `update_conversation()` method allows you to update multiple fields of a conversation in a single request. This is more efficient than calling individual methods when you need to change several properties at once.

## Method Signature

```python
conversation_manager.update_conversation(
    conversation_id: Union[int, str],
    name: Optional[str] = None,
    is_marked: Optional[bool] = None,
    customer_id: Optional[str] = None,
    device: Optional[str] = None,
    language: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None
)
```

## Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `conversation_id` | string or integer | **Yes** | Conversation ID (string) or database ID (integer) |
| `name` | string | No | Conversation name (max 255 characters) |
| `is_marked` | boolean | No | Mark as favorite/important |
| `customer_id` | string | No | Customer identifier |
| `device` | string | No | Device type |
| `language` | string | No | Language code |
| `metadata` | dict | No | Additional custom data |

:::tip All Fields Optional
Only include fields you want to update. All parameters except `conversation_id` are optional.
:::

## Usage Example

```python
from agentsight import conversation_manager

# Update multiple fields after conversation completion
conversation_manager.update_conversation(
    conversation_id="support-session-456",  # or use database ID
    name="✅ RESOLVED - Account Access (5 stars)",
    is_marked=True,
    metadata={
        "resolution_status": "resolved",
        "resolution_time_minutes": 5,
        "customer_satisfaction": 5,
        "tags": ["password-reset", "high-satisfaction"],
        "follow_up_required": False,
        "resolved_by": "AI Agent",
        "resolution_notes": "Successfully reset password and verified account access"
    }
)
```

## Best Practices

### 1. Update Multiple Fields Together

```python
# ✅ Good - single API call
conversation_manager.update_conversation(
    conversation_id="conv-123",
    name="Resolved Issue",
    is_marked=False,
    metadata={"status": "resolved"}
)

# ❌ Avoid - multiple API calls
conversation_manager.rename_conversation("conv-123", "Resolved Issue")
conversation_manager.mark_conversation("conv-123", False)
conversation_manager.update_conversation("conv-123", metadata={"status": "resolved"})
```

### 2. Preserve Existing Metadata

```python
# ✅ Good - merge with existing metadata
from agentsight import agentsight_api, conversation_manager

def safe_metadata_update(conversation_id, new_metadata):
    # Get existing metadata
    conv = agentsight_api.fetch_conversation(conversation_id)
    existing = conv.get('metadata', {})
    
    # Merge (new values override existing)
    merged = {**existing, **new_metadata}
    
    # Update
    conversation_manager.update_conversation(
        conversation_id=conversation_id,
        metadata=merged
    )
```