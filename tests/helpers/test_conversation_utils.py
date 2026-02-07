"""Tests for helper functions."""

from datetime import datetime
from agentsight.helpers import (
    generate_conversation_id,
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

class TestTimestampGeneration:
    def test_get_iso_timestamp_format(self):
        timestamp = get_iso_timestamp()

        assert timestamp.endswith("+00:00")
        assert "T" in timestamp

        try:
            datetime.fromisoformat(timestamp)
        except ValueError:
            assert False, "Invalid ISO timestamp format"
