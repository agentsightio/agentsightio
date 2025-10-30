"""Tests for conversation data validators."""

import pytest
from unittest.mock import patch
from agentsight.validators import (
    validate_conversation_id,
    validate_conversation_data,
    validate_question_and_answer_data,
    validate_content_data,
    validate_action_data,
    validate_button_data
)
from agentsight.exceptions import (
    MissingConversationIdException,
)

class TestValidateConversationId:
    """Test cases for validate_conversation_id function."""
    
    def test_valid_conversation_id(self):
        """Test that valid conversation_id passes validation."""
        data = {"conversation_id": "conv_123"}
        # Should not raise any exception
        validate_conversation_id(data)
    
    def test_missing_conversation_key(self):
        """Test that missing conversation key raises exception."""
        data = {"other_key": "value"}
        with pytest.raises(MissingConversationIdException):
            validate_conversation_id(data)
    
    def test_empty_conversation_id(self):
        """Test that empty conversation_id raises exception."""
        data = {"conversation_id": ""}
        with pytest.raises(MissingConversationIdException):
            validate_conversation_id(data)
    
    def test_whitespace_conversation_id(self):
        """Test that whitespace-only conversation_id raises exception."""
        data = {"conversation_id": "   "}
        with pytest.raises(MissingConversationIdException):
            validate_conversation_id(data)
    
    def test_none_conversation_id(self):
        """Test that None conversation_id raises exception."""
        data = {"conversation_id": None}
        with pytest.raises(MissingConversationIdException):
            validate_conversation_id(data)
    
    def test_numeric_conversation_id(self):
        """Test that numeric conversation_id is valid."""
        data = {"conversation_id": 123}
        # Should not raise any exception
        validate_conversation_id(data)
    
    def test_zero_conversation_id(self):
        """Test that zero conversation_id raises exception."""
        data = {"conversation_id": 0}
        with pytest.raises(MissingConversationIdException):
            validate_conversation_id(data)


class TestValidateConversationData:
    """Test cases for validate_conversation_data function."""
    
    def test_valid_question_and_answer(self):
        """Test valid data with both question and answer."""
        data = {
            "conversation_id": "conv_123",
            "question": "What is 2+2?",
            "answer": "4"
        }
        assert validate_conversation_data(data) is True
    
    def test_valid_content_only(self):
        """Test valid data with content only."""
        data = {
            "conversation_id": "conv_123",
            "content": "Hello world"
        }
        assert validate_conversation_data(data) is True
    
    def test_missing_conversation_id(self):
        """Test that missing conversation_id raises exception."""
        data = {
            "question": "What is 2+2?",
            "answer": "4"
        }
        with pytest.raises(MissingConversationIdException):
            validate_conversation_data(data)
    
    def test_missing_content_and_qa(self):
        """Test that missing content and question/answer returns False."""
        data = {"conversation_id": "conv_123"}
        assert validate_conversation_data(data) is False
    
    def test_empty_content_and_qa(self):
        """Test that empty content and question/answer returns False."""
        data = {
            "conversation_id": "conv_123",
            "content": "",
            "question": "",
            "answer": ""
        }
        assert validate_conversation_data(data) is False
    
    def test_whitespace_content_and_qa(self):
        """Test that whitespace-only content and question/answer returns False."""
        data = {
            "conversation_id": "conv_123",
            "content": "   ",
            "question": "   ",
            "answer": "   "
        }
        assert validate_conversation_data(data) is False
    
    def test_partial_qa_data(self):
        """Test that partial question/answer data returns False."""
        data = {
            "conversation_id": "conv_123",
            "question": "What is 2+2?",
            "answer": ""
        }
        assert validate_conversation_data(data) is False
    
    def test_none_values(self):
        """Test that None values are handled correctly."""
        data = {
            "conversation_id": "conv_123",
            "content": None,
            "question": None,
            "answer": None
        }
        assert validate_conversation_data(data) is False


