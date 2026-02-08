---
outline: deep
---

<CopyMarkdownButton />

# Manage Environments

Testing before going live is crucial and the same applies to your AI.
<!-- **AgentSight** lets you manage two separate environments: **development** and **production**. -->

## How it works

AgentSight tracks and stores all conversation data according to the environment you specify when sending data through the **Python SDK**.

We provide two environments to help you safely build, test, and deploy your conversational AI:
* **Development:** for testing and iteration.
* **Production:** for live, real-world interactions.

When data is sent through the SDK, AgentSight tags it with the specified environment, ensuring it’s saved and displayed in the correct context inside your dashboard.

## Rules & Behavior

| Environment | Purpose | Dashboard Access | Analytics Availability |
| --------------- | -------------------------------------------- | ----------------------------------------------------- | ---------------------------------------------------------------- |
| **Development** | Used for building and testing your AI.       | View transcripts, messages, actions, and attachments. | ❌ No analytics or reports (test data is excluded from insights). |
| **Production**  | Used for deployed, real-world conversations. | Full access to dashboards, analytics, and reports.    | ✅ Analytics and reports available.                               |

To view your development data inside the dashboard, simply toggle **Development Mode**.

> **Note:** Development is the default environment.

## How to Set the Environment

Environment selection is **conversation-based**, meaning you define it when initializing or creating a conversation.

All subsequent events (messages, metrics, actions, etc.) associated with that conversation will automatically inherit its environment setting.

### Setting for each conversation

You can specify it in either the `initialize_conversation()` or `get_or_create_conversation()` method.

```python
from agentsight import conversation_tracker

# Create or fetch a conversation in development mode
conversation = conversation_tracker.get_or_create_conversation(
    conversation_id="test-conv-123",
    customer_id="user_001",
    environment="development"
)

# For development (default)
prod_conversation = conversation_tracker.get_or_create_conversation(
    conversation_id="prod-conv-456",
    customer_id="user_002"
)
```

### Setting the Environment via `.env`

You can also set your AgentSight environment globally using environment variables.
This approach is useful if you want to define your environment once and avoid passing it manually in every SDK call.

**.env**

```bash
AGENTSIGHT_ENVIRONMENT=development  # Options: production, development
```

When this variable is set, the SDK automatically uses the defined environment for all tracked conversations and events.

For more configuration options, see the [Configuration](./configuration.md) page.
