---
outline: deep
---

# FastAPI Integration with LangChain

AgentSight's in-memory architecture is perfect for FastAPI applications using LangChain. Track conversations instantly during request processing, then send data in background tasks to avoid impacting response times.

## Prerequisites

:::tabs
== pip
```bash
pip install agentsight fastapi uvicorn python-dotenv langchain langchain-anthropic langchain-openai
```
== poetry
```bash
poetry add agentsight fastapi uvicorn python-dotenv langchain langchain-anthropic langchain-openai
```
== uv
```bash
uv add agentsight fastapi uvicorn python-dotenv langchain langchain-anthropic langchain-openai
```
:::

## Environment Setup

```bash
# .env
AGENTSIGHT_API_KEY=your_agentsight_api_key
ANTHROPIC_API_KEY=your_anthropic_api_key
# or OPENAI_API_KEY=your_openai_api_key
```

## Basic FastAPI Integration

```python
from fastapi import FastAPI, BackgroundTasks
from pydantic import BaseModel
from agentsight import conversation_tracker
from agentsight.helpers import generate_conversation_id
from langchain_anthropic import ChatAnthropic
from typing import Optional
from dotenv import load_dotenv
import time

load_dotenv()

app = FastAPI(title="AgentSight LangChain FastAPI Example")

# Initialize LLM
llm = ChatAnthropic(model="claude-3-5-sonnet-20241022")

class ChatRequest(BaseModel):
    message: str
    conversation_id: Optional[str] = None
    customer_id: Optional[str] = None

class ChatResponse(BaseModel):
    response: str
    conversation_id: str

async def send_tracking_data():
    """Background task to send tracking data"""
    try:
        result = conversation_tracker.send_tracked_data()
        print(f"✅ Sent tracking data: {result['summary']}")
    except Exception as e:
        print(f"❌ Failed to send tracking data: {e}")

@app.post("/chat", response_model=ChatResponse)
async def chat_endpoint(
    request: ChatRequest, 
    background_tasks: BackgroundTasks
):
    """Chat endpoint with instant tracking and background sending"""
    
    # Generate conversation ID if not provided
    conversation_id = request.conversation_id or generate_conversation_id()
    
    # Initialize conversation
    conversation_tracker.get_or_create_conversation(
        conversation_id=conversation_id,
        customer_id=request.customer_id,
        source="api",
        device="desktop",
        name="FastAPI LangChain Chat"
    )
    
    # Track user message
    conversation_tracker.track_human_message(
        question=request.message,
        metadata={
            "endpoint": "/chat",
            "message_length": len(request.message)
        }
    )
    
    # Get AI response
    start_time = time.time()
    result = llm.invoke([{"role": "user", "content": request.message}])
    duration_ms = int((time.time() - start_time) * 1000)
    
    # Track agent response
    conversation_tracker.track_agent_message(
        answer=result.content,
        metadata={
            "model": "claude-3-5-sonnet-20241022",
            "response_time_ms": duration_ms
        }
    )
    
    # Schedule background task (non-blocking)
    background_tasks.add_task(send_tracking_data)
    
    return ChatResponse(
        response=result.content,
        conversation_id=conversation_id
    )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
```

## Advanced Integration with Tools