class TestValidateQuestionAndAnswerData:
    """Test cases for validate_question_and_answer_data function."""
    
    def test_valid_question_and_answer(self):
        """Test valid question and answer data."""
        data = {
            "question": "What is 2+2?",
            "answer": "4"
        }
        assert validate_question_and_answer_data(data) is True
    
    def test_missing_question(self):
        """Test missing question returns False."""
        data = {"answer": "4"}
        assert validate_question_and_answer_data(data) is False
    
    def test_missing_answer(self):
        """Test missing answer returns False."""
        data = {"question": "What is 2+2?"}
        assert validate_question_and_answer_data(data) is False
    
    def test_empty_question(self):
        """Test empty question returns False."""
        data = {
            "question": "",
            "answer": "4"
        }
        assert validate_question_and_answer_data(data) is False
    
    def test_empty_answer(self):
        """Test empty answer returns False."""
        data = {
            "question": "What is 2+2?",
            "answer": ""
        }
        assert validate_question_and_answer_data(data) is False
    
    def test_whitespace_question(self):
        """Test whitespace-only question returns False."""
        data = {
            "question": "   ",
            "answer": "4"
        }
        assert validate_question_and_answer_data(data) is False
    
    def test_whitespace_answer(self):
        """Test whitespace-only answer returns False."""
        data = {
            "question": "What is 2+2?",
            "answer": "   "
        }
        assert validate_question_and_answer_data(data) is False
    
    def test_none_question(self):
        """Test None question returns False."""
        data = {
            "question": None,
            "answer": "4"
        }
        assert validate_question_and_answer_data(data) is False
    
    def test_none_answer(self):
        """Test None answer returns False."""
        data = {
            "question": "What is 2+2?",
            "answer": None
        }
        assert validate_question_and_answer_data(data) is False


class TestValidateContentData:
    """Test cases for validate_content_data function."""
    
    def test_valid_content(self):
        """Test valid content data."""
        data = {"content": "Hello world"}
        assert validate_content_data(data) is True
    
    def test_missing_content(self):
        """Test missing content returns False."""
        data = {"other_key": "value"}
        assert validate_content_data(data) is False
    
    def test_empty_content(self):
        """Test empty content returns False."""
        data = {"content": ""}
        assert validate_content_data(data) is False
    
    def test_whitespace_content(self):
        """Test whitespace-only content returns False."""
        data = {"content": "   "}
        assert validate_content_data(data) is False
    
    def test_none_content(self):
        """Test None content returns False."""
        data = {"content": None}
        assert validate_content_data(data) is False
    
    def test_numeric_content(self):
        """Test numeric content is valid."""
        data = {"content": 123}
        assert validate_content_data(data) is True
    
    def test_zero_content(self):
        """Test zero content returns False."""
        data = {"content": 0}
        assert validate_content_data(data) is False


class TestValidateActionData:
    """Test cases for validate_action_data function."""
    
    def test_valid_action_data(self):
        """Test valid action data."""
        data = {
            "conversation_id": "conv_123",
            "action_name": "calculate"
        }
        assert validate_action_data(data) is True
    
    def test_missing_conversation_id(self):
        """Test that missing conversation_id raises exception."""
        data = {"action_name": "calculate"}
        with pytest.raises(MissingConversationIdException):
            validate_action_data(data)
    
    def test_missing_action_name(self):
        """Test missing action_name returns False."""
        data = {"conversation_id": "conv_123"}
        assert validate_action_data(data) is False
    
    def test_empty_action_name(self):
        """Test empty action_name returns False."""
        data = {
            "conversation_id": "conv_123",
            "action_name": ""
        }
        assert validate_action_data(data) is False
    
    def test_whitespace_action_name(self):
        """Test whitespace-only action_name returns False."""
        data = {
            "conversation_id": "conv_123",
            "action_name": "   "
        }
        assert validate_action_data(data) is False
    
    def test_none_action_name(self):
        """Test None action_name returns False."""
        data = {
            "conversation_id": "conv_123",
            "action_name": None
        }
        assert validate_action_data(data) is False
    
    def test_numeric_action_name(self):
        """Test numeric action_name is valid."""
        data = {
            "conversation_id": "conv_123",
            "action_name": 123
        }
        assert validate_action_data(data) is True
    
    def test_zero_action_name(self):
        """Test zero action_name returns False."""
        data = {
            "conversation_id": "conv_123",
            "action_name": 0
        }
        assert validate_action_data(data) is False


