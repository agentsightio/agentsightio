import pytest
from agentsight.exceptions import (
    InvalidQuestionDataException,
)


class TestConversationTrackerTrackQuestion:
    """Test cases for track_question method."""
    
    def test_track_question_valid_data(self, tracker):
        """Test tracking a valid question."""
        tracker.get_or_create_conversation("conv_123")
        tracker.track_question("What is 2+2?")
        
        # Check that data was stored
        assert "conv_123" in tracker._tracked_data
        assert len(tracker._tracked_data["conv_123"]["items"]) == 2
        
        item = tracker._tracked_data["conv_123"]["items"][1]
        assert item["type"] == "question"
        assert "timestamp" in item
        assert isinstance(item["timestamp"], str)
        assert len(item["timestamp"]) > 0
        assert item["data"]["content"] == "What is 2+2?"
        assert item["data"]["sender"] == "end_user"
        assert item["data"]["metadata"] == {}
    
    def test_track_question_invalid_data_raises_exception(self, tracker):
        """Test that invalid question data raises InvalidQuestionDataException."""
        tracker.get_or_create_conversation("conv_123")
        with pytest.raises(InvalidQuestionDataException):
            tracker.track_question("")
        
        with pytest.raises(InvalidQuestionDataException):
            tracker.track_question("   ")
    
    def test_track_question_with_metadata(self, tracker):
        """Test tracking question with metadata."""
        metadata = {"source": "test", "priority": "high"}
        
        tracker.get_or_create_conversation("conv_123")
        tracker.track_question("Test question", metadata)
        
        item = tracker._tracked_data["conv_123"]["items"][1]
        assert item["data"]["metadata"] == metadata
    
    def test_track_question_with_none_metadata(self, tracker):
        """Test tracking question with None metadata."""
        tracker.get_or_create_conversation("conv_123")
        tracker.track_question("Test question", None)
        
        item = tracker._tracked_data["conv_123"]["items"][1]
        assert item["data"]["metadata"] == {}
    
    def test_track_question_with_empty_metadata(self, tracker):
        """Test tracking question with empty metadata."""
        tracker.get_or_create_conversation("conv_123")
        tracker.track_question("Test question", {})
        
        item = tracker._tracked_data["conv_123"]["items"][1]
        assert item["data"]["metadata"] == {}
    
    def test_track_multiple_questions_preserves_order(self, tracker):
        """Test that multiple questions are stored in order."""
        questions = ["First question", "Second question", "Third question"]

        tracker.get_or_create_conversation("conv_123")

        for question in questions:
            tracker.track_question(question)
        
        # Check that all questions were stored (1 conv + 3 questions)
        assert len(tracker._tracked_data["conv_123"]["items"]) == 4
        
        # Check that order is preserved
        for i, question in enumerate(questions):
            item = tracker._tracked_data["conv_123"]["items"][i+1]
            assert item["data"]["content"] == question
            assert item["type"] == "question"
    
    def test_track_question_timestamp_progression(self, tracker):
        """Test that timestamps progress correctly for sequential questions."""
        import time
        
        tracker.get_or_create_conversation("conv_123")
        tracker.track_question("First question")
        time.sleep(0.01)  # Small delay to ensure different timestamps
        tracker.track_question("Second question")
        
        items = tracker._tracked_data["conv_123"]["items"]
        assert len(items) == 3
        
        # Check that timestamps are different
        timestamp1 = items[0]["timestamp"]
        timestamp2 = items[1]["timestamp"]
        assert timestamp1 != timestamp2
        
        # Check that both timestamps are valid strings
        assert isinstance(timestamp1, str)
        assert isinstance(timestamp2, str)
        assert len(timestamp1) > 0
        assert len(timestamp2) > 0
    
    def test_track_question_with_special_characters(self, tracker):
        """Test tracking questions with special characters."""
        special_questions = [
            "What's the meaning of life?",
            "How do you say 'hello' in 中文?",
            "What about émojis? 😀🎉",
            "Math: 2+2=4, right?",
            "Newline\nQuestion",
            "Tab\tQuestion"
        ]
        
        tracker.get_or_create_conversation("conv_123")
        for i, question in enumerate(special_questions):
            tracker.track_question(question)
        
        # Check that all special characters are preserved
        for i, question in enumerate(special_questions):
            conv_id = f"conv_123"
            item = tracker._tracked_data[conv_id]["items"][i+1]
            assert item["data"]["content"] == question
    
    def test_track_question_validates_empty_content(self, tracker):
        """Test that empty content validation works correctly."""
        invalid_questions = ["", "   ", "\t", "\n", "\r\n"]
        
        tracker.get_or_create_conversation("conv_123")
        for question in invalid_questions:
            with pytest.raises(InvalidQuestionDataException):
                tracker.track_question(question)
