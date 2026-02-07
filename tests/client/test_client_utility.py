from unittest.mock import Mock, patch
from threading import Thread
from agentsight.client import ConversationTracker
import pytest
from agentsight.exceptions import (
    NoDataToSendException
)
import time

class TestConversationTrackerSendTrackedData:
    """Test cases for send_tracked_data method."""
    
    def test_send_tracked_data_success(self, valid_api_key):
        """Test successful sending of tracked data."""
        tracker = ConversationTracker(api_key=valid_api_key)
        tracker._http_client = Mock()
        
        # Mock HTTP responses
        tracker._http_client.send_payload.side_effect = [
            {"id": "conv_123"},  # conversation
            {"id": "q1"},        # question
            {"id": "a1"}         # answer
        ]
        
        # Track some data
        tracker.get_or_create_conversation("conv_123")
        tracker.track_human_message("Test question")
        tracker.track_agent_message("Test answer")
        
        # Send tracked data
        result = tracker.send_tracked_data()
        
        # Verify response structure
        assert "items" in result
        assert "summary" in result
        assert result["summary"]["questions"] == 1
        assert result["summary"]["answers"] == 1
        assert result["summary"]["errors"] == 0
        
        # Verify data was cleared
        assert "conv_123" not in tracker._tracked_data
    
    def test_send_tracked_data_no_data_raises_exception(self, valid_api_key):
        """Test that sending with no tracked data raises NoDataToSendException."""
        tracker = ConversationTracker(api_key=valid_api_key)
        
        with pytest.raises(NoDataToSendException):
            tracker.send_tracked_data()
    
    def test_send_tracked_data_with_errors(self, valid_api_key):
        """Test sending tracked data with HTTP errors."""
        tracker = ConversationTracker(api_key=valid_api_key)
        tracker._http_client = Mock()
        
        # Mock HTTP error for question, success for conversation
        tracker._http_client.send_payload.side_effect = [
            {"id": "conv_123"},        # conversation succeeds
            Exception("HTTP Error")    # question fails
        ]
        
        # Track some data
        tracker.get_or_create_conversation("conv_123")
        tracker.track_human_message("Test question")
        
        # Send tracked data
        result = tracker.send_tracked_data()
        
        # Verify error handling
        assert result["summary"]["errors"] == 1
        assert result["summary"]["questions"] == 0  # Failed to send
        assert len(result["items"]) == 2
        assert result["items"][1]["success"] is False
        assert "HTTP Error" in result["items"][1]["error"]
    
    def test_send_tracked_data_preserves_order(self, valid_api_key):
        """Test that send_tracked_data preserves order of tracked items."""
        tracker = ConversationTracker(api_key=valid_api_key)
        tracker._http_client = Mock()
        
        # Mock HTTP responses
        tracker._http_client.send_payload.side_effect = [
            {"id": "conv_123"},  # conversation
            {"id": "q1"},        # question
            {"id": "a1"},        # answer
            {"id": "act1"}       # action
        ]
        
        # Track data in specific order
        tracker.get_or_create_conversation("conv_123")
        tracker.track_human_message("First question")
        tracker.track_agent_message("First answer")
        tracker.track_action("First action")
        
        # Send tracked data
        result = tracker.send_tracked_data()
        
        # Verify order
        items = result["items"]
        assert len(items) == 4
        assert items[0]["type"] == "conversation"
        assert items[1]["type"] == "question"
        assert items[2]["type"] == "answer"
        assert items[3]["type"] == "action"
    
    def test_send_tracked_data_with_token_usage(self, valid_api_key):
        """Test sending tracked data includes token usage when handler exists."""
        tracker = ConversationTracker(api_key=valid_api_key)
        tracker._http_client = Mock()
        
        # Mock HTTP responses
        tracker._http_client.send_payload.side_effect = [
            {"id": "conv_123"},  # conversation
            {"id": "q1"},        # question
            {"id": "token1"},    # token usage action
            {"id": "a1"}         # answer
        ]
        
        # Track data and token usage
        tracker.get_or_create_conversation("conv_123")
        tracker.track_human_message("Test question")
        tracker.track_token_usage(prompt_tokens=10, completion_tokens=20)
        tracker.track_agent_message("Test answer")
        
        # Send tracked data
        result = tracker.send_tracked_data()
        
        # Verify token usage was included
        assert len(result["items"]) == 4
        assert result["summary"]["questions"] == 1
        assert result["summary"]["answers"] == 1
        assert result["summary"]["actions"] == 1  # Token usage action
    
    def test_send_tracked_data_thread_safety(self, valid_api_key):
        """Test that send_tracked_data is thread-safe."""
        tracker = ConversationTracker(api_key=valid_api_key)
        tracker._http_client = Mock()
        
        # Mock HTTP responses
        tracker._http_client.send_payload.side_effect = [
            {"id": "conv_123"},
            {"id": "q1"}
        ]
        
        # Track some data
        tracker.get_or_create_conversation("conv_123")
        tracker.track_human_message("Test question")
        
        responses = []
        exceptions = []
        
        def send_data():
            try:
                response = tracker.send_tracked_data()
                responses.append(response)
            except Exception as e:
                exceptions.append(e)
        
        # Try to send from multiple threads
        threads = []
        for _ in range(3):
            thread = Thread(target=send_data)
            threads.append(thread)
            thread.start()
        
        for thread in threads:
            thread.join()
        
        # Only one should succeed
        assert len(responses) == 1
        assert len(exceptions) == 2
        for exc in exceptions:
            assert isinstance(exc, NoDataToSendException)


