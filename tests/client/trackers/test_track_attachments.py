from agentsight.client import ConversationTracker
from agentsight.enums import AttachmentMode
from io import BytesIO

class TestConversationTrackerTrackAttachments:
    """Test cases for track_attachments method."""
    
    def test_track_attachments_base64_mode(self, tracker):
        """Test tracking attachments in base64 mode."""
        # Use valid base64 data that will pass validation
        import base64
        base64_data = base64.b64encode(b"test content").decode('utf-8')
        
        attachments = [
            {"filename": "test.txt", "mime_type": "text/plain", "data": base64_data}
        ]
        
        tracker.get_or_create_conversation("conv_123")
        tracker.track_attachments(attachments, mode="base64")
        
        # Check that data was stored
        assert "conv_123" in tracker._tracked_data
        assert len(tracker._tracked_data["conv_123"]["items"]) == 2
        
        item = tracker._tracked_data["conv_123"]["items"][1]
        print(item)
        assert item["type"] == "attachments"
        assert item["data"]["mode"] == AttachmentMode.BASE64.value
        assert len(item["data"]["attachments"]) == 1
        
        # Check that the attachment was processed
        attachment = item["data"]["attachments"][0]
        assert attachment["filename"] == "test.txt"
        assert attachment["mime_type"] == "text/plain"

    def test_track_attachments_form_data_mode(self, tracker):
        """Test tracking attachments in form_data mode."""
        # Use BytesIO data that will pass validation for form_data mode
        attachments = [
            {"filename": "test.txt", "mime_type": "text/plain", "data": BytesIO(b"test content")}
        ]
        
        tracker.get_or_create_conversation("conv_123")
        tracker.track_attachments(attachments, "conv_123", mode="form_data")
        
        # Check that data was stored
        assert "conv_123" in tracker._tracked_data
        assert len(tracker._tracked_data["conv_123"]["items"]) == 2
        
        item = tracker._tracked_data["conv_123"]["items"][1]
        assert item["type"] == "attachments"
        assert item["data"]["mode"] == AttachmentMode.FORM_DATA.value
        assert len(item["data"]["attachments"]) == 1
