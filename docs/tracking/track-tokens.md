---
outline: deep
---

<CopyMarkdownButton />

# Track Token Usage Method

The `track_token_usage()` method allows you to monitor and record token consumption for your AI agent's interactions. This provides visibility into the computational costs associated with LLM calls and embeddings, helping you optimize performance and manage usage costs.

## Token Usage Tracking Concept

AgentSight uses a **cumulative token tracking system** that works as follows:

1. **Accumulation**: Each call to `track_token_usage()` **adds** the provided token counts to the existing totals
2. **Session Scope**: Token counts accumulate throughout the session cycle as you are counting them
3. **Reset on Send**: When you call `send_tracked_data()`, all token counters are reset to 0 for the next conversation cycle

This approach allows you to track tokens from multiple LLM calls within a single session and get accurate total usage before sending the data to AgentSight.

:::info Cumulative Token Tracking
Token counts are **additive** - each call adds to the running total rather than replacing it. This allows you to track tokens across multiple LLM interactions within the same iteration.
:::

## Method Signature

```python
def track_token_usage(
    self,
    prompt_tokens: Optional[int] = 0,
    completion_tokens: Optional[int] = 0,
    total_tokens: Optional[int] = 0,
    embedding_tokens: Optional[int] = 0
) -> None:
```

## Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `prompt_tokens` | `int` | No | Number of tokens used in the input/prompt (default: 0) |
| `completion_tokens` | `int` | No | Number of tokens generated in the completion (default: 0) |
| `total_tokens` | `int` | No | Total tokens used (prompt + completion) (default: 0) |
| `embedding_tokens` | `int` | No | Number of tokens used for embeddings (default: 0) |

## Complete Usage Example

```python
# Track token usage from the LLM interactions
tracker.track_token_usage(
    prompt_tokens=100,
    completion_tokens=25,
    total_tokens=125
)
```

## Retrieving Token Usage Data

Use the `get_token_usage()` method to retrieve current token statistics:

```python
# Get current token usage for the conversation
token_data = tracker.get_token_usage()
print(token_data)
```

## Cumulative Token Tracking Example

```python
# First LLM call
tracker.track_token_usage(
    prompt_tokens=50,
    completion_tokens=20,
    total_tokens=70
)

print(tracker.get_token_usage())
# Output: {'prompt_llm_token_count': 50, 'completion_llm_token_count': 20, 'total_llm_token_count': 70, 'total_embedding_token_count': 0}

# Second LLM call - tokens are added to existing totals
tracker.track_token_usage(
    prompt_tokens=30,
    completion_tokens=15,
    total_tokens=45
)

print(tracker.get_token_usage())
# Output: {'prompt_llm_token_count': 80, 'completion_llm_token_count': 35, 'total_llm_token_count': 115, 'total_embedding_token_count': 0}

# Send tracked data - this resets all counters to 0
result = tracker.send_tracked_data()

print(tracker.get_token_usage())
# Output: {'prompt_llm_token_count': 0, 'completion_llm_token_count': 0, 'total_llm_token_count': 0, 'total_embedding_token_count': 0}
```

## Automatic Token Handlers

AgentSight provides automatic token tracking integrations for popular AI frameworks. These handlers automatically capture token usage without requiring manual `track_token_usage()` calls.

### Available Token Handlers

- **LlamaIndex**: Automatically tracks tokens from LlamaIndex LLM calls
- **LangChain**: Automatically tracks tokens from LangChain LLM interactions

### Enabling Automatic Token Handlers

To activate automatic token tracking, set the environment variable:

```bash
# For LlamaIndex automatic tracking
AGENTSIGHT_TOKEN_HANDLER_TYPE=llamaindex

# For LangChain automatic tracking
AGENTSIGHT_TOKEN_HANDLER_TYPE=langchain
```

### Example with Automatic Token Handler

```python
import os
from agentsight import ConversationTracker

# Enable automatic LlamaIndex token tracking
os.environ["AGENTSIGHT_TOKEN_HANDLER_TYPE"] = "llamaindex"

tracker = ConversationTracker()

# Your LlamaIndex LLM calls will automatically track tokens
from llama_index.llms.openai import OpenAI

llm = OpenAI(model="gpt-3.5-turbo")
response = llm.complete("Hello, world!")

# Tokens are automatically tracked - no manual tracking needed
print(tracker.get_token_usage())
```

:::info Automatic vs Manual Tracking
When using automatic token handlers, you don't need to manually call `track_token_usage()`. The integration captures token usage automatically from your framework's LLM calls.
:::

:::warning Dependencies
For automatic token handlers we are expecting that you have already instaled base packages for that specific AI framework. If you did not install them, automatic tracker will not be set.
:::

## Use Cases

- **Cost Management:** Monitor token usage to estimate and control LLM costs
- **Performance Optimization:** Identify conversations with high token consumption
- **Usage Analytics:** Track token patterns across different conversation types
- **Billing Insights:** Provide detailed usage reports for cost allocation

## Important Notes

:::tip Best Practices
- Track token usage immediately after each LLM call for accurate accounting
- Include embedding tokens when using vector databases or similarity search
- Use automatic token handlers when available for your framework
- Monitor cumulative usage throughout long conversations
:::

:::warning Counter Reset
Token counters are reset to 0 when you call `send_tracked_data()`. Make sure to send data at appropriate conversation boundaries.
:::