class TestConversationTrackerGetTrackedDataSummary:
    """Test cases for get_tracked_data_summary method."""
    
    def test_get_tracked_data_summary_returns_deep_copy(self, valid_api_key):
        """Test that get_tracked_data_summary returns a deep copy."""
        tracker = ConversationTracker(api_key=valid_api_key, conversation_id="conv_123")
        
        # Add some tracked data
        tracker.track_human_message("Original question")
        
        result = tracker.get_tracked_data_summary()
        
        # Modify returned data
        result["items"][0]["data"]["content"] = "Modified question"
        
        # Original should be unchanged
        original_summary = tracker.get_tracked_data_summary()
        assert original_summary["items"][0]["data"]["content"] == "Original question"


class TestConversationTrackerUtilityMethods:
    """Test cases for utility methods."""
    
    def test_get_conversation_id_returns_current_id(self, valid_api_key):
        """Test that _get_conversation_id returns current conversation ID."""
        tracker = ConversationTracker(api_key=valid_api_key, conversation_id="test-conv-123")
        
        result = tracker._get_conversation_id()
        assert result == "test-conv-123"
    
    def test_get_or_generate_conversation_id_with_provided_id(self, valid_api_key):
        """Test _get_or_generate_conversation_id with provided ID."""
        tracker = ConversationTracker(api_key=valid_api_key)
        
        result = tracker._get_or_generate_conversation_id("provided-id")
        assert result == "provided-id"
        assert tracker.config.conversation_id == "provided-id"
    
    def test_get_or_generate_conversation_id_uses_existing(self, valid_api_key):
        """Test _get_or_generate_conversation_id uses existing config ID."""
        tracker = ConversationTracker(api_key=valid_api_key, conversation_id="existing-id")
        
        result = tracker._get_or_generate_conversation_id()
        assert result == "existing-id"
    
    def test_get_or_generate_conversation_id_generates_new(self, valid_api_key):
        """Test _get_or_generate_conversation_id generates new ID when none exists."""
        tracker = ConversationTracker(api_key=valid_api_key)
        
        result = tracker._get_or_generate_conversation_id()
        assert result is not None
        assert len(result) > 0
        assert tracker.config.conversation_id == result
    
    def test_ensure_conversation_storage_creates_structure(self, valid_api_key):
        """Test that _ensure_conversation_storage creates proper structure."""
        tracker = ConversationTracker(api_key=valid_api_key)
        
        tracker._ensure_conversation_storage("conv_123")
        
        assert "conv_123" in tracker._tracked_data
        assert "items" in tracker._tracked_data["conv_123"]
        assert isinstance(tracker._tracked_data["conv_123"]["items"], list)
    
    def test_ensure_conversation_storage_idempotent(self, valid_api_key):
        """Test that _ensure_conversation_storage is idempotent."""
        tracker = ConversationTracker(api_key=valid_api_key)
        
        # Call twice
        tracker._ensure_conversation_storage("conv_123")
        tracker._ensure_conversation_storage("conv_123")
        
        # Should only have one entry
        assert len(tracker._tracked_data) == 1
        assert "conv_123" in tracker._tracked_data
    
    def test_add_tracking_item_creates_proper_structure(self, valid_api_key):
        """Test that _add_tracking_item creates proper structure."""
        tracker = ConversationTracker(api_key=valid_api_key, conversation_id="conv_123")
        
        tracker._add_tracking_item("test_type", {"test": "data"})
        
        assert "conv_123" in tracker._tracked_data
        items = tracker._tracked_data["conv_123"]["items"]
        assert len(items) == 1
        assert items[0]["type"] == "test_type"
        assert items[0]["data"] == {"test": "data"}
        assert "timestamp" in items[0]
    
    def test_add_tracking_item_thread_safety(self, valid_api_key):
        """Test that _add_tracking_item is thread-safe."""
        tracker = ConversationTracker(api_key=valid_api_key, conversation_id="conv_123")
        
        def add_item(item_id):
            tracker._add_tracking_item("test_type", {"id": item_id})
        
        # Add items from multiple threads
        threads = []
        for i in range(10):
            thread = Thread(target=add_item, args=(i,))
            threads.append(thread)
            thread.start()
        
        for thread in threads:
            thread.join()
        
        # All items should be added
        items = tracker._tracked_data["conv_123"]["items"]
        assert len(items) == 10
        
        # All items should have unique IDs
        item_ids = [item["data"]["id"] for item in items]
        assert len(set(item_ids)) == 10


