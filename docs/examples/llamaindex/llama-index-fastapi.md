---
outline: deep
---

# FastAPI Integration with Background Tasks

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
from fastapi import FastAPI, BackgroundTasks, Request
from pydantic import BaseModel
from agentsight import ConversationTracker
from agentsight.helpers import generate_conversation_id
from llama_index.llms.openai import OpenAI
from llama_index.core.agent.workflow import FunctionAgent
import time
from typing import Optional
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(title="AgentSight FastAPI Example")

# Initialize tracker once at startup
tracker = ConversationTracker()

# Initialize your AI agent
llm = OpenAI(model="gpt-3.5-turbo")
agent = FunctionAgent(tools=[], llm=llm)

class ChatRequest(BaseModel):
    message: str
    conversation_id: Optional[str] = None
    customer_id: Optional[str] = None

class ChatResponse(BaseModel):
    response: str

async def send_tracking_data():
    """Background task to send tracking data"""
    try:
        result = tracker.send_tracked_data()
        print(f"✅ Sent tracking data: {result}")
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
    
    # Initialize conversation with context
    tracker.get_or_create_conversation(
        conversation_id=conversation_id,
        customer_id=customer_id
    )
    
    tracker.track_question(request.message)

    response = await agent.run(request.message)

    tracker.track_answer(str(response))
    
    # Schedule background task to send data (non-blocking)
    background_tasks.add_task(send_tracking_data)
    
    return ChatResponse(
        response=str(response)
    )
```

## Advanced Integration with Tool Tracking

```python
from fastapi import FastAPI, BackgroundTasks, HTTPException, Request
from pydantic import BaseModel
from agentsight import ConversationTracker
from agentsight.helpers import generate_conversation_id
from llama_index.llms.openai import OpenAI
from llama_index.core.agent.workflow import FunctionAgent
from llama_index.core.tools.tool_spec.base import BaseToolSpec
import time
import asyncio
from typing import Optional
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(title="Advanced AgentSight FastAPI Example")

# Global tracker instance
tracker = ConversationTracker()

class CalculatorSpec(BaseToolSpec):
    """Calculator tool with tracking"""
    spec_functions = ["calculate"]
    
    def calculate(self, expression: str):
        """Basic calculator for simple expressions"""
        start_time = time.time()
        
        try:
            # Safely evaluate simple expressions
            result = eval(expression.replace("^", "**"))
            end_time = time.time()
            duration_ms = int((end_time - start_time) * 1000)
            
            # Track tool usage
            tracker.track_action(
                action_name="calculate",
                duration_ms=duration_ms,
                response=str(result),
                metadata={
                    "expression": expression,
                    "tool_type": "calculator",
                    "result": result
                }
            )
            
            return result
        except Exception as e:
            end_time = time.time()
            duration_ms = int((end_time - start_time) * 1000)
            
            # Track failed calculation
            tracker.track_action(
                action_name="calculate",
                duration_ms=duration_ms,
                error_msg=str(e),
                metadata={
                    "expression": expression,
                    "tool_type": "calculator",
                    "status": "failed"
                }
            )
            return f"Error: {str(e)}"

# Create agent with tools
calculator_tools = CalculatorSpec().to_tool_list()
agent = FunctionAgent(
    tools=calculator_tools,
    llm=OpenAI(model="gpt-3.5-turbo"),
)

class ChatRequest(BaseModel):
    message: str
    conversation_id: Optional[str] = None

class ChatResponse(BaseModel):
    response: str

async def send_tracking_data():
    """Background task to send tracking data"""
    try:
        result = tracker.send_tracked_data()
        print(f"✅ Sent tracking data: {result}")
    except Exception as e:
        print(f"❌ Failed to send tracking data: {e}")

@app.post("/chat", response_model=ChatResponse)
async def chat_endpoint(
    request: ChatRequest, 
    background_tasks: BackgroundTasks,
):
    """Advanced chat endpoint with comprehensive tracking"""
    
    # Generate conversation ID
    conversation_id = request.conversation_id or generate_conversation_id()
    
    # Initialize conversation with full context
    tracker.get_or_create_conversation(
        conversation_id=conversation_id
    )
    
    # Track question
    tracker.track_question(request.message)
    
    try:
        # Process with AI agent
        start_time = time.time()
        response = await agent.run(request.message)
        duration_ms = int((time.time() - start_time) * 1000)
        
        # Track main agent response
        tracker.track_answer(str(response))
        
        # Schedule background sending
        background_tasks.add_task(send_tracking_data)
        
        return ChatResponse(
            response=str(response)
        )
        
    except Exception as e:
        # Track error
        duration_ms = int((time.time() - start_time) * 1000)
        tracker.track_action(
            action_name="chat_error",
            duration_ms=duration_ms,
            error_msg=str(e),
            metadata={
                "error_type": type(e).__name__
            }
        )
        
        # Still send tracking data for errors
        background_tasks.add_task(send_tracking_data)
        
        raise HTTPException(status_code=500, detail=f"Chat error: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
```