```python
from fastapi import FastAPI, BackgroundTasks, HTTPException
from pydantic import BaseModel
from agentsight import conversation_tracker
from agentsight.helpers import generate_conversation_id
from langchain_anthropic import ChatAnthropic
from langchain.tools import tool
from langchain.agents import create_agent
from typing import Optional
from dotenv import load_dotenv
import time

load_dotenv()

app = FastAPI(title="Advanced AgentSight LangChain FastAPI")

# Calculator tool with tracking
@tool
def calculate(expression: str) -> str:
    """
    Calculate a mathematical expression.
    
    Args:
        expression: Mathematical expression like "2+2" or "10*5"
    """
    start_time = time.time()
    
    try:
        # Safely evaluate expressions
        result = eval(expression.replace("^", "**"))
        end_time = time.time()
        duration_ms = int((end_time - start_time) * 1000)
        
        # Track successful calculation
        conversation_tracker.track_action(
            action_name="calculate",
            started_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(start_time)),
            ended_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(end_time)),
            duration_ms=duration_ms,
            tools_used={"tool": "calculator"},
            response=str(result),
            metadata={
                "expression": expression,
                "result": result,
                "status": "success"
            }
        )
        
        return f"The result is: {result}"
    except Exception as e:
        end_time = time.time()
        duration_ms = int((end_time - start_time) * 1000)
        
        # Track failed calculation
        conversation_tracker.track_action(
            action_name="calculate",
            started_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(start_time)),
            ended_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(end_time)),
            duration_ms=duration_ms,
            tools_used={"tool": "calculator"},
            error_msg=str(e),
            metadata={
                "expression": expression,
                "status": "failed"
            }
        )
        
        return f"Error: {str(e)}"

@tool
def get_weather(city: str) -> str:
    """
    Get current weather for a city.
    
    Args:
        city: City name to get weather for
    """
    start_time = time.time()
    
    try:
        # Simulate weather API call
        weather_data = {
            "san francisco": "Sunny, 68°F",
            "new york": "Cloudy, 55°F",
            "london": "Rainy, 52°F"
        }
        
        result = weather_data.get(city.lower(), f"Weather data not available for {city}")
        end_time = time.time()
        duration_ms = int((end_time - start_time) * 1000)
        
        # Track weather lookup
        conversation_tracker.track_action(
            action_name="get_weather",
            started_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(start_time)),
            ended_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(end_time)),
            duration_ms=duration_ms,
            tools_used={"tool": "weather_api"},
            response=result,
            metadata={
                "city": city,
                "status": "success"
            }
        )
        
        return result
    except Exception as e:
        end_time = time.time()
        duration_ms = int((end_time - start_time) * 1000)
        
        conversation_tracker.track_action(
            action_name="get_weather",
            duration_ms=duration_ms,
            error_msg=str(e),
            metadata={"city": city, "status": "failed"}
        )
        
        return f"Error getting weather: {str(e)}"

# Initialize LLM and tools
llm = ChatAnthropic(model="claude-3-5-sonnet-20241022")
tools = [calculate, get_weather]

# Create agent
agent = create_agent(
    model=llm,
    tools=tools
)

class ChatRequest(BaseModel):
    message: str
    conversation_id: Optional[str] = None
    customer_id: Optional[str] = None

class ChatResponse(BaseModel):
    response: str
    conversation_id: str
    tools_used: list[str]

async def send_tracking_data():
    """Background task to send tracking data"""
    try:
        result = conversation_tracker.send_tracked_data()
        print(f"✅ Sent tracking data: {result['summary']}")
    except Exception as e:
        print(f"❌ Failed to send tracking data: {e}")

@app.post("/chat", response_model=ChatResponse)
async def chat_endpoint(
    request: ChatRequest, 
    background_tasks: BackgroundTasks
):
    """Advanced chat endpoint with tool tracking"""
    
    # Generate conversation ID
    conversation_id = request.conversation_id or generate_conversation_id()
    
    # Initialize conversation
    conversation_tracker.get_or_create_conversation(
        conversation_id=conversation_id,
        customer_id=request.customer_id,
        source="api",
        name="Agent Chat with Tools"
    )
    
    # Track question
    conversation_tracker.track_human_message(
        question=request.message,
        metadata={
            "endpoint": "/chat",
            "has_customer_id": bool(request.customer_id)
        }
    )
    
    try:
        # Process with agent
        start_time = time.time()
        result = agent.invoke(
            {"messages": [{"role": "user", "content": request.message}]}
        )
        duration_ms = int((time.time() - start_time) * 1000)
        
        # Extract response and tools used
        final_message = result["messages"][-1].content
        tools_used = [msg.name for msg in result["messages"] if hasattr(msg, 'name')]
        
        # Track agent response
        conversation_tracker.track_agent_message(
            answer=final_message,
            metadata={
                "model": "claude-3-5-sonnet-20241022",
                "response_time_ms": duration_ms,
                "tools_available": ["calculate", "get_weather"],
                "tools_used": tools_used
            }
        )
        
        # Schedule background sending
        background_tasks.add_task(send_tracking_data)
        
        return ChatResponse(
            response=final_message,
            conversation_id=conversation_id,
            tools_used=tools_used
        )
        
    except Exception as e:
        duration_ms = int((time.time() - start_time) * 1000)
        
        # Track error
        conversation_tracker.track_action(
            action_name="chat_error",
            duration_ms=duration_ms,
            error_msg=str(e),
            metadata={
                "error_type": type(e).__name__,
                "endpoint": "/chat"
            }
        )
        
        # Still send tracking data
        background_tasks.add_task(send_tracking_data)
        
        raise HTTPException(status_code=500, detail=f"Chat error: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
```

## Key Features

✅ **Non-Blocking** - Tracking is instant, sending happens in background  
✅ **Tool Tracking** - Automatic tracking of all tool executions  
✅ **Error Handling** - Track failures without breaking the API  
✅ **LLM Flexibility** - Works with Claude, OpenAI, Google Gemini  
✅ **Performance Monitoring** - Track response times and durations  
✅ **Zero Latency** - In-memory tracking adds ~0ms to response time  

## Testing the API

### Start the Server

```bash
uvicorn main:app --reload
```

### Test Chat Endpoint

```bash
# Simple chat
curl -X POST "http://localhost:8000/chat" \
  -H "Content-Type: application/json" \
  -d '{"message": "Hello, how are you?"}'

# Chat with calculation
curl -X POST "http://localhost:8000/chat" \
  -H "Content-Type: application/json" \
  -d '{"message": "What is 127 multiplied by 8?"}'

# Weather query
curl -X POST "http://localhost:8000/chat" \
  -H "Content-Type: application/json" \
  -d '{"message": "What'\''s the weather in San Francisco?"}'

# With conversation ID
curl -X POST "http://localhost:8000/chat" \
  -H "Content-Type: application/json" \
  -d '{
    "message": "Hello!",
    "conversation_id": "web-chat-123",
    "customer_id": "user-456"
  }'
```

## Best Practices

### 1. Always Use Background Tasks

```python
# ✅ Good - non-blocking
background_tasks.add_task(send_tracking_data)

# ❌ Bad - blocks response
conversation_tracker.send_tracked_data()
```

### 2. Track All Tool Executions

```python
# ✅ Good - track every tool call
@tool
def my_tool(input: str) -> str:
    start_time = time.time()
    try:
        result = process(input)
        conversation_tracker.track_action(
            action_name="my_tool",
            duration_ms=int((time.time() - start_time) * 1000),
            response=result
        )
        return result
    except Exception as e:
        conversation_tracker.track_action(
            action_name="my_tool",
            error_msg=str(e)
        )
        raise
```

### 3. Add Rich Metadata

```python
# ✅ Good - comprehensive metadata
conversation_tracker.track_agent_message(
    answer=response,
    metadata={
        "model": "claude-3-5-sonnet-20241022",
        "response_time_ms": duration_ms,
        "tools_available": tool_names,
        "tools_used": used_tools,
        "message_length": len(response)
    }
)
```