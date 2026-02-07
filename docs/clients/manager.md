---
outline: deep
---

# ConversationManager

The `ConversationManager` is your tool for managing and updating existing conversations. Use it to rename conversations, add user feedback, mark favorites, update metadata, and delete conversations.

> Note: if you want to use regular api go to [API Reference](../getting-started/api-reference.md)

## Installation

```bash
pip install agentsight python-dotenv
```

## Quick Start

The manager is **automatically initialized as a singleton** - just import and use:

```python
from agentsight import conversation_manager
from dotenv import load_dotenv

load_dotenv()  # Loads AGENTSIGHT_API_KEY from .env

# Rename a conversation
conversation_manager.rename_conversation(
    conversation_id="conv-123",
    name="Resolved: Password Reset"
)

# Submit user feedback
conversation_manager.submit_feedback(
    conversation_id="conv-123",
    sentiment="positive",
    comment="Very helpful!"
)
```

## Configuration

### Automatic Initialization (Default)

The manager automatically reads configuration from environment variables:

```bash
# .env file
AGENTSIGHT_API_KEY="your_api_key"
AGENTSIGHT_API_ENDPOINT="https://api.agentsight.io"  # Optional
```

No initialization code needed - just import and use!

## Conversation IDs

All methods accept **both string conversation_id and integer database ID**:

```python
# Using string conversation_id (recommended)
conversation_manager.rename_conversation(
    conversation_id="conv-abc-123", 
    name="New Name"
)

# Using integer database ID
conversation_manager.rename_conversation(
    conversation_id=42, 
    name="New Name"
)
```

## Management Methods

### Submit Feedback

```python
from agentsight.enums import Sentiment

conversation_manager.submit_feedback(
    conversation_id="conv-123",
    sentiment=Sentiment.POSITIVE,
    comment="Very helpful!",
    metadata={"rating": 5}
)
```

> 📖 **[Learn more: Submit Feedback →](../managing/feedback.md)**

### Rename Conversation

```python
conversation_manager.rename_conversation(
    conversation_id="conv-123",
    name="Resolved: Account Access"
)
```

> 📖 **[Learn more: Rename Conversation →](../managing/rename.md)**

### Mark Conversation

```python
# Mark as favorite
conversation_manager.mark_conversation(
    conversation_id="conv-123",
    is_marked=True
)
```

> 📖 **[Learn more: Mark Conversation →](../managing/mark.md)**

### Update Conversation

```python
conversation_manager.update_conversation(
    conversation_id="conv-123",
    name="VIP Support",
    is_marked=True,
    metadata={"priority": "high"}
)
```

> 📖 **[Learn more: Update Conversation →](../managing/update.md)**

### Delete Conversation

```python
conversation_manager.delete_conversation(
    conversation_id="conv-123"
)
```

> 📖 **[Learn more: Delete Conversation →](../managing/delete.md)**
