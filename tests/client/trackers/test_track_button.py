import pytest
from unittest.mock import patch
from agentsight.client import ConversationTracker
from agentsight.exceptions import (
    InvalidConversationDataException,
)

class TestConversationTrackerTrackButton:
    """Test cases for track_button method."""
    
    @patch('agentsight.helpers.get_iso_timestamp')
    def test_track_button_valid_data(self, mock_timestamp, tracker):
        """Test tracking a valid button click."""
        mock_timestamp.return_value = "2024-01-01T12:00:00.000Z"
        
        tracker.get_or_create_conversation("conv_123")
        tracker.track_button("submit", "Submit Form", "submit_action")
        
        item = tracker._tracked_data["conv_123"]["items"][1]
        assert item["type"] == "button"
        assert item["data"]["button_event"] == "submit"
        assert item["data"]["label"] == "Submit Form"
        assert item["data"]["value"] == "submit_action"
    
    def test_track_button_empty_fields_raise_exception(self, tracker):
        """Test that empty button fields raise InvalidConversationDataException."""
        tracker.get_or_create_conversation("conv_123")
        # Empty button_event
        with pytest.raises(InvalidConversationDataException):
            tracker.track_button("", "Label", "value")
        
        # Empty label
        with pytest.raises(InvalidConversationDataException):
            tracker.track_button("event", "", "value")
        
        # Empty value
        with pytest.raises(InvalidConversationDataException):
            tracker.track_button("event", "Label", "")
        
        # Whitespace only
        with pytest.raises(InvalidConversationDataException):
            tracker.track_button("   ", "Label", "value")
