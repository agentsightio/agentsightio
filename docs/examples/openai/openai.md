---
outline: deep
---

<CopyMarkdownButton />

# OpenAI Integration Example

AgentSight provides seamless integration with OpenAI's GPT models, allowing you to track conversations, function calls, and performance metrics automatically.

## Prerequisites

:::tabs
== pip
```bash
pip install agentsight python-dotenv openai
```
== poetry
```bash
poetry add agentsight python-dotenv openai
```
== uv
```bash
uv add agentsight python-dotenv openai
```
:::

## Environment Setup

Set up your environment variables:

```bash
# .env
AGENTSIGHT_API_KEY=your_agentsight_api_key
OPENAI_API_KEY=your_openai_api_key
```

## Basic Integration

### Simple Chat with Tracking

```python
import os
from openai import OpenAI
from agentsight import conversation_tracker
from agentsight.helpers import generate_conversation_id
from dotenv import load_dotenv

load_dotenv()

# Initialize OpenAI client
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

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

# Get response from GPT
response = client.chat.completions.create(
    model="gpt-4",
    messages=[{"role": "user", "content": user_question}]
)

# Extract the response
ai_response = response.choices[0].message.content

# Track the answer
conversation_tracker.track_agent_message(
    answer=ai_response,
    metadata={
        "model": "gpt-4",
        "finish_reason": response.choices[0].finish_reason
    }
)

# Track token usage
conversation_tracker.track_token_usage(
    prompt_tokens=response.usage.prompt_tokens,
    completion_tokens=response.usage.completion_tokens,
    total_tokens=response.usage.total_tokens
)

# Send tracking data
result = conversation_tracker.send_tracked_data()

print(f"Question: {user_question}")
print(f"Answer: {ai_response}")
print(f"✅ Tracked: {result['summary']}")
```

## Advanced Integration with Function Calling

```python
import os
import json
import time
from openai import OpenAI
from agentsight import conversation_tracker
from agentsight.helpers import generate_conversation_id
from dotenv import load_dotenv

load_dotenv()

# Initialize OpenAI client
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

def calculator_function(a: float, b: float) -> float:
    """Simple calculator for addition"""
    start_time = time.time()
    
    result = a + b
    end_time = time.time()
    duration = int((end_time - start_time) * 1000)
    
    # Track the function call as an action
    conversation_tracker.track_action(
        action_name=f"calculator_addition",
        started_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(start_time)),
        ended_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(end_time)),
        duration_ms=duration,
        tools_used={
            "function": "calculator",
            "operation": addition
        },
        response=str(result) if result is not None else "Error",
        metadata={
            "parameters": {"a": a, "b": b},
            "result": result
        }
    )
    
    return result

# Define calculator tool for OpenAI
calculator_tool = {
    "type": "function",
    "function": {
        "name": "calculator",
        "description": "Perform addition",
        "parameters": {
            "type": "object",
            "properties": {
                "a": {"type": "number", "description": "First number"},
                "b": {"type": "number", "description": "Second number"}
            },
            "required": ["operation", "a", "b"]
        }
    }
}

# User input and conversation setup
user_question = "What's 24 + 3?"
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

# Get response from GPT with calculator tool
response = client.chat.completions.create(
    model="gpt-4",
    messages=[{"role": "user", "content": user_question}],
    tools=[calculator_tool],
    tool_choice="auto"
)

# Track initial token usage
conversation_tracker.track_token_usage(
    prompt_tokens=response.usage.prompt_tokens,
    completion_tokens=response.usage.completion_tokens,
    total_tokens=response.usage.total_tokens
)

# Process the response
message = response.choices[0].message

if message.tool_calls:
    # GPT wants to use the calculator
    messages = [
        {"role": "user", "content": user_question},
        {"role": "assistant", "content": message.content, "tool_calls": message.tool_calls}
    ]
    
    # Process each tool call
    for tool_call in message.tool_calls:
        if tool_call.function.name == "calculator":
            # Parse and execute function
            function_args = json.loads(tool_call.function.arguments)
            result = calculator_function(
                function_args["operation"],
                function_args["a"],
                function_args["b"]
            )
            
            # Add tool result to messages
            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": str(result)
            })
    
    # Get final response
    final_response = client.chat.completions.create(
        model="gpt-4",
        messages=messages
    )
    
    # Track additional token usage
    conversation_tracker.track_token_usage(
        prompt_tokens=final_response.usage.prompt_tokens,
        completion_tokens=final_response.usage.completion_tokens,
        total_tokens=final_response.usage.total_tokens
    )
    
    final_answer = final_response.choices[0].message.content
else:
    final_answer = message.content

# Track the final answer
conversation_tracker.track_agent_message(
    answer=final_answer,
    metadata={
        "model": "gpt-4",
        "used_tools": bool(message.tool_calls)
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
✅ **AI Responses** - All GPT outputs are logged  
✅ **Token Usage** - Monitor costs across conversations  
✅ **Function Calls** - Track tool usage and performance  
✅ **Execution Time** - Measure function call duration  
✅ **Errors** - Capture and log failures  

## Best Practices

### 1. Track Metadata

```python
# Add context to every interaction
conversation_tracker.track_agent_message(
    answer=ai_response,
    metadata={
        "model": "gpt-4",
        "temperature": 0.7,
        "finish_reason": response.choices[0].finish_reason,
        "response_time_ms": 850
    }
)
```

### 2. Handle Errors Gracefully

```python
try:
    response = client.chat.completions.create(...)
    conversation_tracker.track_agent_message(response.choices[0].message.content)
except Exception as e:
    conversation_tracker.track_action(
        action_name="openai_api_call",
        error_msg=str(e),
        metadata={"failed": True}
    )
```

### 3. Track All Tool Calls

```python
# Track every function execution
for tool_call in message.tool_calls:
    result = execute_function(tool_call)
    conversation_tracker.track_action(
        action_name=tool_call.function.name,
        tools_used={"function": tool_call.function.name},
        response=str(result)
    )
```