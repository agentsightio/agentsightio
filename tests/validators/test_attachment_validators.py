"""Tests for attachment validators."""

import pytest
import base64
from io import BytesIO
from agentsight.validators import (
    validate_and_process_attachments_flexible,
)
from agentsight.exceptions import InvalidAttachmentException
from agentsight.enums import AttachmentMode


class TestValidateAndProcessAttachmentsFlexible:
    """Test validate_and_process_attachments_flexible function."""

    def test_empty_attachments_raises_exception(self):
        """Test validation raises exception when attachments list is empty."""
        with pytest.raises(InvalidAttachmentException) as exc_info:
            validate_and_process_attachments_flexible([], AttachmentMode.BASE64)
        
        assert "Attachments list cannot be empty" in str(exc_info.value)

    def test_non_list_attachments_raises_exception(self):
        """Test validation raises exception when attachments is not a list."""
        with pytest.raises(InvalidAttachmentException) as exc_info:
            validate_and_process_attachments_flexible("not a list", AttachmentMode.BASE64)
        
        assert "Attachments must be provided as a list" in str(exc_info.value)

    def test_base64_mode_valid_attachments(self):
        """Test validation passes with valid base64 attachments."""
        test_data = b"test file content"
        encoded_data = base64.b64encode(test_data).decode('utf-8')
        
        attachments = [
            {
                "filename": "test.txt",
                "mime_type": "text/plain",
                "data": encoded_data
            }
        ]
        
        result = validate_and_process_attachments_flexible(attachments, AttachmentMode.BASE64)
        
        assert len(result) == 1
        assert result[0]['filename'] == "test.txt"
        assert result[0]['mime_type'] == "text/plain"
        assert result[0]['data'] == encoded_data

    def test_base64_mode_non_string_data_raises_exception(self):
        """Test validation raises exception when base64 mode data is not string."""
        attachments = [
            {
                "filename": "test.txt",
                "mime_type": "text/plain",
                "data": b"bytes data"  # Should be string in base64 mode
            }
        ]
        
        with pytest.raises(InvalidAttachmentException) as exc_info:
            validate_and_process_attachments_flexible(attachments, AttachmentMode.BASE64)
        
        assert "must be a base64 string" in str(exc_info.value)

    def test_base64_mode_invalid_base64_raises_exception(self):
        """Test validation raises exception when base64 data is invalid."""
        attachments = [
            {
                "filename": "test.txt",
                "mime_type": "text/plain",
                "data": "invalid-base64!"
            }
        ]
        
        with pytest.raises(InvalidAttachmentException) as exc_info:
            validate_and_process_attachments_flexible(attachments, AttachmentMode.BASE64)
        
        assert "invalid base64 data" in str(exc_info.value)

    def test_form_data_mode_bytes_data(self):
        """Test validation passes with bytes data in form_data mode."""
        test_data = b"test file content"
        
        attachments = [
            {
                "filename": "test.txt",
                "mime_type": "text/plain",
                "data": test_data
            }
        ]
        
        result = validate_and_process_attachments_flexible(attachments, AttachmentMode.FORM_DATA)
        
        assert len(result) == 1
        assert result[0]['filename'] == "test.txt"
        assert result[0]['mime_type'] == "text/plain"
        assert result[0]['data'] == test_data  # Data is passed through as-is
        assert isinstance(result[0]['data'], bytes)

    def test_form_data_mode_bytesio_data(self):
        """Test validation passes with BytesIO data in form_data mode."""
        test_data = b"test file content"
        bytes_io_data = BytesIO(test_data)
        
        attachments = [
            {
                "filename": "test.txt",
                "mime_type": "text/plain",
                "data": bytes_io_data
            }
        ]
        
        result = validate_and_process_attachments_flexible(attachments, AttachmentMode.FORM_DATA)
        
        assert len(result) == 1
        assert result[0]['filename'] == "test.txt"
        assert result[0]['mime_type'] == "text/plain"
        assert result[0]['data'] == bytes_io_data  # Data is passed through as-is
        assert isinstance(result[0]['data'], BytesIO)

    def test_form_data_mode_string_data_raises_exception(self):
        """Test validation raises exception when form_data mode data is string."""
        attachments = [
            {
                "filename": "test.txt",
                "mime_type": "text/plain",
                "data": "string data"  # Should not be string in form_data mode
            }
        ]
        
        with pytest.raises(InvalidAttachmentException) as exc_info:
            validate_and_process_attachments_flexible(attachments, AttachmentMode.FORM_DATA)
        
        assert "must be bytes or file-like object, not string" in str(exc_info.value)

    def test_invalid_mode_raises_exception(self):
        """Test validation raises exception with invalid mode."""
        test_data = b"test"
        
        attachments = [
            {
                "filename": "test.txt",
                "mime_type": "text/plain",
                "data": test_data
            }
        ]
        
        with pytest.raises(InvalidAttachmentException) as exc_info:
            validate_and_process_attachments_flexible(attachments, "invalid_mode")
        
        assert "Invalid mode" in str(exc_info.value)

    def test_non_dict_attachment_raises_exception(self):
        """Test validation raises exception when attachment is not a dict."""
        attachments = ["not a dict"]
        
        with pytest.raises(InvalidAttachmentException) as exc_info:
            validate_and_process_attachments_flexible(attachments, AttachmentMode.BASE64)
        
        assert "Must be a dictionary" in str(exc_info.value)

    def test_form_data_mode_minimal_data_only(self):
        """Test form_data mode with only data field (minimal requirement)."""
        test_data = b"test file content"
        
        attachments = [
            {
                "data": test_data
            }
        ]
        
        result = validate_and_process_attachments_flexible(attachments, AttachmentMode.FORM_DATA)
        
        assert len(result) == 1
        assert result[0]['data'] == test_data
        assert 'filename' not in result[0]  # Optional field not added if not provided
        assert 'mime_type' not in result[0]  # Optional field not added if not provided

    def test_form_data_mode_with_extra_fields(self):
        """Test form_data mode preserves extra fields."""
        test_data = b"test file content"
        
        attachments = [
            {
                "data": test_data,
                "filename": "test.txt",
                "mime_type": "text/plain",
                "extra_field": "extra_value",
                "another_field": 123
            }
        ]
        
        result = validate_and_process_attachments_flexible(attachments, AttachmentMode.FORM_DATA)
        
        assert len(result) == 1
        assert result[0]['data'] == test_data
        assert result[0]['filename'] == "test.txt"
        assert result[0]['mime_type'] == "text/plain"
        assert result[0]['extra_field'] == "extra_value"
        assert result[0]['another_field'] == 123

    def test_form_data_mode_content_type_alias(self):
        """Test form_data mode handles content_type as alias for mime_type."""
        test_data = b"test file content"
        
        attachments = [
            {
                "data": test_data,
                "filename": "test.txt",
                "content_type": "text/plain"
            }
        ]
        
        result = validate_and_process_attachments_flexible(attachments, AttachmentMode.FORM_DATA)
        
        assert len(result) == 1
        assert result[0]['data'] == test_data
        assert result[0]['filename'] == "test.txt"
        assert result[0]['mime_type'] == "text/plain"
        assert 'content_type' not in result[0]  # content_type is not preserved, only mime_type
