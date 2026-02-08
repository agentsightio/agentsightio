---
outline: deep
---

<CopyMarkdownButton />

# AgentSightAPI

The `AgentSightAPI` is your tool for fetching and querying conversation data from AgentSight. Use it to retrieve conversations, apply filters, search messages.

> Note: if you want to use regular api go to [API Reference](../getting-started/api-reference.md)

## Installation

```bash
pip install agentsight python-dotenv
```

## Quick Start

The API client is **automatically initialized as a singleton** - just import and use:

```python
from agentsight import agentsight_api
from dotenv import load_dotenv

load_dotenv()  # Loads AGENTSIGHT_API_KEY from .env

# Fetch conversations with filters
conversations = agentsight_api.fetch_conversations(
    feedback_sentiment="positive",
    page_size=10
)

# Get specific conversation
conversation = agentsight_api.fetch_conversation("conv-123")
```

## Configuration

### Automatic Initialization (Default)

The API client automatically reads configuration from environment variables:

```bash
# .env file
AGENTSIGHT_API_KEY="your_api_key"
AGENTSIGHT_API_ENDPOINT="https://api.agentsight.io"  # Optional
```

No initialization code needed - just import and use!

## Conversation IDs

`fetch_conversation()` accepts **both string conversation_id and integer database ID**:

```python
# Using string conversation_id
conversation = agentsight_api.fetch_conversation("conv-abc-123")

# Using integer database ID
conversation = agentsight_api.fetch_conversation(42)
```

The SDK automatically handles both types and returns the same data.

## Fetching Methods

### Fetch Conversations

```python
# Basic fetch with pagination
conversations = agentsight_api.fetch_conversations(
    page=1,
    page_size=20
)

# With filters
conversations = agentsight_api.fetch_conversations(
    feedback_sentiment="positive",
    device="mobile",
    started_at_after="2024-01-01T00:00:00Z"
)
```

> 📖 **[Learn more: Fetch Conversations →](../fetching/conversations.md)**

### Fetch Single Conversation

```python
# By string conversation_id
conversation = agentsight_api.fetch_conversation("conv-123")

# By integer database ID
conversation = agentsight_api.fetch_conversation(42)
```

> 📖 **[Learn more: Fetch Conversation →](../fetching/conversation.md)**

### Fetch Conversation Attachments

```python
attachments = agentsight_api.fetch_conversation_attachments(42)

print(f"Total attachments: {attachments['total_attachments']}")
for message in attachments['messages']:
    for att in message['attachments']:
        print(f"File: {att['filename']}")
```

> 📖 **[Learn more: Fetch Attachments →](../fetching/attachments.md)**
