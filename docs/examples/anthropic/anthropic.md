---
outline: deep
---

# Anthropic Integration Example

AgentSight provides seamless integration with Anthropic's Claude models, allowing you to track conversations, actions, and performance metrics automatically.

## Prerequisites

:::tabs
== pip
```bash
pip install agentsight python-dotenv anthropic
```
== poetry
```bash
poetry add agentsight python-dotenv anthropic
```
== uv
```bash
uv add agentsight python-dotenv anthropic
```
:::

## Environment Setup

Set up your environment variables:

```bash
# .env
AGENTSIGHT_API_KEY=your_agentsight_api_key
ANTHROPIC_API_KEY=your_anthropic_api_key
```

## Basic Integration

```python
import os
from anthropic import Anthropic
from agentsight import ConversationTracker
from agentsight.helpers import generate_conversation_id
from dotenv import load_dotenv
load_dotenv()

# Initialize AgentSight tracker
tracker = ConversationTracker()

# Initialize Anthropic client
client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

# User question
user_question = "What's 127 multiplied by 8?"

# Generate conversation ID
conversation_id = generate_conversation_id()

# Initialize conversation
tracker.get_or_create_conversation(
    conversation_id=conversation_id,
    customer_id="user_123"
)

# Track the question
tracker.track_question(user_question)

# Get response from Claude
message = client.messages.create(
    model="claude-3-5-sonnet-20241022",
    max_tokens=1024,
    messages=[{
        "role": "user",
        "content": user_question
    }]
)

# Extract the response
ai_response = message.content[0].text

# Track the answer
tracker.track_answer(ai_response)

# Track token usage
tracker.track_token_usage(
    prompt_tokens=message.usage.input_tokens,
    completion_tokens=message.usage.output_tokens,
    total_tokens=message.usage.input_tokens + message.usage.output_tokens
)

# Send tracking data
result = tracker.send_tracked_data()

print(f"Question: {user_question}")
print(f"Answer: {ai_response}")
print(f"Tracking sent: {result}")
```

## Advanced Integration with Function Calling

```python
import os
import json
import time
from anthropic import Anthropic
from agentsight import ConversationTracker
from agentsight.helpers import generate_conversation_id
from dotenv import load_dotenv

load_dotenv()

# Initialize clients
tracker = ConversationTracker()
client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

def calculator_function(operation: str, a: float, b: float) -> float:
    """Simple calculator function that we'll track"""
    start_time = time.time()
    
    if operation == "add":
        result = a + b
    elif operation == "multiply":
        result = a * b
    elif operation == "subtract":
        result = a - b
    elif operation == "divide":
        result = a / b if b != 0 else None
    else:
        result = None
    
    end_time = time.time()
    duration = int((end_time - start_time) * 1000)
    
    # Track the function call as an action
    tracker.track_action(
        action_name=f"calculator_{operation}",
        duration_ms=duration,
        response=str(result) if result is not None else "Error",
        error_msg=None if result is not None else "Division by zero" if operation == "divide" else "Invalid operation",
        metadata={
            "function": "calculator",
            "operation": operation,
            "parameters": {"a": a, "b": b},
            "tool_type": "calculator"
        }
    )
    
    return result

# Define calculator tool for Claude
calculator_tool = {
    "name": "calculator",
    "description": "Perform basic mathematical operations",
    "input_schema": {
        "type": "object",
        "properties": {
            "operation": {"type": "string", "enum": ["add", "subtract", "multiply", "divide"]},
            "a": {"type": "number"},
            "b": {"type": "number"}
        },
        "required": ["operation", "a", "b"]
    }
}

# User input and conversation setup
user_question = "What's 127 multiplied by 8, and then add 25 to the result?"
conversation_id = generate_conversation_id()

# Initialize conversation
tracker.get_or_create_conversation(
    conversation_id=conversation_id,
    customer_id="user_456",
    device="desktop"
)

# Track the user question
tracker.track_question(user_question)

# Get response from Claude with calculator tool
message = client.messages.create(
    model="claude-3-5-sonnet-20241022",
    max_tokens=1024,
    tools=[calculator_tool],
    messages=[{
        "role": "user",
        "content": user_question
    }]
)

# Track initial token usage
tracker.track_token_usage(
    prompt_tokens=message.usage.input_tokens,
    completion_tokens=message.usage.output_tokens,
    total_tokens=message.usage.input_tokens + message.usage.output_tokens
)

# Process the response based on tool usage
if message.stop_reason == "tool_use":
    # Claude wants to use the calculator
    tool_results = []
    
    for content_block in message.content:
        if content_block.type == "tool_use":
            tool_input = content_block.input
            
            # Execute the calculator function (this will track the action)
            result = calculator_function(
                tool_input["operation"],
                tool_input["a"],
                tool_input["b"]
            )
            
            tool_results.append({
                "tool_use_id": content_block.id,
                "content": str(result)
            })
    
    # Get final response with calculation results
    final_message = client.messages.create(
        model="claude-3-5-sonnet-20241022",
        max_tokens=1024,
        messages=[
            {"role": "user", "content": user_question},
            {"role": "assistant", "content": message.content},
            {"role": "user", "content": tool_results}
        ]
    )
    
    # Track additional token usage
    tracker.track_token_usage(
        prompt_tokens=final_message.usage.input_tokens,
        completion_tokens=final_message.usage.output_tokens,
        total_tokens=final_message.usage.input_tokens + final_message.usage.output_tokens
    )
    
    final_answer = final_message.content[0].text
    used_tools = True
else:
    # No tool use needed
    final_answer = message.content[0].text
    used_tools = False

# Track the final answer
tracker.track_answer(final_answer)

# Send tracking data
result = tracker.send_tracked_data()

print(f"Question: {user_question}")
print(f"Answer: {final_answer}")
print(f"Token usage: {tracker.get_token_usage()}")
print(f"Tracking sent: {result}")
```
