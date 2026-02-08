import pytest
import base64
from io import BytesIO
from agentsight.exceptions import (
    InvalidAnswerDataException,
)
from agentsight.enums import AttachmentMode

class TestConversationTrackerTrackAnswer:
    """Test cases for track_agent_message method."""
    
    def test_track_agent_message_valid_data(self, tracker):
        """Test tracking a valid answer."""
        tracker.get_or_create_conversation("conv_123")
        tracker.track_agent_message("The answer is 4")
        
        # Check that data was stored
        assert tracker.config.conversation_id in tracker._tracked_data
        assert len(tracker._tracked_data[tracker.config.conversation_id]["items"]) == 2
        
        item = tracker._tracked_data[tracker.config.conversation_id]["items"][1]
        assert item["type"] == "answer"
        assert "timestamp" in item
        assert isinstance(item["timestamp"], str)
        assert len(item["timestamp"]) > 0
        assert item["data"]["content"] == "The answer is 4"
        assert item["data"]["sender"] == "agent"

    def test_track_agent_message_invalid_data_raises_exception(self, tracker):
        """Test that invalid answer data raises InvalidAnswerDataException."""
        tracker.get_or_create_conversation("conv_123")
        
        with pytest.raises(InvalidAnswerDataException):
            tracker.track_agent_message("")

    def test_track_agent_message_with_base64_attachments(self, tracker):
        """Test tracking an answer with base64 attachments."""
        tracker.get_or_create_conversation("conv_123")
        
        # Use actual valid base64 data
        file_content = b"This is test PDF content"
        base64_data = base64.b64encode(file_content).decode('utf-8')
        
        attachments = [
            {
                'filename': 'test.pdf',
                'data': base64_data,
                'mime_type': 'application/pdf'
            }
        ]
        
        tracker.track_agent_message(
            message="Here are the documents",
            attachments=attachments,
            attachment_mode='base64',
            metadata={"test": "metadata"}
        )
        
        # Check that data was stored with attachments
        conv_id = tracker.config.conversation_id
        assert conv_id in tracker._tracked_data
        assert len(tracker._tracked_data[conv_id]["items"]) == 2
        
        item = tracker._tracked_data[conv_id]["items"][1]
        assert item["type"] == "answer"
        assert item["data"]["content"] == "Here are the documents"
        assert item["data"]["sender"] == "agent"
        assert "attachments" in item["data"]
        assert len(item["data"]["attachments"]) == 1
        assert item["data"]["attachments"][0]["filename"] == "test.pdf"
        assert item["data"]["attachment_mode"] == AttachmentMode.BASE64.value

    def test_track_agent_message_with_form_data_attachments(self, tracker):
        """Test tracking an answer with form_data attachments."""
        tracker.get_or_create_conversation("conv_123")
        
        # Use BytesIO for form_data mode
        attachments = [
            {
                'data': BytesIO(b'PDF file content here'),
                'filename': 'document.pdf'
            }
        ]
        
        tracker.track_agent_message(
            message="Here is your document",
            attachments=attachments,
            attachment_mode='form_data',
            metadata={"document_type": "invoice"}
        )
        
        # Check that data was stored with attachments
        conv_id = tracker.config.conversation_id
        assert conv_id in tracker._tracked_data
        item = tracker._tracked_data[conv_id]["items"][1]
        assert item["type"] == "answer"
        assert "attachments" in item["data"]
        assert item["data"]["attachment_mode"] == AttachmentMode.FORM_DATA.value
        assert len(item["data"]["attachments"]) == 1

    def test_track_agent_message_with_multiple_attachments(self, tracker):
        """Test tracking an answer with multiple attachments."""
        tracker.get_or_create_conversation("conv_123")
        
        # Create multiple valid base64 attachments
        attachments = []
        for i in range(3):
            file_content = f"File {i+1} content".encode()
            base64_data = base64.b64encode(file_content).decode('utf-8')
            attachments.append({
                'filename': f'file{i+1}.pdf',
                'data': base64_data,
                'mime_type': 'application/pdf'
            })
        
        tracker.track_agent_message(
            message="Here are multiple documents",
            attachments=attachments,
            attachment_mode='base64'
        )
        
        # Check that all attachments were stored
        conv_id = tracker.config.conversation_id
        item = tracker._tracked_data[conv_id]["items"][1]
        assert len(item["data"]["attachments"]) == 3
        assert all(att["filename"] in ['file1.pdf', 'file2.pdf', 'file3.pdf'] 
                  for att in item["data"]["attachments"])

    def test_track_agent_message_without_attachments(self, tracker):
        """Test that tracking without attachments still works (backward compatibility)."""
        tracker.get_or_create_conversation("conv_123")
        tracker.track_agent_message(
            message="Simple message without attachments",
            metadata={"simple": True}
        )
        
        # Check that message was stored without attachments
        conv_id = tracker.config.conversation_id
        item = tracker._tracked_data[conv_id]["items"][1]
        assert item["type"] == "answer"
        assert "attachments" not in item["data"]
        assert "attachment_mode" not in item["data"]
        assert item["data"]["content"] == "Simple message without attachments"

    def test_track_agent_message_invalid_attachment_mode_raises_exception(self, tracker):
        """Test that invalid attachment mode raises ValueError."""
        tracker.get_or_create_conversation("conv_123")
        
        attachments = [{'filename': 'test.pdf', 'data': 'data'}]
        
        with pytest.raises(ValueError, match="Invalid mode"):
            tracker.track_agent_message(
                message="Test",
                attachments=attachments,
                attachment_mode='invalid_mode'
            )