from typing import Dict, Any
from agentsight.exceptions import (
    MissingConversationIdException
)

def validate_conversation_id(data: Dict[str, Any]) -> None:
    """Validate conversation_id is present and raise specific exception if not."""
    if not bool(str(data.get("conversation_id", "") or "").strip()):
        raise MissingConversationIdException()

def validate_conversation_data(data: Dict[str, Any]) -> bool:
    """Validate conversation data structure with specific error messages."""
    # Check specific required fields first
    validate_conversation_id(data)
    
    # Then check that at least question or answer is present
    has_content = bool(
        (str(data.get("question", "") or "").strip() and
        str(data.get("answer", "") or "").strip()) or
        str(data.get("content", "") or "").strip()
    )
    
    return has_content

def validate_question_and_answer_data(data: Dict[str, Any]) -> bool:
    """Validate question and answer data structure."""
    return bool(
        str(data.get("question", "") or "").strip() and
        str(data.get("answer", "") or "").strip()
    )

def validate_content_data(data: Dict[str, Any]) -> bool:
    """Validate if content is in data."""
    return bool(str(data.get("content", "") or "").strip())
    
def validate_action_data(data: Dict[str, Any]) -> bool:
    """Validate action data structure."""
    # Check specific required fields first
    validate_conversation_id(data)
    
    # Check that action_name is present
    return bool(str(data.get("action_name", "") or "").strip())

def validate_button_data(data: Dict[str, Any]) -> bool:
    """Validate button data structure."""
    # Check specific required fields first
    validate_conversation_id(data)
    
    # Check that all required button fields are present
    return bool(
        str(data.get("button_event", "") or "").strip() and
        str(data.get("label", "") or "").strip() and
        str(data.get("value", "") or "").strip()
    )
