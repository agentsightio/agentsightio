---
outline: deep
---

# FastAPI Integration with Google Gemini and Background Tasks

AgentSight's in-memory architecture is perfect for FastAPI applications using Google Gemini via LangChain. Track conversations instantly during request processing, then send data in background tasks to avoid impacting response times.

## Prerequisites

:::tabs
== pip
```bash
pip install agentsight fastapi uvicorn python-dotenv langchain langchain-google-genai langchain-community
```
== poetry
```bash
poetry add agentsight fastapi uvicorn python-dotenv langchain langchain-google-genai langchain-community
```
== uv
```bash
uv add agentsight fastapi uvicorn python-dotenv langchain langchain-google-genai langchain-community
```
:::

## Environment Setup

```bash
# .env
AGENTSIGHT_API_KEY=your_agentsight_api_key
GOOGLE_API_KEY=your_google_api_key
AGENTSIGHT_TOKEN_HANDLER_TYPE=langchain
```

## Basic FastAPI Integration

```python
from fastapi import FastAPI, BackgroundTasks
from pydantic import BaseModel
from agentsight import ConversationTracker
from agentsight.helpers import generate_conversation_id
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain.agents import AgentExecutor, create_tool_calling_agent
from langchain.prompts import ChatPromptTemplate
import time
from typing import Optional
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(title="AgentSight Gemini FastAPI Example")

# Initialize tracker once at startup
tracker = ConversationTracker()

# Initialize Google Gemini LLM
llm = ChatGoogleGenerativeAI(
    model="gemini-2.0-flash",
    temperature=0,
    google_api_key=None  # Will use GOOGLE_API_KEY env var
)

# Create a simple agent prompt
prompt = ChatPromptTemplate.from_messages([
    ("system", "You are a helpful assistant. Answer questions clearly and concisely."),
    ("human", "{input}"),
    ("placeholder", "{agent_scratchpad}"),
])

# Create agent with empty tools for basic example
agent = create_tool_calling_agent(llm, [], prompt)
agent_executor = AgentExecutor(agent=agent, tools=[])

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
        customer_id=request.customer_id
    )
    
    # Track question instantly (no performance impact)
    tracker.track_question(request.message)
    
    # Process with Gemini agent (full performance available)
    response = agent_executor.invoke({"input": request.message})
    
    # Track response instantly
    tracker.track_answer(response["output"])
    
    # Schedule background task to send data (non-blocking)
    background_tasks.add_task(send_tracking_data)
    
    return ChatResponse(
        response=response["output"]
    )
```

## Advanced Integration with Tool Tracking

```python
from fastapi import FastAPI, BackgroundTasks, HTTPException
from pydantic import BaseModel
from agentsight import ConversationTracker
from agentsight.helpers import generate_conversation_id
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain.agents import AgentExecutor, create_tool_calling_agent
from langchain.prompts import ChatPromptTemplate
from langchain.tools import tool
from langchain_community.tools import DuckDuckGoSearchRun
import time
import requests
from typing import Optional
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(title="Advanced AgentSight Gemini FastAPI Example")

# Global tracker instance
tracker = ConversationTracker()

# Custom calculator tool with tracking
@tool
def calculate(expression: str) -> str:
    """Basic calculator for simple mathematical expressions like 2+2, 10*5, etc."""
    start_time = time.time()
    
    try:
        # Safely evaluate simple expressions
        # Replace common math operators
        safe_expression = expression.replace("^", "**").replace("÷", "/")
        result = eval(safe_expression)
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
        
        return f"The result is: {result}"
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
        return f"Error calculating '{expression}': {str(e)}"

# Create Google Gemini agent with tools
llm = ChatGoogleGenerativeAI(
    model="gemini-2.0-flash",
    temperature=0
)

prompt = ChatPromptTemplate.from_messages([
    ("system", """You are a helpful assistant with access to various tools. You can:
    - Calculate mathematical expressions
    - Get current weather for any city
    - Search the web for current information
    
    Use the appropriate tool for each task and provide clear, helpful responses."""),
    ("human", "{input}"),
    ("placeholder", "{agent_scratchpad}"),
])

tools = [calculate, get_weather, search_web]
agent = create_tool_calling_agent(llm, tools, prompt)
agent_executor = AgentExecutor(agent=agent, tools=tools, verbose=True)

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
    """Advanced chat endpoint with comprehensive tracking"""
    
    # Generate conversation ID
    conversation_id = request.conversation_id or generate_conversation_id()
    
    # Initialize conversation with context
    tracker.get_or_create_conversation(
        conversation_id=conversation_id,
        customer_id=request.customer_id
    )
    
    # Track question
    tracker.track_question(request.message)
    
    try:
        # Process with Gemini agent
        start_time = time.time()
        response = agent_executor.invoke({"input": request.message})
        duration_ms = int((time.time() - start_time) * 1000)
        
        # Track successful response
        tracker.track_answer(response["output"])
        
        # Schedule background sending
        background_tasks.add_task(send_tracking_data)
        
        return ChatResponse(
            response=response["output"]
        )
        
    except Exception as e:
        # Track error
        duration_ms = int((time.time() - start_time) * 1000)
        tracker.track_action(
            action_name="chat_error",
            duration_ms=duration_ms,
            error_msg=str(e),
            metadata={
                "customer_id": request.customer_id,
                "error_type": type(e).__name__,
                "model": "gemini-2.0-flash"
            }
        )
        
        # Still send tracking data for errors
        background_tasks.add_task(send_tracking_data)
        
        raise HTTPException(status_code=500, detail=f"Chat error: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
```
