---
outline: deep
---

# Anthropic Integration Example

AgentSight provides seamless integration with Anthropic's Claude models, allowing you to track conversations, tool usage, and performance metrics automatically.

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

### Simple Chat with Tracking

```python
import os
from anthropic import Anthropic
from agentsight import conversation_tracker
from agentsight.helpers import generate_conversation_id
from dotenv import load_dotenv

load_dotenv()

# Initialize Anthropic client
client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

# User question
user_question = "What's 127 multiplied by 8?"

# Generate conversation ID
conversation_id = generate_conversation_id()

# Initialize conversation
conversation_tracker.get_or_create_conversation(
    conversation_id=conversation_id,
    customer_id="user_123",
    name="Math Question"
)

# Track the question
conversation_tracker.track_human_message(
    question=user_question,
    metadata={"input_length": len(user_question)}
)

# Get response from Claude
message = client.messages.create(
    model="claude-3-5-sonnet-20241022",
    max_tokens=1024,
    messages=[{"role": "user", "content": user_question}]
)

# Extract the response
ai_response = message.content[0].text

# Track the answer
conversation_tracker.track_agent_message(
    answer=ai_response,
    metadata={
        "model": "claude-3-5-sonnet-20241022",
        "stop_reason": message.stop_reason
    }
)

# Track token usage
conversation_tracker.track_token_usage(
    prompt_tokens=message.usage.input_tokens,
    completion_tokens=message.usage.output_tokens,
    total_tokens=message.usage.input_tokens + message.usage.output_tokens
)

# Send tracking data
result = conversation_tracker.send_tracked_data()

print(f"Question: {user_question}")
print(f"Answer: {ai_response}")
print(f"✅ Tracked: {result['summary']}")
```

## Advanced Integration with Tool Use

```python
import os
import json
import time
from anthropic import Anthropic
from agentsight import conversation_tracker
from agentsight.helpers import generate_conversation_id
from dotenv import load_dotenv

load_dotenv()

# Initialize Anthropic client
client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

def calculator_function(operation: str, a: float, b: float) -> float:
    """Simple calculator function that we'll track"""
    start_time = time.time()
    
    operations = {
        "add": lambda: a + b,
        "multiply": lambda: a * b,
        "subtract": lambda: a - b,
        "divide": lambda: a / b if b != 0 else None
    }
    
    result = operations.get(operation, lambda: None)()
    end_time = time.time()
    duration = int((end_time - start_time) * 1000)
    
    # Track the tool call as an action
    conversation_tracker.track_action(
        action_name=f"calculator_{operation}",
        started_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(start_time)),
        ended_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(end_time)),
        duration_ms=duration,
        tools_used={
            "function": "calculator",
            "operation": operation
        },
        response=str(result) if result is not None else "Error",
        error_msg="Division by zero" if operation == "divide" and b == 0 else None,
        metadata={
            "parameters": {"a": a, "b": b},
            "result": result
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
            "operation": {
                "type": "string",
                "enum": ["add", "subtract", "multiply", "divide"],
                "description": "The mathematical operation to perform"
            },
            "a": {"type": "number", "description": "First number"},
            "b": {"type": "number", "description": "Second number"}
        },
        "required": ["operation", "a", "b"]
    }
}

# User input and conversation setup
user_question = "What's 127 multiplied by 8, and then add 25 to the result?"
conversation_id = generate_conversation_id()

# Initialize conversation
conversation_tracker.get_or_create_conversation(
    conversation_id=conversation_id,
    customer_id="user_456",
    device="desktop",
    name="Calculator Chat"
)

# Track the user question
conversation_tracker.track_human_message(
    question=user_question,
    metadata={"requires_calculation": True}
)

# Get response from Claude with calculator tool
message = client.messages.create(
    model="claude-3-5-sonnet-20241022",
    max_tokens=1024,
    tools=[calculator_tool],
    messages=[{"role": "user", "content": user_question}]
)

# Track initial token usage
conversation_tracker.track_token_usage(
    prompt_tokens=message.usage.input_tokens,
    completion_tokens=message.usage.output_tokens,
    total_tokens=message.usage.input_tokens + message.usage.output_tokens
)

# Process the response
if message.stop_reason == "tool_use":
    # Claude wants to use the calculator
    tool_results = []
    
    for content_block in message.content:
        if content_block.type == "tool_use":
            tool_input = content_block.input
            
            # Execute the calculator function
            result = calculator_function(
                tool_input["operation"],
                tool_input["a"],
                tool_input["b"]
            )
            
            tool_results.append({
                "type": "tool_result",
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
    conversation_tracker.track_token_usage(
        prompt_tokens=final_message.usage.input_tokens,
        completion_tokens=final_message.usage.output_tokens,
        total_tokens=final_message.usage.input_tokens + final_message.usage.output_tokens
    )
    
    final_answer = final_message.content[0].text
else:
    final_answer = message.content[0].text

# Track the final answer
conversation_tracker.track_agent_message(
    answer=final_answer,
    metadata={
        "model": "claude-3-5-sonnet-20241022",
        "used_tools": message.stop_reason == "tool_use"
    }
)

# Send tracking data
result = conversation_tracker.send_tracked_data()

# Display results
print(f"Question: {user_question}")
print(f"Answer: {final_answer}")
print(f"Token usage: {conversation_tracker.get_token_usage()}")
print(f"✅ Tracked: {result['summary']}")
```

## Key Features Tracked

✅ **User Questions** - Every input is captured  
✅ **Claude Responses** - All outputs are logged  
✅ **Token Usage** - Monitor costs across conversations  
✅ **Tool Use** - Track calculator and custom tools  
✅ **Execution Time** - Measure tool execution duration  
✅ **Errors** - Capture and log failures  

## Best Practices

### 1. Track Metadata

```python
# Add context to every interaction
conversation_tracker.track_agent_message(
    answer=ai_response,
    metadata={
        "model": "claude-3-5-sonnet-20241022",
        "stop_reason": message.stop_reason,
        "response_time_ms": 1200
    }
)
```

### 2. Handle Errors Gracefully

```python
try:
    message = client.messages.create(...)
    conversation_tracker.track_agent_message(message.content[0].text)
except Exception as e:
    conversation_tracker.track_action(
        action_name="anthropic_api_call",
        error_msg=str(e),
        metadata={"failed": True}
    )
```

### 3. Track All Tool Usage

```python
# Track every tool execution
for content_block in message.content:
    if content_block.type == "tool_use":
        result = execute_tool(content_block)
        conversation_tracker.track_action(
            action_name=content_block.name,
            tools_used={"tool": content_block.name},
            response=str(result)
        )
```