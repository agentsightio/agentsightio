"""Tests for helper functions."""

import pytest
from datetime import datetime
from agentsight.helpers import (
    generate_conversation_id,
    format_conversation_metadata,
    get_iso_timestamp
)


class TestIdGeneration:
    """Test ID generation functions."""

    def test_generate_conversation_id(self):
        """Test conversation ID generation."""
        conv_id = generate_conversation_id()
        
        assert conv_id.startswith("conv_")
        assert len(conv_id) == 17  # "conv_" + 12 hex chars
        
        # Test uniqueness
        conv_id2 = generate_conversation_id()
        assert conv_id != conv_id2


class TestMetadataFormatting:
    """Test metadata formatting functions."""

    def test_format_conversation_metadata_valid(self):
        """Test formatting valid metadata."""
        metadata = {
            "user_id": "user123",
            "channel": "web",
            "score": 4.5,
            "tags": ["support", "billing"]
        }
        
        formatted = format_conversation_metadata(metadata)
        
        assert formatted["user_id"] == "user123"
        assert formatted["channel"] == "web"
        assert formatted["score"] == 4.5
        assert formatted["tags"] == "['support', 'billing']"  # List converted to string

    def test_format_conversation_metadata_none(self):
        """Test formatting None metadata."""
        result = format_conversation_metadata(None)
        assert result == {}

    def test_format_conversation_metadata_empty(self):
        """Test formatting empty metadata."""
        result = format_conversation_metadata({})
        assert result == {}

    def test_format_conversation_metadata_invalid_type(self):
        """Test formatting invalid metadata type."""
        result = format_conversation_metadata("not a dict")
        assert result == {}

class TestTimestampGeneration:
    def test_get_iso_timestamp_format(self):
        timestamp = get_iso_timestamp()

        assert timestamp.endswith("+00:00")
        assert "T" in timestamp

        try:
            datetime.fromisoformat(timestamp)
        except ValueError:
            assert False, "Invalid ISO timestamp format"
