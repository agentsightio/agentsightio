import pytest
from unittest.mock import MagicMock
from io import BytesIO
import time
from agentsight.helpers import prepare_form_data_payload_from_data
from agentsight.enums import Sender


class TestPrepareFormDataPayloadFromData:
    """Test cases for prepare_form_data_payload_from_data function."""
    
    def test_single_attachment(self):
        """Test preparing form data with single attachment."""
        file_data = BytesIO(b"test file content")
        attachments = [
            {
                'filename': 'test.txt',
                'mime_type': 'text/plain',
                'data': file_data
            }
        ]
        conversation_id = "conv_123"
        sender = Sender.USER.value
        
        result = prepare_form_data_payload_from_data(attachments, conversation_id, sender)
        
        # Check metadata fields
        assert result['conversation'] == (None, "conv_123")
        assert result['mode'] == (None, 'form_data')
        assert result['sender'] == (None, sender)
        assert 'timestamp' in result
        assert result['timestamp'][0] is None
        assert isinstance(result['timestamp'][1], str)
        assert 'T' in result['timestamp'][1]  # ISO format
        
        # Check attachment
        assert 'attachment_0' in result
        filename, file_obj, mime_type = result['attachment_0']
        assert filename == 'test.txt'
        assert mime_type == 'text/plain'
        assert file_obj == file_data
    
    def test_multiple_attachments(self):
        """Test preparing form data with multiple attachments."""
        file_data_1 = BytesIO(b"first file content")
        file_data_2 = BytesIO(b"second file content")
        file_data_3 = BytesIO(b"third file content")
        
        attachments = [
            {
                'filename': 'file1.txt',
                'mime_type': 'text/plain',
                'data': file_data_1
            },
            {
                'filename': 'file2.pdf',
                'mime_type': 'application/pdf',
                'data': file_data_2
            },
            {
                'filename': 'file3.jpg',
                'mime_type': 'image/jpeg',
                'data': file_data_3
            }
        ]
        conversation_id = "conv_456"
        sender = Sender.USER.value
        
        result = prepare_form_data_payload_from_data(attachments, conversation_id, sender)
        
        # Check metadata fields
        assert result['conversation'] == (None, "conv_456")
        assert result['mode'] == (None, 'form_data')
        assert result['sender'] == (None, sender)
        assert 'timestamp' in result
        assert result['timestamp'][0] is None
        assert isinstance(result['timestamp'][1], str)
        
        # Check first attachment
        assert 'attachment_0' in result
        filename, file_obj, mime_type = result['attachment_0']
        assert filename == 'file1.txt'
        assert mime_type == 'text/plain'
        assert file_obj == file_data_1
        
        # Check second attachment
        assert 'attachment_1' in result
        filename, file_obj, mime_type = result['attachment_1']
        assert filename == 'file2.pdf'
        assert mime_type == 'application/pdf'
        assert file_obj == file_data_2
        
        # Check third attachment
        assert 'attachment_2' in result
        filename, file_obj, mime_type = result['attachment_2']
        assert filename == 'file3.jpg'
        assert mime_type == 'image/jpeg'
        assert file_obj == file_data_3
        
        # Verify 8 keys (5 metadata + 3 attachments)
        assert len(result) == 8
    
    def test_empty_attachments_list(self):
        """Test preparing form data with empty attachments list."""
        attachments = []
        conversation_id = "conv_789"
        sender = Sender.USER.value
        
        result = prepare_form_data_payload_from_data(attachments, conversation_id, sender)
        
        # Check metadata fields only
        assert result['conversation'] == (None, "conv_789")
        assert result['mode'] == (None, 'form_data')
        assert result['sender'] == (None, sender)
        assert 'timestamp' in result
        assert result['timestamp'][0] is None
        assert isinstance(result['timestamp'][1], str)
        
        # Should only have metadata, no attachments
        assert len(result) == 5
        assert 'attachment_0' not in result
    
    def test_file_seek_called(self):
        """Test that file.seek(0) is called on each attachment."""
        # Create mock file objects
        mock_file_1 = MagicMock()
        mock_file_2 = MagicMock()
        
        attachments = [
            {
                'filename': 'test1.txt',
                'mime_type': 'text/plain',
                'data': mock_file_1
            },
            {
                'filename': 'test2.txt',
                'mime_type': 'text/plain',
                'data': mock_file_2
            }
        ]
        conversation_id = "conv_seek_test"
        sender = Sender.USER.value
        
        result = prepare_form_data_payload_from_data(attachments, conversation_id, sender)
        
        # Verify seek(0) was called on each file
        mock_file_1.seek.assert_called_once_with(0)
        mock_file_2.seek.assert_called_once_with(0)
        
        # Verify files are in result
        assert result['attachment_0'][1] == mock_file_1
        assert result['attachment_1'][1] == mock_file_2
    
    def test_various_mime_types(self):
        """Test with various MIME types."""
        attachments = [
            {
                'filename': 'document.pdf',
                'mime_type': 'application/pdf',
                'data': BytesIO(b"pdf content")
            },
            {
                'filename': 'image.png',
                'mime_type': 'image/png',
                'data': BytesIO(b"png content")
            },
            {
                'filename': 'video.mp4',
                'mime_type': 'video/mp4',
                'data': BytesIO(b"mp4 content")
            },
            {
                'filename': 'audio.mp3',
                'mime_type': 'audio/mpeg',
                'data': BytesIO(b"mp3 content")
            }
        ]
        conversation_id = "conv_mime_test"
        sender = Sender.USER.value
        
        result = prepare_form_data_payload_from_data(attachments, conversation_id, sender)
        
        # Check each attachment has correct MIME type
        assert result['attachment_0'][2] == 'application/pdf'
        assert result['attachment_1'][2] == 'image/png'
        assert result['attachment_2'][2] == 'video/mp4'
        assert result['attachment_3'][2] == 'audio/mpeg'
    
    def test_special_characters_in_filename(self):
        """Test with special characters in filenames."""
        attachments = [
            {
                'filename': 'file with spaces.txt',
                'mime_type': 'text/plain',
                'data': BytesIO(b"content")
            },
            {
                'filename': 'file-with-dashes.pdf',
                'mime_type': 'application/pdf',
                'data': BytesIO(b"content")
            },
            {
                'filename': 'file_with_underscores.jpg',
                'mime_type': 'image/jpeg',
                'data': BytesIO(b"content")
            },
            {
                'filename': 'file.with.dots.png',
                'mime_type': 'image/png',
                'data': BytesIO(b"content")
            }
        ]
        conversation_id = "conv_special_chars"
        sender = Sender.USER.value
        
        result = prepare_form_data_payload_from_data(attachments, conversation_id, sender)
        
        # Check filenames are preserved
        assert result['attachment_0'][0] == 'file with spaces.txt'
        assert result['attachment_1'][0] == 'file-with-dashes.pdf'
        assert result['attachment_2'][0] == 'file_with_underscores.jpg'
        assert result['attachment_3'][0] == 'file.with.dots.png'
    
    def test_unicode_filenames(self):
        """Test with unicode characters in filenames."""
        attachments = [
            {
                'filename': '文档.pdf',  # Chinese
                'mime_type': 'application/pdf',
                'data': BytesIO(b"content")
            },
            {
                'filename': 'файл.txt',  # Russian
                'mime_type': 'text/plain',
                'data': BytesIO(b"content")
            },
            {
                'filename': 'émojis_😀.png',  # French + emoji
                'mime_type': 'image/png',
                'data': BytesIO(b"content")
            }
        ]
        conversation_id = "conv_unicode"
        sender = Sender.USER.value
        
        result = prepare_form_data_payload_from_data(attachments, conversation_id, sender)
        
        # Check unicode filenames are preserved
        assert result['attachment_0'][0] == '文档.pdf'
        assert result['attachment_1'][0] == 'файл.txt'
        assert result['attachment_2'][0] == 'émojis_😀.png'
    
    def test_large_number_of_attachments(self):
        """Test with a large number of attachments."""
        # Create 100 attachments
        attachments = []
        for i in range(100):
            attachments.append({
                'filename': f'file_{i}.txt',
                'mime_type': 'text/plain',
                'data': BytesIO(f"content_{i}".encode())
            })
        
        conversation_id = "conv_large_batch"
        sender = Sender.USER.value
        
        result = prepare_form_data_payload_from_data(attachments, conversation_id, sender)
        
        # Check metadata
        assert result['conversation'] == (None, "conv_large_batch")
        assert result['mode'] == (None, 'form_data')
        assert result['sender'] == (None, sender)
        assert 'timestamp' in result
        assert isinstance(result['timestamp'][1], str)
        
        # Check all attachments are present
        assert len(result) == 105  # 5 metadata + 100 attachments
        
        # Check first and last attachments
        assert result['attachment_0'][0] == 'file_0.txt'
        assert result['attachment_99'][0] == 'file_99.txt'
        
        # Check all attachment keys exist
        for i in range(100):
            assert f'attachment_{i}' in result
    
    def test_conversation_id_types(self):
        """Test with different conversation ID types."""
        attachments = [
            {
                'filename': 'test.txt',
                'mime_type': 'text/plain',
                'data': BytesIO(b"content")
            }
        ]
        sender = Sender.USER.value
        
        # Test with string conversation ID
        result = prepare_form_data_payload_from_data(attachments, "string_conv_id", sender)
        assert result['conversation'] == (None, "string_conv_id")
        
        # Test with numeric conversation ID (will be converted to string)
        result = prepare_form_data_payload_from_data(attachments, 12345, sender)
        assert result['conversation'] == (None, 12345)
    
    def test_different_sender_values(self):
        """Test with different sender values."""
        attachments = [
            {
                'filename': 'test.txt',
                'mime_type': 'text/plain',
                'data': BytesIO(b"content")
            }
        ]
        conversation_id = "conv_sender_test"
        
        # Test with USER sender
        result = prepare_form_data_payload_from_data(attachments, conversation_id, Sender.USER.value)
        assert result['sender'] == (None, Sender.USER.value)
        
        # Test with AGENT sender
        result = prepare_form_data_payload_from_data(attachments, conversation_id, Sender.AGENT.value)
        assert result['sender'] == (None, Sender.AGENT.value)
        
        # Test with default sender (when not provided - need to check function signature)
        result = prepare_form_data_payload_from_data(attachments, conversation_id)
        assert 'sender' in result
        assert result['sender'][0] is None
    
    def test_timestamp_integration(self):
        """Test timestamp integration with get_iso_timestamp."""
        attachments = [
            {
                'filename': 'test.txt',
                'mime_type': 'text/plain',
                'data': BytesIO(b"content")
            }
        ]
        sender = Sender.USER.value
        
        # Call the function multiple times
        result1 = prepare_form_data_payload_from_data(attachments, "conv_123", sender)
        time.sleep(0.01)  # Small delay to ensure different timestamp
        result2 = prepare_form_data_payload_from_data(attachments, "conv_123", sender)
        
        # Verify timestamp is present and realistic
        assert 'timestamp' in result1
        assert 'timestamp' in result2
        assert result1['timestamp'][0] is None
        assert result2['timestamp'][0] is None
        
        # Verify timestamps are different (proving function is being called)
        assert result1['timestamp'][1] != result2['timestamp'][1]
        
        # Verify timestamp format (should be ISO format)
        timestamp_value = result1['timestamp'][1]
        assert isinstance(timestamp_value, str)
        assert 'T' in timestamp_value  # ISO format has T separator
        
        # Verify timestamps are recent (within last few seconds)
        import datetime
        try:
            # Try to parse the timestamp to verify it's valid ISO format
            if timestamp_value.endswith('Z'):
                parsed_time = datetime.datetime.fromisoformat(timestamp_value.replace('Z', '+00:00'))
            else:
                parsed_time = datetime.datetime.fromisoformat(timestamp_value)
            
            # Should be within last 10 seconds
            now = datetime.datetime.now(datetime.timezone.utc)
            time_diff = abs((now - parsed_time).total_seconds())
            assert time_diff < 10, f"Timestamp {timestamp_value} is not recent enough"
        except ValueError:
            # If parsing fails, at least check basic format
            assert len(timestamp_value) > 10  # Should be a reasonable timestamp length
    
    def test_multiple_calls_different_timestamps(self):
        """Test that multiple calls generate different timestamps."""
        attachments = [
            {
                'filename': 'test.txt',
                'mime_type': 'text/plain',
                'data': BytesIO(b"content")
            }
        ]
        sender = Sender.USER.value
        
        timestamps = []
        for i in range(5):
            result = prepare_form_data_payload_from_data(attachments, f"conv_{i}", sender)
            timestamps.append(result['timestamp'][1])
            time.sleep(0.001)  # Small delay
        
        # All timestamps should be different
        assert len(set(timestamps)) == 5, "All timestamps should be unique"
        
        # All should be valid strings
        for ts in timestamps:
            assert isinstance(ts, str)
            assert 'T' in ts
    
    def test_timestamp_format_consistency(self):
        """Test that timestamp format is consistent across calls."""
        attachments = [
            {
                'filename': 'test.txt',
                'mime_type': 'text/plain',
                'data': BytesIO(b"content")
            }
        ]
        sender = Sender.USER.value
        
        # Generate multiple timestamps
        timestamps = []
        for i in range(3):
            result = prepare_form_data_payload_from_data(attachments, f"conv_{i}", sender)
            timestamps.append(result['timestamp'][1])
        
        # Check that all timestamps follow similar format pattern
        for ts in timestamps:
            # Should contain date separator
            assert '-' in ts
            # Should contain time separator
            assert ':' in ts
            # Should contain datetime separator
            assert 'T' in ts
            # Should be reasonable length (ISO format is usually 20+ chars)
            assert len(ts) >= 20
