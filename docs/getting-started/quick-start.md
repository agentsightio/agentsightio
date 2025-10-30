---
outline: deep
---

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

## Initial setup
1. Add your API key to a .env file.
2. Initialize the tracker in your code using the key.

```python
# Load API key and initialize AgentSight
import os
from agentsight import ConversationTracker
from dotenv import load_dotenv

load_dotenv()  # Load environment variables from .env file

# Retrieve the API key
api_key = os.getenv("AGENTSIGHT_API_KEY")

# Initialize the conversation tracker
tracker = ConversationTracker(api_key=api_key)
```

## Setting Your AgentSight API Key
You need an **AgentSight API key** to send data to your AgentSight dashboard.
Get your API key from the [AgentSight Dashboard](https://app.agentsight.io/).
For security and convenience, we recommend setting it as an environment variable.

:::tabs
== Export to CLI
```bash
export AGENTSIGHT_API_KEY="your_agentsight_api_key_here"
```
== .env file
```
AGENTSIGHT_API_KEY="your_agentsight_api_key_here"
```
:::

> Note: If you're using a `.env` file, make sure to call `load_dotenv()` before initializing ConversationTracker

This code will automatically use the API key from the `.env`:
```python
from dotenv import load_dotenv
load_dotenv()

tracker = ConversationTracker()
```

## Conversation Tracking
Conversations are uniquely identified to help you maintain context across multiple interactions. Once you create a conversation with your ID, use that same ID to reference your tracking methods with that conversation.

Here is how to specify a conversation and `conversation_id`:
```python
conversation_id="your_conversation_id"
tracker.get_or_create_conversation(
    conversation_id=conversation_id
)
```

:::info Conversation ID Priority
You can only pass conversation ID in `get_or_create_conversation`. If the `conversation_id` is not set, we will create one automatically for you which could result in creating new conversation in each iteration.
:::

> You can use `generate_conversation_id` function `from agentsight.helpers import generate_conversation_id`

How to pass tracking data about the conversation like geographical data, source and other, visit [Tracking conversation](../tracking/track-conversations.md)

## Tracking Data

### Track Question
Capture only the user's question without an immediate answer.

```python
tracker.track_question("How does machine learning work?")
```

> Read more [Track Question](../tracking/track-question.md)

### Track Answer
Log an AI response independently of a question.
```python
tracker.track_answer("Machine learning involves training algorithms...")
```

> Read more [Track Answer](../tracking/track-answer.md)

### Track Token Usage
Track usage tokens for your workflows.

```python
tracker.track_token_usage(
    prompt_tokens=100,
    completion_tokens=25,
    total_tokens=125
)
```

> Read more [Track Token Usage](../tracking/track-tokens.md)

### Track Action
Record specific actions or tool usage during an interaction.

```python
tracker.track_action(
    action_name="data_retrieval",
    duration_ms=250,
    tools_used={"database": "PostgreSQL"},
    response="Data successfully retrieved"
)
```

> Read more [Track Action](../tracking/track-actions.md)

### Track Button
Log user interface interactions and button clicks.

```python
tracker.track_button(
    button_event="user_selection",
    label="Confirm Order",
    value="order_id_123"
)
```

> Read more [Track Button](../tracking/track-buttons.md)

### Track Attachments
Send file attachments separately or with other tracking methods.

```python
tracker.track_attachments(
    attachments=[{
        'filename': 'report.pdf',
        'content': base64_encoded_content,
        'mime_type': 'application/pdf'
    }],
    mode='base64' # default
)
```

Attachment Modes:
- **Base64:** Encode files directly in payload
- **Form Data:** Send files as multipart form data

> Read more [Track Attachment](../tracking/track-attachments.md)

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
