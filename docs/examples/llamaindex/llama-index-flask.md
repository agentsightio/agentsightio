---
outline: deep
---

# Flask Integration with Background Tasks

AgentSight's in-memory architecture is perfect for Flask applications. Track conversations instantly during request processing, then send data in background tasks using Celery to avoid impacting response times.

## Prerequisites

:::tabs
== pip
```bash
pip install agentsight flask celery redis python-dotenv llama-index llama-index-llms-openai
```
== poetry
```bash
poetry add agentsight flask celery redis python-dotenv llama-index llama-index-llms-openai
```
== uv
```bash
uv add agentsight flask celery redis python-dotenv llama-index llama-index-llms-openai
```
:::

## Environment Setup

```bash
# .env
AGENTSIGHT_API_KEY=your_agentsight_api_key
OPENAI_API_KEY=your_openai_api_key
AGENTSIGHT_TOKEN_HANDLER_TYPE=llamaindex
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=redis://localhost:6379/0
```

## Basic Flask Integration

```python
from flask import Flask, request, jsonify
from agentsight import ConversationTracker
from agentsight.helpers import generate_conversation_id
from llama_index.llms.openai import OpenAI
from llama_index.core.agent.workflow import FunctionAgent
from celery import Celery
import time
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

# Celery configuration
app.config['CELERY_BROKER_URL'] = 'redis://localhost:6379/0'
app.config['CELERY_RESULT_BACKEND'] = 'redis://localhost:6379/0'

# Initialize Celery
celery = Celery(app.name, broker=app.config['CELERY_BROKER_URL'])
celery.conf.update(app.config)

# Initialize tracker once at startup
tracker = ConversationTracker()

# Initialize your AI agent
llm = OpenAI(model="gpt-3.5-turbo")
agent = FunctionAgent(tools=[], llm=llm)

@celery.task
def send_tracking_data():
    """Background task to send tracking data"""
    try:
        result = tracker.send_tracked_data()
        print(f"✅ Sent tracking data: {result}")
        return result
    except Exception as e:
        print(f"❌ Failed to send tracking data: {e}")
        return {"error": str(e)}

@app.route('/chat', methods=['POST'])
def chat_endpoint():
    """Chat endpoint with instant tracking and background sending"""
    
    data = request.get_json()
    if not data or 'message' not in data:
        return jsonify({"error": "Message is required"}), 400
    
    message = data['message']
    # Generate conversation ID if not provided
    conversation_id = data.get('conversation_id') or generate_conversation_id()
    customer_id = data.get('customer_id')
    
    # Initialize conversation with context
    tracker.get_or_create_conversation(
        conversation_id=conversation_id,
        customer_id=customer_id
    )
    
    # Track question instantly (no performance impact)
    tracker.track_question(message)
    
    # Process with AI agent (full performance available)
    response = agent.run(message)
    
    # Track response instantly
    tracker.track_answer(str(response))
    
    # Schedule background task to send data (non-blocking)
    send_tracking_data.delay()
    
    return jsonify({
        "response": str(response)
    })

if __name__ == '__main__':
    app.run(debug=True)
```

## Advanced Integration with Tool Tracking

```python
from flask import Flask, request, jsonify
from agentsight import ConversationTracker
from agentsight.helpers import generate_conversation_id
from llama_index.llms.openai import OpenAI
from llama_index.core.agent.workflow import FunctionAgent
from llama_index.core.tools.tool_spec.base import BaseToolSpec
from celery import Celery
import time
from typing import Optional
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

# Celery configuration
app.config['CELERY_BROKER_URL'] = 'redis://localhost:6379/0'
app.config['CELERY_RESULT_BACKEND'] = 'redis://localhost:6379/0'

# Initialize Celery
celery = Celery(app.name, broker=app.config['CELERY_BROKER_URL'])
celery.conf.update(app.config)

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

@celery.task
def send_tracking_data():
    """Background task to send tracking data"""
    try:
        result = tracker.send_tracked_data()
        print(f"✅ Sent tracking data: {result}")
        return result
    except Exception as e:
        print(f"❌ Failed to send tracking data: {e}")
        return {"error": str(e)}

@app.route('/chat', methods=['POST'])
def chat_endpoint():
    """Advanced chat endpoint with comprehensive tracking"""
    
    data = request.get_json()
    if not data or 'message' not in data:
        return jsonify({"error": "Message is required"}), 400
    
    message = data['message']
    # Generate conversation ID if not provided
    conversation_id = data.get('conversation_id') or generate_conversation_id()
    
    # Initialize conversation with context
    tracker.get_or_create_conversation(
        conversation_id=conversation_id
    )
    
    # Track question
    tracker.track_question(message)
    
    try:
        # Process with AI agent
        start_time = time.time()
        response = agent.run(message)
        duration_ms = int((time.time() - start_time) * 1000)
        
        # Track successful response
        tracker.track_answer(str(response))
        
        # Schedule background sending
        send_tracking_data.delay()
        
        return jsonify({
            "response": str(response)
        })
        
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
        send_tracking_data.delay()
        
        return jsonify({"error": f"Chat error: {str(e)}"}), 500

if __name__ == '__main__':
    app.run(debug=True)
```

## Key Integration Points

### 1. Conversation Initialization
- Always call `get_or_create_conversation()` with required `conversation_id`
- Include contextual information like `customer_id` when available
- Use request headers for additional context

### 2. Token Tracking
- With `AGENTSIGHT_TOKEN_HANDLER_TYPE=llamaindex`, tokens are automatically tracked

### 3. Background Processing
- Use Celery tasks to send tracking data without blocking responses
- Handle errors gracefully in background tasks

### 4. Error Handling
- Track errors as actions for debugging insights
- Always send tracking data, even for failed requests
- Use structured error metadata for better analysis

## Running the Example

### Start Redis (required for Celery)
```bash
redis-server
```

### Start Celery Worker
```bash
celery -A your_app_name worker --loglevel=info
```

### Start Flask Application
```bash
python app.py
```

### Test the Endpoint
```bash
curl -X POST "http://localhost:5000/chat" \
  -H "Content-Type: application/json" \
  -d '{
    "message": "Calculate 25 * 4 + 10",
    "customer_id": "user_123"
  }'
```