class TestConversationTrackerThreadSafety:
    """Test cases for thread safety."""
    
    def test_multiple_threads_tracking_same_conversation(self, valid_api_key):
        """Test that multiple threads can track the same conversation safely."""
        tracker = ConversationTracker(api_key=valid_api_key, conversation_id="shared_conv")
        
        def track_data(thread_id):
            tracker.track_human_message(f"Question from thread {thread_id}")
            tracker.track_agent_message(f"Answer from thread {thread_id}")
        
        # Track same conversation from multiple threads
        threads = []
        for i in range(3):
            thread = Thread(target=track_data, args=(i,))
            threads.append(thread)
            thread.start()
        
        for thread in threads:
            thread.join()
        
        # All items should be tracked
        assert len(tracker._tracked_data) == 1
        assert "shared_conv" in tracker._tracked_data
        assert len(tracker._tracked_data["shared_conv"]["items"]) == 6  # 3 questions + 3 answers
    
    def test_concurrent_tracking_item_addition(self, valid_api_key):
        """Test that concurrent tracking item addition is thread-safe."""
        tracker = ConversationTracker(api_key=valid_api_key, conversation_id="thread_test")
        
        def add_items(thread_id):
            for i in range(5):
                tracker.track_human_message(f"Question {i} from thread {thread_id}")
        
        # Add items concurrently from multiple threads
        threads = []
        for i in range(3):
            thread = Thread(target=add_items, args=(i,))
            threads.append(thread)
            thread.start()
        
        for thread in threads:
            thread.join()
        
        # All items should be tracked
        assert "thread_test" in tracker._tracked_data
        assert len(tracker._tracked_data["thread_test"]["items"]) == 15  # 3 threads × 5 questions
    
    def test_thread_safety_of_storage_creation(self, valid_api_key):
        """Test that conversation storage creation is thread-safe."""
        tracker = ConversationTracker(api_key=valid_api_key)
        
        def create_storage(conv_id):
            tracker._ensure_conversation_storage(conv_id)
        
        # Create storage from multiple threads
        threads = []
        for i in range(10):
            thread = Thread(target=create_storage, args=(f"conv_{i}",))
            threads.append(thread)
            thread.start()
        
        for thread in threads:
            thread.join()
        
        # All storages should be created
        assert len(tracker._tracked_data) == 10
        for i in range(10):
            assert f"conv_{i}" in tracker._tracked_data
