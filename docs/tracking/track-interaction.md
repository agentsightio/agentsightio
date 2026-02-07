---
outline: deep
---

# Track Interaction

The interaction tracking feature allows you to monitor whether users are actually engaging with your AI agents, not just visiting pages where they're available. This provides valuable insights into user behavior and engagement rates.

## Interaction vs Conversation Tracking

AgentSight distinguishes between two types of tracking:

- **Interaction Tracking**: Records when a user has the opportunity to use your AI agent (e.g., visits a page with a chat widget)
- **Conversation Tracking**: Records when a user actually engages with your AI agent (asks questions, gets responses)

This distinction helps you understand conversion rates and user engagement patterns.

## Two-Step Tracking Flow

### Step 1: Initialize Interaction
When a user first encounters your AI agent (e.g., loads a page with a chat widget), call `initialize_conversation()` to track the potential interaction.

### Step 2: Track Actual Usage
When the user actually interacts with your agent, use the regular tracking flow starting with `get_or_create_conversation()` using the same `conversation_id`.

## Method Signature

```python
def initialize_conversation(
    self,
    conversation_id: str,
    customer_id: Optional[str] = None,
    customer_ip_address: Optional[str] = None,
    device: Optional[str] = None,
    source: Optional[str] = None,
    language: Optional[str] = None,
    environment: Literal["production", "development"] = "production",
    metadata: Optional[Dict[str, Any]] = None
):
```

## Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `conversation_id` | `str` | Yes | Unique identifier for the potential conversation |
| `customer_id` | `str` | No | Unique identifier for the customer/user |
| `customer_ip_address` | `str` | No | IP address of the customer for geographical tracking |
| `device` | `str` | No | Device type or identifier (e.g., "mobile", "desktop", "tablet") |
| `source` | `str` | No | Source platform or channel (e.g., "web", "mobile_app") |
| `language` | `str` | No | Language code for the interaction (e.g., "en-US", "es-ES") |
| `environment` | `Literal["production", "development"]` | No | Specifies the environment in which the conversation is taking place. Defaults to `production`. |
| `metadata` | `Dict[str, Any]` | No | Additional contextual information |

## Web Widget Example

### Frontend Implementation

```javascript
// When user loads the page with chat widget
window.onload = function() {
    const conversationId = generateConversationId();
    
    // Track that user has potential to interact
    fetch('/api/track-interaction', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            conversation_id: conversationId,
            customer_id: getCurrentUserId(),
            page_url: window.location.href
        })
    });
    
    // Store conversation ID for later use
    localStorage.setItem('conversation_id', conversationId);
};

// When user actually opens/uses the chat widget
function onWidgetOpen() {
    const conversationId = localStorage.getItem('conversation_id');
    
    // Now start actual conversation tracking
    fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            conversation_id: conversationId,
            message: "Hello, I need help"
        })
    });
}
```

### Backend Implementation

```python
from fastapi import FastAPI, Request
from pydantic import BaseModel
from agentsight import ConversationTracker
from agentsight.helpers import generate_conversation_id
from typing import Optional

app = FastAPI()
tracker = ConversationTracker()

class InteractionRequest(BaseModel):
    conversation_id: str
    customer_id: Optional[str] = None
    page_url: Optional[str] = None

class ChatRequest(BaseModel):
    conversation_id: str
    message: str
    customer_id: Optional[str] = None

@app.post("/api/track-interaction")
async def track_interaction(request: InteractionRequest, http_request: Request):
    """Track potential interaction when user visits page"""
    
    # Get client information
    client_ip = http_request.client.host
    user_agent = http_request.headers.get("user-agent", "")
    
    # Initialize conversation (marks potential interaction)
    tracker.initialize_conversation(
        conversation_id=request.conversation_id,
        customer_id=request.customer_id,
        customer_ip_address=client_ip,
        device=get_device_type(user_agent),
        source="web",
        language="en-US",
        metadata={
            "page_url": request.page_url,
            "user_agent": user_agent,
            "widget_loaded": True
        }
    )
    
    return {"status": "interaction_tracked", "conversation_id": request.conversation_id}

@app.post("/api/chat")
async def chat(request: ChatRequest):
    """Handle actual chat interaction"""
    
    # This will update the existing conversation to mark it as used
    tracker.get_or_create_conversation(
        conversation_id=request.conversation_id,
        customer_id=request.customer_id
    )
    
    # Continue with regular tracking flow
    tracker.track_human_message(request.message)
    
    # Your AI agent logic here
    response = "This is a sample response"
    
    tracker.track_agent_message(response)
    
    # Send tracking data
    result = tracker.send_tracked_data()
    
    return {"response": response}

def get_device_type(user_agent: str) -> str:
    """Simple device detection"""
    if 'Mobile' in user_agent:
        return 'mobile'
    elif 'Tablet' in user_agent:
        return 'tablet'
    else:
        return 'desktop'
```

## Analytics Benefits

### Engagement Metrics
- **Interaction Rate**: `(actual_conversations / initialized_conversations) * 100`
- **Page Abandonment**: Users who loaded widget but never engaged
- **User Segmentation**: Which customer types engage most

### Optimization Insights
- **Widget Placement**: Which page locations drive more engagement
- **Timing Patterns**: When users are most likely to engage
- **Content Effectiveness**: Which pages lead to more AI interactions

## Important Notes

:::info When to Use Interaction Tracking
Interaction tracking is most valuable for **web widgets** and **optional AI features**. It's not typically needed for voice agents or mandatory AI interactions where usage is guaranteed.
:::

:::tip Best Practices
- Use the same `conversation_id` for both `initialize_conversation()` and `get_or_create_conversation()`
- Include relevant metadata to enable rich analytics
- Consider privacy implications when tracking user behavior
- Set up proper error handling for both tracking endpoints
:::

:::warning Not Suitable For
- Voice agents (users must interact to use)
- Command-line interfaces
- Mandatory AI interactions
- Simple API integrations without user choice
:::
