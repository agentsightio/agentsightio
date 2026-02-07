import pytest
from unittest.mock import patch
from agentsight.client import ConversationTracker
from agentsight.exceptions import (
    InvalidAnswerDataException,
)

class TestConversationTrackerTrackAnswer:
    """Test cases for track_agent_message method."""
    
    @patch('agentsight.validators.validate_content_data')
    def test_track_agent_message_valid_data(self, mock_validate, tracker):
        """Test tracking a valid answer."""
        mock_validate.return_value = True
        
        tracker.get_or_create_conversation("conv_123")
        tracker.track_agent_message("The answer is 4", "conv_123")
        
        # Check that data was stored
        assert "conv_123" in tracker._tracked_data
        assert len(tracker._tracked_data["conv_123"]["items"]) == 2
        
        item = tracker._tracked_data["conv_123"]["items"][1]
        assert item["type"] == "answer"
        assert "timestamp" in item  # Just check it exists
        assert isinstance(item["timestamp"], str)  # And it's a string
        assert len(item["timestamp"]) > 0  # And it's not empty
        assert item["data"]["content"] == "The answer is 4"
        assert item["data"]["sender"] == "agent"

    @patch('agentsight.validators.validate_content_data')
    def test_track_agent_message_invalid_data_raises_exception(self, mock_validate, tracker):
        """Test that invalid answer data raises InvalidAnswerDataException."""
        mock_validate.return_value = False
        
        with pytest.raises(InvalidAnswerDataException):
            tracker.track_agent_message("")