class TestValidateButtonData:
    """Test cases for validate_button_data function."""
    
    def test_valid_button_data(self):
        """Test valid button data."""
        data = {
            "conversation_id": "conv_123",
            "button_event": "click",
            "label": "Submit",
            "value": "submit_form"
        }
        assert validate_button_data(data) is True
    
    def test_missing_conversation_id(self):
        """Test that missing conversation_id raises exception."""
        data = {
            "button_event": "click",
            "label": "Submit",
            "value": "submit_form"
        }
        with pytest.raises(MissingConversationIdException):
            validate_button_data(data)
    
    def test_missing_button_event(self):
        """Test missing button_event returns False."""
        data = {
            "conversation_id": "conv_123",
            "label": "Submit",
            "value": "submit_form"
        }
        assert validate_button_data(data) is False
    
    def test_missing_label(self):
        """Test missing label returns False."""
        data = {
            "conversation_id": "conv_123",
            "button_event": "click",
            "value": "submit_form"
        }
        assert validate_button_data(data) is False
    
    def test_missing_value(self):
        """Test missing value returns False."""
        data = {
            "conversation_id": "conv_123",
            "button_event": "click",
            "label": "Submit"
        }
        assert validate_button_data(data) is False
    
    def test_empty_button_event(self):
        """Test empty button_event returns False."""
        data = {
            "conversation_id": "conv_123",
            "button_event": "",
            "label": "Submit",
            "value": "submit_form"
        }
        assert validate_button_data(data) is False
    
    def test_empty_label(self):
        """Test empty label returns False."""
        data = {
            "conversation_id": "conv_123",
            "button_event": "click",
            "label": "",
            "value": "submit_form"
        }
        assert validate_button_data(data) is False
    
    def test_empty_value(self):
        """Test empty value returns False."""
        data = {
            "conversation_id": "conv_123",
            "button_event": "click",
            "label": "Submit",
            "value": ""
        }
        assert validate_button_data(data) is False
    
    def test_whitespace_button_event(self):
        """Test whitespace-only button_event returns False."""
        data = {
            "conversation_id": "conv_123",
            "button_event": "   ",
            "label": "Submit",
            "value": "submit_form"
        }
        assert validate_button_data(data) is False
    
    def test_whitespace_label(self):
        """Test whitespace-only label returns False."""
        data = {
            "conversation_id": "conv_123",
            "button_event": "click",
            "label": "   ",
            "value": "submit_form"
        }
        assert validate_button_data(data) is False
    
    def test_whitespace_value(self):
        """Test whitespace-only value returns False."""
        data = {
            "conversation_id": "conv_123",
            "button_event": "click",
            "label": "Submit",
            "value": "   "
        }
        assert validate_button_data(data) is False
    
    def test_none_button_event(self):
        """Test None button_event returns False."""
        data = {
            "conversation_id": "conv_123",
            "button_event": None,
            "label": "Submit",
            "value": "submit_form"
        }
        assert validate_button_data(data) is False
    
    def test_none_label(self):
        """Test None label returns False."""
        data = {
            "conversation_id": "conv_123",
            "button_event": "click",
            "label": None,
            "value": "submit_form"
        }
        assert validate_button_data(data) is False
    
    def test_none_value(self):
        """Test None value returns False."""
        data = {
            "conversation_id": "conv_123",
            "button_event": "click",
            "label": "Submit",
            "value": None
        }
        assert validate_button_data(data) is False
    
    def test_numeric_button_fields(self):
        """Test numeric button fields are valid."""
        data = {
            "conversation_id": "conv_123",
            "button_event": 123,
            "label": 456,
            "value": 789
        }
        assert validate_button_data(data) is True
    
    def test_zero_button_fields(self):
        """Test zero button fields return False."""
        data = {
            "conversation_id": "conv_123",
            "button_event": 0,
            "label": "Submit",
            "value": "submit_form"
        }
        assert validate_button_data(data) is False


class TestValidationIntegration:
    """Integration tests for validation functions."""
    
    def test_validate_conversation_data_raises_missing_conversation_id(self):
        """Test that validate_conversation_data raises MissingConversationIdException when conversation_id is missing."""
        data = {"content": "Hello"}
        
        with pytest.raises(MissingConversationIdException):
            validate_conversation_data(data)
    
    def test_validate_action_data_raises_missing_conversation_id(self):
        """Test that validate_action_data raises MissingConversationIdException when conversation_id is missing."""
        data = {"action_name": "test"}
        
        with pytest.raises(MissingConversationIdException):
            validate_action_data(data)
    
    def test_validate_button_data_raises_missing_conversation_id(self):
        """Test that validate_button_data raises MissingConversationIdException when conversation_id is missing."""
        data = {
            "button_event": "click",
            "label": "Submit",
            "value": "submit_form"
        }
        
        with pytest.raises(MissingConversationIdException):
            validate_button_data(data)
