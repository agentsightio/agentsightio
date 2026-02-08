---
outline: deep
---

<CopyMarkdownButton />

# Fetch Conversations

The `fetch_conversations()` method allows you to retrieve a paginated list of conversations with powerful filtering options. Use it to build dashboards, query specific conversations, or export data.

## Method Signature

```python
agentsight_api.fetch_conversations(
    page: Optional[int] = None,
    page_size: Optional[int] = None,
    conversation_id: Optional[str] = None,
    customer_id: Optional[str] = None,
    name: Optional[str] = None,
    device: Optional[str] = None,
    language: Optional[str] = None,
    customer_ip_address: Optional[str] = None,
    is_marked: Optional[bool] = None,
    include_deleted: Optional[bool] = None,
    started_at_after: Optional[Union[str, datetime]] = None,
    started_at_before: Optional[Union[str, datetime]] = None,
    has_messages: Optional[bool] = None,
    message_contains: Optional[str] = None,
    action_name: Optional[str] = None,
    has_feedback: Optional[bool] = None,
    feedback_sentiment: Optional[str] = None,
    feedback_source: Optional[str] = None,
    metadata: Optional[str] = None,
    **extra_params
)
```

## Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `page` | integer | Page number (default: 1) |
| `page_size` | integer | Results per page (default: 10, max: 100) |
| `conversation_id` | string | Exact match for conversation ID |
| `customer_id` | string | Exact match for customer ID |
| `name` | string | Search in conversation name (case-insensitive) |
| `device` | string | Filter by device type |
| `language` | string | Filter by language code |
| `customer_ip_address` | string | Exact match for customer IP |
| `is_marked` | boolean | Filter by favorite status |
| `include_deleted` | boolean | Include soft-deleted conversations |
| `started_at_after` | datetime/string | Conversations started after timestamp |
| `started_at_before` | datetime/string | Conversations started before timestamp |
| `has_messages` | boolean | Only conversations with messages |
| `message_contains` | string | Search within message contents |
| `action_name` | string | Filter by action name |
| `has_feedback` | boolean | Only conversations with feedback |
| `feedback_sentiment` | string | Filter by sentiment: `positive`, `neutral`, `negative` |
| `feedback_source` | string | Filter by source: `customer`, `platform` |
| `metadata` | string | Filter by metadata (format: `key:value,key2:value2`) |

## Usage Example

```python
from agentsight import agentsight_api
from datetime import datetime, timedelta

# Fetch conversations with multiple filters
conversations = agentsight_api.fetch_conversations(
    feedback_sentiment="positive",
    feedback_source="customer",
    device="mobile",
    has_messages=True,
    started_at_after=(datetime.now() - timedelta(days=7)).isoformat(),
    page=1,
    page_size=20
)

# Process results
for conv in conversations['results']:
    print(f"Conversation: {conv['name']}")
    print(f"  Customer: {conv['customer_id']}")
    print(f"  Device: {conv['device']}")
    print(f"  Messages: {len(conv['messages'])}")
    print(f"  Feedbacks: {len(conv['feedbacks'])}")
```

## Filtering Examples

### By Customer

```python
# Specific customer
conversations = agentsight_api.fetch_conversations(
    customer_id="user-456"
)

# Partial customer ID match
conversations = agentsight_api.fetch_conversations(
    customer_id__icontains="premium"
)
```

### By Time Range

```python
from datetime import datetime, timedelta

# Last 24 hours
yesterday = datetime.now() - timedelta(days=1)
conversations = agentsight_api.fetch_conversations(
    started_at_after=yesterday.isoformat()
)

# Specific date range
conversations = agentsight_api.fetch_conversations(
    started_at_after="2024-01-01T00:00:00Z",
    started_at_before="2024-01-31T23:59:59Z"
)

# Last 7 days
week_ago = datetime.now() - timedelta(days=7)
conversations = agentsight_api.fetch_conversations(
    started_at_after=week_ago.isoformat()
)
```

### By Device and Language

```python
# Mobile conversations in English
conversations = agentsight_api.fetch_conversations(
    device="mobile",
    language="en"
)

# Desktop conversations
conversations = agentsight_api.fetch_conversations(
    device="desktop"
)
```

### By Feedback

```python
# Positive customer feedback
conversations = agentsight_api.fetch_conversations(
    feedback_sentiment="positive",
    feedback_source="customer"
)

# Negative feedback needing review
conversations = agentsight_api.fetch_conversations(
    feedback_sentiment="negative",
    is_marked=True
)

# Conversations without feedback
conversations = agentsight_api.fetch_conversations(
    has_feedback=False
)
```

### By Message Content

```python
# Search for specific keywords
conversations = agentsight_api.fetch_conversations(
    message_contains="password reset"
)

# Find technical support conversations
conversations = agentsight_api.fetch_conversations(
    message_contains="error",
    action_name="database_query"
)
```

### By Actions

```python
# Conversations with specific action
conversations = agentsight_api.fetch_conversations(
    action_name="database_lookup"
)

# Conversations with API calls
conversations = agentsight_api.fetch_conversations(
    action_name="api_call"
)
```

### By Metadata

```python
# Single metadata filter
conversations = agentsight_api.fetch_conversations(
    metadata="priority:high"
)

# Multiple metadata filters
conversations = agentsight_api.fetch_conversations(
    metadata="status:resolved,customer_tier:premium"
)

# Nested metadata
conversations = agentsight_api.fetch_conversations(
    metadata="analysis.sentiment:positive"
)
```

### Marked/Favorite Conversations

```python
# Only marked conversations
conversations = agentsight_api.fetch_conversations(
    is_marked=True
)

# Unmarked conversations
conversations = agentsight_api.fetch_conversations(
    is_marked=False
)
```

### Include Deleted

```python
# Include soft-deleted conversations
conversations = agentsight_api.fetch_conversations(
    include_deleted=True
)

# Filter to only deleted
all_convs = agentsight_api.fetch_conversations(include_deleted=True)
deleted_convs = [c for c in all_convs['results'] if c['is_deleted']]
```

## Combining Filters

```python
# Complex query: VIP customers with positive feedback
conversations = agentsight_api.fetch_conversations(
    metadata="customer_tier:vip",
    feedback_sentiment="positive",
    device="desktop",
    has_messages=True,
    is_marked=True,
    page_size=50
)

# Support tickets needing review
conversations = agentsight_api.fetch_conversations(
    feedback_sentiment="negative",
    is_marked=True,
    metadata="status:pending",
    started_at_after="2024-01-01T00:00:00Z"
)
```

## Pagination

```python
# Get specific page
conversations = agentsight_api.fetch_conversations(
    page=2,
    page_size=25
)
```

## Response Structure

```python
response = agentsight_api.fetch_conversations(page_size=2)

# Response structure:
{
    "count": 245,  # Total matching conversations
    "next": "https://api.agentsight.io/api/conversations/?page=2",
    "previous": None,
    "results": [
        {
            "id": 42,
            "conversation_id": "conv-abc-123",
            "name": "Support Chat",
            "customer_id": "user-456",
            "customer_ip_address": "203.0.113.45",
            "device": "desktop",
            "language": "en",
            "environment": "production",
            "is_marked": True,
            "is_deleted": False,
            "started_at": "2024-01-15T10:30:00Z",
            "ended_at": "2024-01-15T10:35:00Z",
            "metadata": {...},
            "geo_location": {...},
            "messages": [...],
            "feedbacks": [...]
        }
    ]
}
```
