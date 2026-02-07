import pytest
from agentsight.client import ConversationTracker


class TestConversationTrackerGetOrCreateConversation:
    """Test cases for get_or_create_conversation method."""
    
    def test_get_or_create_conversation_basic(self, tracker):
        """Test creating a conversation with just conversation_id."""
        conversation_id = "conv_123"
        
        tracker.get_or_create_conversation(conversation_id)
        
        # Check that conversation was created
        assert conversation_id in tracker._tracked_data
        assert len(tracker._tracked_data[conversation_id]["items"]) == 1
        
        # Check conversation item
        item = tracker._tracked_data[conversation_id]["items"][0]
        assert item["type"] == "conversation"
        assert "timestamp" in item
        assert isinstance(item["timestamp"], str)
        assert len(item["timestamp"]) > 0
        assert item["data"]["conversation_id"] == conversation_id
        assert item["data"]["is_used"] is True
        
        # Check config was updated
        assert tracker.config.conversation_id == conversation_id
    
    def test_get_or_create_conversation_with_customer_id(self, tracker):
        """Test creating a conversation with customer_id."""
        conversation_id = "conv_456"
        customer_id = "customer_789"
        
        tracker.get_or_create_conversation(
            conversation_id=conversation_id,
            customer_id=customer_id
        )
        
        item = tracker._tracked_data[conversation_id]["items"][0]
        assert item["data"]["conversation_id"] == conversation_id
        assert item["data"]["customer_id"] == customer_id
    
    def test_get_or_create_conversation_with_all_parameters(self, tracker):
        """Test creating a conversation with all parameters."""
        conversation_id = "conv_full"
        customer_id = "customer_123"
        customer_ip = "192.168.1.1"
        device = "mobile"
        source = "web"
        language = "en"
        metadata = {"plan": "premium", "region": "us-east"}
        
        tracker.get_or_create_conversation(
            conversation_id=conversation_id,
            customer_id=customer_id,
            customer_ip_address=customer_ip,
            device=device,
            source=source,
            language=language,
            metadata=metadata
        )
        
        item = tracker._tracked_data[conversation_id]["items"][0]
        assert item["data"]["conversation_id"] == conversation_id
        assert item["data"]["customer_id"] == customer_id
        assert item["data"]["customer_ip_address"] == customer_ip
        assert item["data"]["device"] == device
        assert item["data"]["source"] == source
        assert item["data"]["language"] == language
        assert item["data"]["metadata"] == metadata
        assert item["data"]["is_used"] is True
    
    def test_get_or_create_conversation_with_partial_parameters(self, tracker):
        """Test creating a conversation with some optional parameters."""
        conversation_id = "conv_partial"
        
        tracker.get_or_create_conversation(
            conversation_id=conversation_id,
            device="desktop",
            language="es"
        )
        
        item = tracker._tracked_data[conversation_id]["items"][0]
        assert item["data"]["conversation_id"] == conversation_id
        assert item["data"]["device"] == "desktop"
        assert item["data"]["language"] == "es"
        assert item["data"]["customer_id"] is None
        assert item["data"]["customer_ip_address"] is None
        assert item["data"]["source"] is None
    
    def test_get_or_create_conversation_without_metadata(self, tracker):
        """Test that metadata is None when not provided."""
        conversation_id = "conv_no_meta"
        
        tracker.get_or_create_conversation(conversation_id)
        
        item = tracker._tracked_data[conversation_id]["items"][0]
        assert item["data"]["metadata"] is None
    
    def test_get_or_create_conversation_with_empty_metadata(self, tracker):
        """Test creating a conversation with empty metadata dict."""
        conversation_id = "conv_empty_meta"
        
        tracker.get_or_create_conversation(
            conversation_id=conversation_id,
            metadata={}
        )
        
        item = tracker._tracked_data[conversation_id]["items"][0]
        assert item["data"]["metadata"] == {}
    
    def test_get_or_create_conversation_updates_config(self, tracker):
        """Test that calling get_or_create_conversation updates config."""
        first_conv_id = "conv_first"
        second_conv_id = "conv_second"
        
        tracker.get_or_create_conversation(first_conv_id)
        assert tracker.config.conversation_id == first_conv_id
        
        tracker.get_or_create_conversation(second_conv_id)
        assert tracker.config.conversation_id == second_conv_id
    
    def test_get_or_create_conversation_multiple_times(self, tracker):
        """Test creating multiple conversations in the same tracker."""
        conv_id_1 = "conv_001"
        conv_id_2 = "conv_002"
        
        tracker.get_or_create_conversation(conv_id_1, customer_id="customer_a")
        tracker.get_or_create_conversation(conv_id_2, customer_id="customer_b")
        
        # Both conversations should exist
        assert conv_id_1 in tracker._tracked_data
        assert conv_id_2 in tracker._tracked_data
        
        # Each should have their own data
        item_1 = tracker._tracked_data[conv_id_1]["items"][0]
        item_2 = tracker._tracked_data[conv_id_2]["items"][0]
        
        assert item_1["data"]["customer_id"] == "customer_a"
        assert item_2["data"]["customer_id"] == "customer_b"
    
    def test_get_or_create_conversation_allows_tracking_after(self, tracker):
        """Test that items can be tracked after creating conversation."""
        conversation_id = "conv_track_after"
        
        tracker.get_or_create_conversation(conversation_id)
        tracker.track_human_message("What is AI?")
        
        # Should have 2 items: conversation and question
        assert len(tracker._tracked_data[conversation_id]["items"]) == 2
        assert tracker._tracked_data[conversation_id]["items"][0]["type"] == "conversation"
        assert tracker._tracked_data[conversation_id]["items"][1]["type"] == "question"
