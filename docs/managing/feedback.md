---
outline: deep
---

# Submit Feedback

The `submit_feedback()` method allows you to submit end-user feedback for a conversation. This feedback is automatically tagged as coming from customers and is used in analytics to measure user satisfaction.

## Method Signature

```python
conversation_manager.submit_feedback(
    conversation_id: Union[int, str],
    sentiment: Union[Sentiment, str],
    comment: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None
)
```

## Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `conversation_id` | string or integer | **Yes** | Conversation ID (string) or database ID (integer) |
| `sentiment` | string or Sentiment | **Yes** | User sentiment: `positive`, `neutral`, or `negative` |
| `comment` | string | No | User feedback text (max 5000 characters) |
| `metadata` | dict | No | Additional contextual information |

## Basic Usage

```python
from agentsight import conversation_manager

conversation_manager.submit_feedback(
    conversation_id="conv-123",
    sentiment="positive",
    comment="Very helpful!"
)
```

## Complete Usage Example

```python
from agentsight import conversation_manager
from agentsight.enums import Sentiment

conversation_manager.submit_feedback(
    conversation_id="support-session-456", # or use database ID
    sentiment=Sentiment.POSITIVE,
    comment="Excellent service! The agent was knowledgeable and resolved my password reset issue in under 3 minutes.",
    metadata={
        "rating": 5,
        "would_recommend": True,
        "issue_resolved": True,
        "response_time_rating": "excellent",
        "feedback_channel": "post_chat_survey",
        "collected_at": "2024-01-15T10:35:00Z"
    }
)
```

## Sentiment Values

| Sentiment | Description | Use Case |
|-----------|-------------|----------|
| `positive` | User is satisfied | Issue resolved, helpful response |
| `neutral` | User has mixed feelings | Partial help, average experience |
| `negative` | User is dissatisfied | Issue not resolved, poor experience |

:::tip Thumbs up/Thumbs down
You can also use this field if you only have thumbs up/thumbs down, just pass it as positive/negative
:::

## Using Database ID

```python
# Fetch conversation first
from agentsight import agentsight_api

conversation = agentsight_api.fetch_conversation("conv-123")

# Submit feedback using database ID
conversation_manager.submit_feedback(
    conversation_id=conversation['id'],  # Integer database ID
    sentiment="positive",
    comment="Great support!"
)
```

## Feedback Source

The feedback `source` is **automatically determined** by authentication method:

| Authentication | Source | Usage |
|----------------|--------|-------|
| **API Key** | `customer` | End-user feedback - **included in analytics** |
| **JWT** | `platform` | Internal feedback - **excluded from analytics** |

:::info Analytics Note
Only `customer` feedback (from API keys) is used in satisfaction metrics. This ensures analytics reflect genuine user experience, not internal QA reviews.
:::
