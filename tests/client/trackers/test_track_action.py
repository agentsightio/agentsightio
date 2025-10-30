import pytest
from unittest.mock import patch
from agentsight.client import ConversationTracker
from agentsight.exceptions import (
    InvalidConversationDataException,
)

class TestConversationTrackerTrackAction:
    """Test cases for track_action method."""
    
    @patch('agentsight.helpers.get_iso_timestamp')
    def test_track_action_valid_data(self, mock_timestamp, tracker):
        """Test tracking a valid action."""
        mock_timestamp.return_value = "2024-01-01T12:00:00.000Z"

        tracker.get_or_create_conversation("conv_123")
        tracker.track_action(
            "calculate",
            started_at="2024-01-01T11:59:00.000Z",
            ended_at="2024-01-01T12:00:00.000Z",
            duration_ms=1000,
            tools_used={"calculator": "basic"},
            response="4"
        )

        item = tracker._tracked_data["conv_123"]["items"][1]
        assert item["type"] == "action"
        assert item["data"]["action_name"] == "calculate"
        assert item["data"]["started_at"] == "2024-01-01T11:59:00.000Z"
        assert item["data"]["ended_at"] == "2024-01-01T12:00:00.000Z"
        assert item["data"]["duration_ms"] == 1000
        assert item["data"]["tools_used"] == {"calculator": "basic"}
        assert item["data"]["response"] == "4"
    
    def test_track_action_empty_name_raises_exception(self, tracker):
        """Test that empty action name raises InvalidConversationDataException."""
        with pytest.raises(InvalidConversationDataException):
            tracker.track_action("", "conv_123")
        
        with pytest.raises(InvalidConversationDataException):
            tracker.track_action("   ", "conv_123")
        
        with pytest.raises(InvalidConversationDataException):
            tracker.track_action(None, "conv_123")
    
    @patch('agentsight.helpers.get_iso_timestamp')
    def test_track_action_minimal_data(self, mock_timestamp, tracker):
        """Test tracking action with minimal required data."""
        mock_timestamp.return_value = "2024-01-01T12:00:00.000Z"
        
        tracker.get_or_create_conversation("conv_123")
        tracker.track_action("test_action")
        
        item = tracker._tracked_data["conv_123"]["items"][1]
        assert item["data"]["action_name"] == "test_action"
        assert item["data"]["metadata"] == {}
        
        # Optional fields should not be present
        assert "started_at" not in item["data"]
        assert "ended_at" not in item["data"]
        assert "duration_ms" not in item["data"]
