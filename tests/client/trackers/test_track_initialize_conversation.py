import pytest
from unittest.mock import patch, MagicMock
from agentsight.client import ConversationTracker


class TestConversationTrackerInitializeConversation:
    """Test cases for initialize_conversation method."""
    
    def test_initialize_conversation_basic(self, tracker):
        """Test initializing a conversation with just conversation_id."""
        conversation_id = "conv_init_123"
        
        # Mock the send_payload method on the existing instance
        tracker._http_client.send_payload = MagicMock()
        
        tracker.initialize_conversation(conversation_id)
        
        # Verify send_payload was called
        tracker._http_client.send_payload.assert_called_once()
        
        # Check the arguments
        call_args = tracker._http_client.send_payload.call_args
        assert call_args[0][0] == 'conversation'
        
        payload = call_args[0][1]
        assert payload["conversation_id"] == conversation_id
        assert payload["is_used"] is False
        assert payload["customer_id"] is None
        assert payload["customer_ip_address"] is None
        assert payload["device"] is None
        assert payload["source"] is None
        assert payload["language"] is None
        assert payload["metadata"] is None
    
    def test_initialize_conversation_with_customer_id(self, tracker):
        """Test initializing a conversation with customer_id."""
        conversation_id = "conv_init_456"
        customer_id = "customer_789"
        
        tracker._http_client.send_payload = MagicMock()
        
        tracker.initialize_conversation(
            conversation_id=conversation_id,
            customer_id=customer_id
        )
        
        call_args = tracker._http_client.send_payload.call_args
        payload = call_args[0][1]
        
        assert payload["conversation_id"] == conversation_id
        assert payload["customer_id"] == customer_id
        assert payload["is_used"] is False
    
    def test_initialize_conversation_with_all_parameters(self, tracker):
        """Test initializing a conversation with all parameters."""
        conversation_id = "conv_full_init"
        customer_id = "customer_123"
        customer_ip = "192.168.1.1"
        device = "mobile"
        source = "web"
        language = "en"
        metadata = {"plan": "premium", "region": "us-east"}
        
        tracker._http_client.send_payload = MagicMock()
        
        tracker.initialize_conversation(
            conversation_id=conversation_id,
            customer_id=customer_id,
            customer_ip_address=customer_ip,
            device=device,
            source=source,
            language=language,
            metadata=metadata
        )
        
        call_args = tracker._http_client.send_payload.call_args
        payload = call_args[0][1]
        
        assert payload["conversation_id"] == conversation_id
        assert payload["customer_id"] == customer_id
        assert payload["customer_ip_address"] == customer_ip
        assert payload["device"] == device
        assert payload["source"] == source
        assert payload["language"] == language
        assert payload["metadata"] == metadata
        assert payload["is_used"] is False
    
    def test_initialize_conversation_with_partial_parameters(self, tracker):
        """Test initializing a conversation with some optional parameters."""
        conversation_id = "conv_partial_init"
        
        tracker._http_client.send_payload = MagicMock()
        
        tracker.initialize_conversation(
            conversation_id=conversation_id,
            device="desktop",
            language="es"
        )
        
        call_args = tracker._http_client.send_payload.call_args
        payload = call_args[0][1]
        
        assert payload["conversation_id"] == conversation_id
        assert payload["device"] == "desktop"
        assert payload["language"] == "es"
        assert payload["customer_id"] is None
        assert payload["source"] is None
    
    def test_initialize_conversation_with_empty_metadata(self, tracker):
        """Test initializing a conversation with empty metadata dict."""
        conversation_id = "conv_empty_meta_init"
        
        tracker._http_client.send_payload = MagicMock()
        
        tracker.initialize_conversation(
            conversation_id=conversation_id,
            metadata={}
        )
        
        call_args = tracker._http_client.send_payload.call_args
        payload = call_args[0][1]
        
        assert payload["metadata"] == {}
        assert payload["is_used"] is False
    
    def test_initialize_conversation_sends_immediately(self, tracker):
        """Test that initialize_conversation sends immediately, not stores."""
        conversation_id = "conv_immediate"
        
        tracker._http_client.send_payload = MagicMock()
        
        tracker.initialize_conversation(conversation_id)
        
        # Should send immediately
        tracker._http_client.send_payload.assert_called_once()
        
        # Should NOT store in tracked_data
        assert conversation_id not in tracker._tracked_data
    
    def test_initialize_conversation_multiple_times(self, tracker):
        """Test initializing multiple conversations."""
        conv_id_1 = "conv_init_001"
        conv_id_2 = "conv_init_002"
        
        tracker._http_client.send_payload = MagicMock()
        
        tracker.initialize_conversation(conv_id_1, customer_id="customer_a")
        tracker.initialize_conversation(conv_id_2, customer_id="customer_b")
        
        # Should be called twice
        assert tracker._http_client.send_payload.call_count == 2
        
        # Check first call
        first_call = tracker._http_client.send_payload.call_args_list[0]
        assert first_call[0][1]["conversation_id"] == conv_id_1
        assert first_call[0][1]["customer_id"] == "customer_a"
        
        # Check second call
        second_call = tracker._http_client.send_payload.call_args_list[1]
        assert second_call[0][1]["conversation_id"] == conv_id_2
        assert second_call[0][1]["customer_id"] == "customer_b"
    
    def test_initialize_conversation_is_used_always_false(self, tracker):
        """Test that is_used is always False for initialize_conversation."""
        tracker._http_client.send_payload = MagicMock()
        
        tracker.initialize_conversation("conv_001")
        tracker.initialize_conversation("conv_002", customer_id="customer_123")
        tracker.initialize_conversation("conv_003", metadata={"test": "value"})
        
        # Check all calls have is_used = False
        for call in tracker._http_client.send_payload.call_args_list:
            payload = call[0][1]
            assert payload["is_used"] is False
    
    def test_initialize_conversation_does_not_update_config(self, tracker):
        """Test that initialize_conversation does not update tracker config."""
        original_conv_id = tracker.config.conversation_id
        
        tracker._http_client.send_payload = MagicMock()
        
        tracker.initialize_conversation("conv_new_init")
        
        # Config should not change
        assert tracker.config.conversation_id == original_conv_id
