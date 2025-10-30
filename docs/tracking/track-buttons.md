---
outline: deep
---


# Track Button Method

The `track_button()` method allows you to log user interface interactions, specifically button clicks and selections. This provides insights into how users interact with your AI agent's interface elements.

## Method Signature

```python
def track_button(
    button_event: str,
    label: str,
    value: str,
    conversation_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
```

## Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `button_event` | `str` | Yes | Description of what this button is used for |
| `label` | `str` | Yes | The button label/text displayed to the user |
| `value` | `str` | Yes | The button value |
| `conversation_id` | `str` | No | Unique identifier for the conversation (auto-generated if not provided) |
| `metadata` | `Dict[str, Any]` | No | Additional contextual information |

## Complete Usage Example

### E-commerce Button Tracking

```python
# Track product selection button
tracker.track_button(
    button_event="product_selection",
    label="Add to Cart",
    value="product_123",
    conversation_id="shopping_session_456",
    metadata={
        "product_name": "Wireless Headphones",
        "price": 99.99,
        "category": "electronics"
    }
)
```

### Support Ticket Actions

```python
# Track support resolution button
tracker.track_button(
    button_event="ticket_resolution",
    label="Mark as Resolved",
    value="resolved_satisfied",
    conversation_id="support_ticket_789",
    metadata={
        "resolution_type": "self_service",
        "satisfaction_rating": 5,
        "issue_category": "billing"
    }
)
```

### Navigation Tracking

```python
# Track navigation button clicks
tracker.track_button(
    button_event="navigation_action",
    label="View Order History",
    value="order_history_page",
    metadata={
        "section": "account_management",
        "user_type": "premium_member"
    }
)
```

## Use Cases

- **User Experience Analytics:** Track which interface elements users interact with most frequently to optimize your UI design.
- **Conversion Tracking:** Monitor button clicks that lead to important actions like purchases, sign-ups, or support requests.
- **A/B Testing:** Compare the performance of different button labels or placements by tracking interaction rates.
- **User Journey Mapping:** Understand how users navigate through your AI agent's interface and identify common paths.

## Important Notes

:::info Button Context
Button interactions are tracked within the context of a conversation. Use the same `conversation_id` across related interactions to maintain proper context.
:::

:::warning Required Fields
All three core fields (`button_event`, `label`, and `value`) are required and cannot be empty. The method will raise an exception if any of these fields are missing or empty.
:::

:::tip Best Practices
- Use descriptive `button_event` names that clearly indicate the button's purpose
- Keep `label` text consistent with what users actually see in the interface
- Use meaningful `value` strings that help identify the specific action or selection
- Include relevant metadata to provide additional context for analytics
:::
