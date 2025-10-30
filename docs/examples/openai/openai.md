---
outline: deep
---

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
from agentsight import ConversationTracker
from agentsight.helpers import generate_conversation_id
from dotenv import load_dotenv
load_dotenv()

# Initialize AgentSight tracker
tracker = ConversationTracker()

# Initialize OpenAI client
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

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

# Get response from GPT
response = client.chat.completions.create(
    model="gpt-4",
    messages=[{
        "role": "user",
        "content": user_question
    }]
)

# Extract the response
ai_response = response.choices[0].message.content

# Track the answer
tracker.track_answer(ai_response)

# Track token usage
tracker.track_token_usage(
    prompt_tokens=response.usage.prompt_tokens,
    completion_tokens=response.usage.completion_tokens,
    total_tokens=response.usage.total_tokens
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
from openai import OpenAI
from agentsight import ConversationTracker
from agentsight.helpers import generate_conversation_id
from dotenv import load_dotenv

load_dotenv()

# Initialize clients
tracker = ConversationTracker()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

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

# Define calculator tool for OpenAI
calculator_tool = {
    "type": "function",
    "function": {
        "name": "calculator",
        "description": "Perform basic mathematical operations",
        "parameters": {
            "type": "object",
            "properties": {
                "operation": {
                    "type": "string",
                    "enum": ["add", "subtract", "multiply", "divide"],
                    "description": "The mathematical operation to perform"
                },
                "a": {
                    "type": "number",
                    "description": "First number"
                },
                "b": {
                    "type": "number",
                    "description": "Second number"
                }
            },
            "required": ["operation", "a", "b"]
        }
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

# Get response from GPT with calculator tool
response = client.chat.completions.create(
    model="gpt-4",
    messages=[{
        "role": "user",
        "content": user_question
    }],
    tools=[calculator_tool],
    tool_choice="auto"
)

# Track initial token usage
tracker.track_token_usage(
    prompt_tokens=response.usage.prompt_tokens,
    completion_tokens=response.usage.completion_tokens,
    total_tokens=response.usage.total_tokens
)

# Process the response based on tool usage
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
            # Parse function arguments
            function_args = json.loads(tool_call.function.arguments)
            
            # Execute the calculator function (this will track the action)
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
    
    # Get final response with calculation results
    final_response = client.chat.completions.create(
        model="gpt-4",
        messages=messages
    )
    
    # Track additional token usage
    tracker.track_token_usage(
        prompt_tokens=final_response.usage.prompt_tokens,
        completion_tokens=final_response.usage.completion_tokens,
        total_tokens=final_response.usage.total_tokens
    )
    
    final_answer = final_response.choices[0].message.content
    used_tools = True
else:
    # No tool use needed
    final_answer = message.content
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