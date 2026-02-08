---
outline: deep
---

<CopyMarkdownButton />

# Quickstart
Get started with AgentSight in seconds. With just a few lines of code, you can start monitoring your AI agent's conversations, questions, answers, and more. No setup or infrastructure required.

AgentSight is designed to be lightweight and developer-friendly. Instantiate the client with your API key, and you're ready to track your data.

## Installation
First, install the AgentSight SDK. We also recommend installing python-dotenv to manage your API key securely via environment variables.

:::tabs
== pip
```bash
pip install agentsight python-dotenv
```
== poetry
```bash
poetry add agentsight python-dotenv
```
== uv
```bash
uv add agentsight python-dotenv
```
:::

## Setup

1. Get your API key from the [AgentSight Dashboard](https://app.agentsight.io/)
2. Add it to a `.env` file:

```bash
AGENTSIGHT_API_KEY="your_api_key_here"
```

## Basic Usage

```python
from agentsight import conversation_tracker
from dotenv import load_dotenv

load_dotenv()

# 1. Create a conversation
conversation_tracker.get_or_create_conversation(
    conversation_id="chat-123",
    customer_id="user-456",
    name="Support Chat"
)

# 2. Track user message
conversation_tracker.track_human_message("How do I reset my password?")

# 3. Track AI response
conversation_tracker.track_agent_message("Click 'Forgot Password' on the login page.")

# 4. Send all tracked data
response = conversation_tracker.send_tracked_data()
print(f"✅ Sent {response['summary']['questions']} questions and {response['summary']['answers']} answers")
```

That's it! Your conversation is now tracked in AgentSight.

:::info Conversation tracking
Conversations are uniquely identified to help you maintain context across multiple interactions. Once you create a conversation with your ID, use that same ID to reference your tracking methods with that conversation.
:::

## What Can You Track?

- **Messages** - User questions and AI responses
- **Actions** - Tool usage, database queries, API calls
- **Attachments** - Files, images, documents
- **Buttons** - User interactions and clicks
- **Tokens** - LLM token usage for cost tracking

## Three SDK Clients

AgentSight provides three clients for different needs:

| Client | Purpose | Import |
|--------|---------|--------|
| **ConversationTracker** | Track conversations in real-time | `from agentsight import conversation_tracker` |
| **ConversationManager** | Manage conversations (rename, feedback, delete...) | `from agentsight import conversation_manager` |
| **AgentSightAPI** | Fetch and query conversation data | `from agentsight import agentsight_api` |

All clients are automatically initialized and ready to use.

## Example: Complete Conversation

```python
from agentsight import conversation_tracker
from dotenv import load_dotenv

load_dotenv()

# Create conversation
conversation_tracker.get_or_create_conversation(
    conversation_id="support-123",
    name="Password Reset"
)

# User asks
conversation_tracker.track_human_message("I can't log in")

# AI performs action
conversation_tracker.track_action(
    action_name="check_database",
    duration_ms=150,
    response="User found"
)

# AI responds
conversation_tracker.track_agent_message("I found your account. Let me help reset your password.")

# Track token usage
conversation_tracker.track_token_usage(
    prompt_tokens=45,
    completion_tokens=32,
    total_tokens=77
)

# User clicks button
conversation_tracker.track_button(
    button_event="password_reset",
    label="Send Reset Email",
    value="confirmed"
)

# Send everything
conversation_tracker.send_tracked_data()
```

## Next Steps
Now that you’ve set up the basics, let’s continue with looking into Core Concepts
<!-- ## Next Steps
Now that you’ve set up the basics, let’s look at how to fully leverage AgentSight’s capabilities: 
<div class="feature-grid">
  <div class="feature-card">
    <div class="feature-icon">🔧</div>
    <h3 class="feature-title">Integrations</h3>
    <p class="feature-description">
      See how AgentSight automatically instruments popular LLM and agent frameworks.
    </p>
  </div>
  
  <div class="feature-card">
    <div class="feature-icon">📖</div>
    <h3 class="feature-title">Examples</h3>
    <p class="feature-description">
      Explore detailed examples for various use cases and integrations.
    </p>
  </div>
  
  <div class="feature-card">
    <div class="feature-icon">📚</div>
    <h3 class="feature-title">SDK Reference</h3>
    <p class="feature-description">
      Dive deeper into the AgentSight SDK capabilities and API.
    </p>
  </div>
  
  <div class="feature-card">
    <div class="feature-icon">🎯</div>
    <h3 class="feature-title">Trace Decorator</h3>
    <p class="feature-description">
      Learn how to group operations and create custom traces using the @trace decorator.
    </p>
  </div>
</div> -->
