"""Conversation tracking utilities for AgentSight."""

import uuid
from datetime import datetime, timezone
from typing import Dict, Any, Optional

def generate_conversation_id() -> str:
    """Generate a unique conversation ID."""
    return f"conv_{uuid.uuid4().hex[:12]}"

def format_conversation_metadata(metadata: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Format and validate conversation metadata."""
    if not metadata or not isinstance(metadata, dict):
        return {}
    
    formatted = {}
    for key, value in metadata.items():
        # Ensure keys are strings
        key_str = str(key)
        
        # Handle different value types
        if isinstance(value, (dict, list)):
            formatted[key_str] = str(value)
        elif value is None:
            formatted[key_str] = ""
        else:
            formatted[key_str] = value
    
    return formatted

def get_iso_timestamp() -> str:
    """Get current timestamp in ISO format."""
    return datetime.now(timezone.utc).isoformat()
