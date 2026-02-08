---
outline: deep
---

<CopyMarkdownButton />

# FastAPI Integration with LlamaIndex

AgentSight's in-memory architecture is perfect for FastAPI applications. Track conversations instantly during request processing, then send data in background tasks to avoid impacting response times.

## Prerequisites

:::tabs
== pip
```bash
pip install agentsight fastapi uvicorn python-dotenv llama-index llama-index-llms-openai
```
== poetry
```bash
poetry add agentsight fastapi uvicorn python-dotenv llama-index llama-index-llms-openai
```
== uv
```bash
uv add agentsight fastapi uvicorn python-dotenv llama-index llama-index-llms-openai
```
:::

## Environment Setup

```bash
# .env
AGENTSIGHT_API_KEY=your_agentsight_api_key
OPENAI_API_KEY=your_openai_api_key
AGENTSIGHT_TOKEN_HANDLER_TYPE=llamaindex
```

## Basic FastAPI Integration

```python
from fastapi import FastAPI, BackgroundTasks
from pydantic import BaseModel
from agentsight import conversation_tracker
from agentsight.helpers import generate_conversation_id
from llama_index.llms.openai import OpenAI
from llama_index.core.llms import ChatMessage
from typing import Optional
from dotenv import load_dotenv
import time

load_dotenv()

app = FastAPI(title="AgentSight FastAPI Example")

# Initialize LLM
llm = OpenAI(model="gpt-3.5-turbo")

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
        name="FastAPI Chat"
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
    messages = [ChatMessage(role="user", content=request.message)]
    response = llm.chat(messages)
    duration_ms = int((time.time() - start_time) * 1000)
    
    # Track agent response
    conversation_tracker.track_agent_message(
        answer=str(response.message.content),
        metadata={
            "model": "gpt-3.5-turbo",
            "response_time_ms": duration_ms
        }
    )
    
    # Schedule background task to send data (non-blocking)
    background_tasks.add_task(send_tracking_data)
    
    return ChatResponse(
        response=str(response.message.content),
        conversation_id=conversation_id
    )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
```

## Advanced Integration with Tool Tracking

```python
from fastapi import FastAPI, BackgroundTasks, HTTPException
from pydantic import BaseModel
from agentsight import conversation_tracker
from agentsight.helpers import generate_conversation_id
from llama_index.llms.openai import OpenAI
from llama_index.core.tools import FunctionTool
from llama_index.core.agent import ReActAgent
from typing import Optional
from dotenv import load_dotenv
import time

load_dotenv()

app = FastAPI(title="Advanced AgentSight FastAPI Example")

# Calculator tool with tracking
def calculate(expression: str) -> str:
    """
    Basic calculator for simple expressions.
    
    Args:
        expression: Mathematical expression to evaluate (e.g., "2 + 2")
    """
    start_time = time.time()
    
    try:
        # Safely evaluate simple expressions
        result = eval(expression.replace("^", "**"))
        end_time = time.time()
        duration_ms = int((end_time - start_time) * 1000)
        
        # Track successful tool usage
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
        
        return str(result)
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

# Create calculator tool
calculator_tool = FunctionTool.from_defaults(fn=calculate)

# Create agent with tools
llm = OpenAI(model="gpt-3.5-turbo")
agent = ReActAgent.from_tools([calculator_tool], llm=llm, verbose=False)

class ChatRequest(BaseModel):
    message: str
    conversation_id: Optional[str] = None
    customer_id: Optional[str] = None

class ChatResponse(BaseModel):
    response: str
    conversation_id: str
    tools_used: bool

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
    """Advanced chat endpoint with comprehensive tracking"""
    
    # Generate conversation ID
    conversation_id = request.conversation_id or generate_conversation_id()
    
    # Initialize conversation
    conversation_tracker.get_or_create_conversation(
        conversation_id=conversation_id,
        customer_id=request.customer_id,
        source="api",
        device="desktop",
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
        # Process with AI agent
        start_time = time.time()
        response = agent.chat(request.message)
        duration_ms = int((time.time() - start_time) * 1000)
        
        # Check if tools were used (simple heuristic)
        tools_used = "calculate" in request.message.lower()
        
        # Track agent response
        conversation_tracker.track_agent_message(
            answer=str(response),
            metadata={
                "model": "gpt-3.5-turbo",
                "response_time_ms": duration_ms,
                "tools_available": ["calculator"],
                "tools_used": tools_used
            }
        )
        
        # Schedule background sending
        background_tasks.add_task(send_tracking_data)
        
        return ChatResponse(
            response=str(response),
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
        
        # Still send tracking data for errors
        background_tasks.add_task(send_tracking_data)
        
        raise HTTPException(status_code=500, detail=f"Chat error: {str(e)}")

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "service": "agentsight-fastapi"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
```

## Key Features

✅ **Non-Blocking** - Tracking happens instantly, sending in background  
✅ **Tool Tracking** - Automatic tracking of calculator and custom tools  
✅ **Error Handling** - Track failures without breaking the API  
✅ **Token Tracking** - Automatic LlamaIndex token counting  
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

### 2. Track All Errors

```python
# ✅ Good - comprehensive error tracking
try:
    response = agent.chat(message)
except Exception as e:
    conversation_tracker.track_action(
        action_name="error",
        error_msg=str(e)
    )
    raise
```

### 3. Add Request Context

```python
# ✅ Good - rich metadata
conversation_tracker.track_human_message(
    question=message,
    metadata={
        "endpoint": request.url.path,
        "method": request.method,
        "user_agent": request.headers.get("user-agent")
    }
)
```