import pytest
import base64
from io import BytesIO
from agentsight.exceptions import (
    InvalidQuestionDataException,
)
from agentsight.enums import AttachmentMode


class TestConversationTrackerTrackQuestion:
    """Test cases for track_human_message method."""
    
    def test_track_human_message_valid_data(self, tracker):
        """Test tracking a valid question."""
        tracker.get_or_create_conversation("conv_123")
        tracker.track_human_message("What is 2+2?")
        
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
    
    def test_track_human_message_invalid_data_raises_exception(self, tracker):
        """Test that invalid question data raises InvalidQuestionDataException."""
        tracker.get_or_create_conversation("conv_123")
        with pytest.raises(InvalidQuestionDataException):
            tracker.track_human_message("")
        
        with pytest.raises(InvalidQuestionDataException):
            tracker.track_human_message("   ")
    
    def test_track_human_message_with_metadata(self, tracker):
        """Test tracking question with metadata."""
        metadata = {"source": "test", "priority": "high"}
        
        tracker.get_or_create_conversation("conv_123")
        tracker.track_human_message("Test question", metadata=metadata)
        
        item = tracker._tracked_data["conv_123"]["items"][1]
        assert item["data"]["metadata"] == metadata
    
    def test_track_human_message_with_none_metadata(self, tracker):
        """Test tracking question with None metadata."""
        tracker.get_or_create_conversation("conv_123")
        tracker.track_human_message("Test question", metadata=None)
        
        item = tracker._tracked_data["conv_123"]["items"][1]
        assert item["data"]["metadata"] == {}
    
    def test_track_human_message_with_empty_metadata(self, tracker):
        """Test tracking question with empty metadata."""
        tracker.get_or_create_conversation("conv_123")
        tracker.track_human_message("Test question", metadata={})
        
        item = tracker._tracked_data["conv_123"]["items"][1]
        assert item["data"]["metadata"] == {}
    
    def test_track_multiple_questions_preserves_order(self, tracker):
        """Test that multiple questions are stored in order."""
        questions = ["First question", "Second question", "Third question"]

        tracker.get_or_create_conversation("conv_123")

        for question in questions:
            tracker.track_human_message(question)
        
        # Check that all questions were stored (1 conv + 3 questions)
        assert len(tracker._tracked_data["conv_123"]["items"]) == 4
        
        # Check that order is preserved
        for i, question in enumerate(questions):
            item = tracker._tracked_data["conv_123"]["items"][i+1]
            assert item["data"]["content"] == question
            assert item["type"] == "question"
    
    def test_track_human_message_timestamp_progression(self, tracker):
        """Test that timestamps progress correctly for sequential questions."""
        import time
        
        tracker.get_or_create_conversation("conv_123")
        tracker.track_human_message("First question")
        time.sleep(0.01)  # Small delay to ensure different timestamps
        tracker.track_human_message("Second question")
        
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
    
    def test_track_human_message_with_special_characters(self, tracker):
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
            tracker.track_human_message(question)
        
        # Check that all special characters are preserved
        for i, question in enumerate(special_questions):
            conv_id = f"conv_123"
            item = tracker._tracked_data[conv_id]["items"][i+1]
            assert item["data"]["content"] == question
    
    def test_track_human_message_validates_empty_content(self, tracker):
        """Test that empty content validation works correctly."""
        invalid_questions = ["", "   ", "\t", "\n", "\r\n"]
        
        tracker.get_or_create_conversation("conv_123")
        for question in invalid_questions:
            with pytest.raises(InvalidQuestionDataException):
                tracker.track_human_message(question)

    def test_track_human_message_with_base64_attachments(self, tracker):
        """Test tracking a question with base64 attachments."""
        tracker.get_or_create_conversation("conv_123")
        
        # Use actual valid base64 data
        file_content = b"Document content here"
        base64_data = base64.b64encode(file_content).decode('utf-8')
        
        attachments = [
            {
                'filename': 'document.pdf',
                'data': base64_data,
                'mime_type': 'application/pdf'
            }
        ]
        
        tracker.track_human_message(
            message="Here is my document",
            attachments=attachments,
            attachment_mode='base64',
            metadata={"document_type": "verification"}
        )
        
        # Check that data was stored with attachments
        conv_id = tracker.config.conversation_id
        assert conv_id in tracker._tracked_data
        assert len(tracker._tracked_data[conv_id]["items"]) == 2
        
        item = tracker._tracked_data[conv_id]["items"][1]
        assert item["type"] == "question"
        assert item["data"]["content"] == "Here is my document"
        assert item["data"]["sender"] == "end_user"
        assert "attachments" in item["data"]
        assert len(item["data"]["attachments"]) == 1
        assert item["data"]["attachments"][0]["filename"] == "document.pdf"
        assert item["data"]["attachment_mode"] == AttachmentMode.BASE64.value

    def test_track_human_message_with_form_data_attachments(self, tracker):
        """Test tracking a question with form_data attachments."""
        tracker.get_or_create_conversation("conv_123")
        
        # Use BytesIO for form_data mode
        attachments = [
            {
                'data': BytesIO(b'ID document binary content'),
                'filename': 'upload.pdf'
            }
        ]
        
        tracker.track_human_message(
            message="I'm uploading my ID",
            attachments=attachments,
            attachment_mode='form_data',
            metadata={"contains_pii": True}
        )
        
        # Check that data was stored with attachments
        conv_id = tracker.config.conversation_id
        assert conv_id in tracker._tracked_data
        item = tracker._tracked_data[conv_id]["items"][1]
        assert item["type"] == "question"
        assert "attachments" in item["data"]
        assert item["data"]["attachment_mode"] == AttachmentMode.FORM_DATA.value

    def test_track_human_message_with_multiple_attachments(self, tracker):
        """Test tracking a question with multiple attachments."""
        tracker.get_or_create_conversation("conv_123")
        
        # Create multiple valid base64 attachments
        attachments = []
        file_names = ['id.pdf', 'proof.pdf', 'bank.pdf']
        for name in file_names:
            file_content = f"Content of {name}".encode()
            base64_data = base64.b64encode(file_content).decode('utf-8')
            attachments.append({
                'filename': name,
                'data': base64_data,
                'mime_type': 'application/pdf'
            })
        
        tracker.track_human_message(
            message="Here are all my verification documents",
            attachments=attachments,
            attachment_mode='base64'
        )
        
        # Check that all attachments were stored
        conv_id = tracker.config.conversation_id
        item = tracker._tracked_data[conv_id]["items"][1]
        assert len(item["data"]["attachments"]) == 3
        assert all(att["filename"] in ['id.pdf', 'proof.pdf', 'bank.pdf'] 
                  for att in item["data"]["attachments"])

    def test_track_human_message_without_attachments(self, tracker):
        """Test that tracking without attachments still works (backward compatibility)."""
        tracker.get_or_create_conversation("conv_123")
        tracker.track_human_message(
            message="Simple question without attachments",
            metadata={"simple": True}
        )
        
        # Check that message was stored without attachments
        conv_id = tracker.config.conversation_id
        item = tracker._tracked_data[conv_id]["items"][1]
        assert item["type"] == "question"
        assert "attachments" not in item["data"]
        assert "attachment_mode" not in item["data"]
        assert item["data"]["content"] == "Simple question without attachments"

    def test_track_human_message_invalid_attachment_mode_raises_exception(self, tracker):
        """Test that invalid attachment mode raises ValueError."""
        tracker.get_or_create_conversation("conv_123")
        
        attachments = [{'filename': 'test.pdf', 'data': 'data'}]
        
        with pytest.raises(ValueError, match="Invalid mode"):
            tracker.track_human_message(
                message="Test question",
                attachments=attachments,
                attachment_mode='invalid_mode'
            )

    def test_track_human_message_with_form_dash_data_mode(self, tracker):
        """Test that 'form-data' (with dash) is accepted as valid mode."""
        tracker.get_or_create_conversation("conv_123")
        
        attachments = [
            {
                'data': BytesIO(b'test content'),
                'filename': 'test.pdf'
            }
        ]
        
        # Should accept 'form-data' with dash
        tracker.track_human_message(
            message="Test with form-data",
            attachments=attachments,
            attachment_mode='form-data'  # Note: with dash
        )
        
        conv_id = tracker.config.conversation_id
        item = tracker._tracked_data[conv_id]["items"][1]
        # Should be normalized to FORM_DATA
        assert item["data"]["attachment_mode"] == AttachmentMode.FORM_DATA.value