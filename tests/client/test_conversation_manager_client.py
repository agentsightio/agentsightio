import pytest
from unittest.mock import Mock, patch, MagicMock
from agentsight.client.conversation_manager_client import ConversationManager, conversation_manager
from agentsight.exceptions import (
    NoApiKeyException,
    InvalidConversationDataException,
    ConversationApiException,
    NotFoundException
)
from agentsight.config import Config
from agentsight.enums import Sentiment


class TestConversationManagerInitialization:
    """Test cases for ConversationManager initialization."""
    
    def test_init_with_api_key(self, valid_api_key):
        """Test initialization with API key."""
        manager = ConversationManager(api_key=valid_api_key)
        assert manager.config.api_key == valid_api_key
        assert manager._http_client is not None
        assert manager._initialized is True
    
    def test_init_with_config_object(self, test_config):
        """Test initialization with Config object."""
        manager = ConversationManager(config=test_config)
        assert manager.config.api_key == test_config.api_key
        assert manager.config.endpoint == test_config.endpoint
    
    def test_init_with_all_parameters(self, valid_api_key):
        """Test initialization with all parameters."""
        manager = ConversationManager(
            api_key=valid_api_key,
            endpoint="https://test.example.com"
        )
        
        assert manager.config.api_key == valid_api_key
        assert manager.config.endpoint == "https://test.example.com"
    
    def test_init_without_api_key_raises_exception(self):
        """Test that initialization without API key raises NoApiKeyException."""
        with pytest.raises(NoApiKeyException):
            ConversationManager()
    
    def test_init_with_empty_api_key_raises_exception(self):
        """Test that initialization with empty API key raises NoApiKeyException."""
        with pytest.raises(NoApiKeyException):
            ConversationManager(api_key="")
    
    def test_init_with_none_api_key_raises_exception(self):
        """Test that initialization with None API key raises NoApiKeyException."""
        with pytest.raises(NoApiKeyException):
            ConversationManager(api_key=None)
    
    def test_http_client_initialization(self, valid_api_key):
        """Test that HTTPClient is initialized correctly."""
        manager = ConversationManager(api_key=valid_api_key)
        
        assert hasattr(manager, '_http_client')
        assert manager._http_client is not None
        assert manager._http_client.config == manager.config
    
    def test_init_default_endpoint(self, valid_api_key):
        """Test that default endpoint is set correctly."""
        manager = ConversationManager(api_key=valid_api_key)
        
        assert manager.config.endpoint == "https://api.agentsight.io"
    
    def test_init_with_custom_endpoint(self, valid_api_key):
        """Test initialization with custom endpoint."""
        manager = ConversationManager(
            api_key=valid_api_key,
            endpoint="https://custom.api.com"
        )
        
        assert manager.config.endpoint == "https://custom.api.com"
    
    def test_init_with_none_config_creates_new_config(self, valid_api_key):
        """Test that None config creates new Config instance."""
        manager = ConversationManager(api_key=valid_api_key, config=None)
        
        assert manager.config is not None
        assert isinstance(manager.config, Config)
        assert manager.config.api_key == valid_api_key
    
    def test_singleton_pattern_returns_same_instance(self, valid_api_key):
        """Test that singleton pattern returns the same instance."""
        # Reset singleton for ConversationManager
        from threading import Lock
        ConversationManager._instance = None
        ConversationManager._instance_lock = Lock()
        
        manager1 = ConversationManager(api_key=valid_api_key)
        manager2 = ConversationManager(api_key=valid_api_key)
        
        # Should be the same instance
        assert manager1 is manager2
        assert id(manager1) == id(manager2)
    
    def test_singleton_reinitialization_prevented(self, valid_api_key):
        """Test that singleton prevents re-initialization."""
        # Reset singleton for ConversationManager
        from threading import Lock
        ConversationManager._instance = None
        ConversationManager._instance_lock = Lock()
        
        manager1 = ConversationManager(api_key=valid_api_key, endpoint="https://first.com")
        manager2 = ConversationManager(api_key=valid_api_key, endpoint="https://second.com")
        
        # Both should be the same instance
        assert manager1 is manager2
        # Endpoint from first initialization should be preserved
        assert manager1.config.endpoint == "https://first.com"
        assert manager2.config.endpoint == "https://first.com"


class TestConversationManagerConfigure:
    """Test cases for ConversationManager configure method."""
    
    def test_configure_with_new_api_key(self, valid_api_key):
        """Test reconfiguration with new API key."""
        manager = ConversationManager(api_key=valid_api_key)
        new_api_key = "ags_22222222222222222222222222222222_222222"
        
        manager.configure(api_key=new_api_key)
        
        assert manager.config.api_key == new_api_key
        assert manager._http_client.config.api_key == new_api_key
    
    def test_configure_with_new_endpoint(self, valid_api_key):
        """Test reconfiguration with new endpoint."""
        manager = ConversationManager(api_key=valid_api_key)
        new_endpoint = "https://new.endpoint.com"
        
        manager.configure(endpoint=new_endpoint)
        
        assert manager.config.endpoint == new_endpoint
        assert manager._http_client.config.endpoint == new_endpoint
    
    def test_configure_without_api_key_raises_exception(self, valid_api_key):
        """Test that reconfiguration without API key raises exception."""
        manager = ConversationManager(api_key=valid_api_key)
        
        with pytest.raises(NoApiKeyException):
            manager.configure(api_key=None)
    
    def test_configure_with_empty_api_key_raises_exception(self, valid_api_key):
        """Test that reconfiguration with empty API key raises exception."""
        manager = ConversationManager(api_key=valid_api_key)
        
        with pytest.raises(NoApiKeyException):
            manager.configure(api_key="")


class TestConversationManagerSubmitFeedback:
    """Test cases for submit_feedback method."""
    
    def test_submit_feedback_with_sentiment_enum(self, valid_api_key):
        """Test submitting feedback with Sentiment enum."""
        manager = ConversationManager(api_key=valid_api_key)
        manager._http_client = Mock()
        
        expected_response = {"id": 1, "sentiment": "positive"}
        manager._http_client.post.return_value = expected_response
        
        result = manager.submit_feedback(
            conversation_id="conv1",
            sentiment=Sentiment.POSITIVE
        )
        
        assert result == expected_response
        manager._http_client.post.assert_called_once_with(
            '/api/conversation-feedbacks/',
            data={
                "conversation_id": "conv1",
                "sentiment": "positive"
            }
        )
    
    def test_submit_feedback_with_sentiment_string(self, valid_api_key):
        """Test submitting feedback with sentiment as string."""
        manager = ConversationManager(api_key=valid_api_key)
        manager._http_client = Mock()
        
        expected_response = {"id": 1, "sentiment": "negative"}
        manager._http_client.post.return_value = expected_response
        
        result = manager.submit_feedback(
            conversation_id="conv1",
            sentiment="negative"
        )
        
        assert result == expected_response
        call_args = manager._http_client.post.call_args
        assert call_args[0][0] == '/api/conversation-feedbacks/'
        assert call_args[1]['data']['sentiment'] == "negative"
    
    def test_submit_feedback_with_comment(self, valid_api_key):
        """Test submitting feedback with comment."""
        manager = ConversationManager(api_key=valid_api_key)
        manager._http_client = Mock()
        
        expected_response = {"id": 1, "comment": "Great service!"}
        manager._http_client.post.return_value = expected_response
        
        result = manager.submit_feedback(
            conversation_id="conv1",
            sentiment=Sentiment.POSITIVE,
            comment="Great service!"
        )
        
        assert result == expected_response
        call_args = manager._http_client.post.call_args
        assert call_args[1]['data']['comment'] == "Great service!"
    
    def test_submit_feedback_with_metadata(self, valid_api_key):
        """Test submitting feedback with metadata."""
        manager = ConversationManager(api_key=valid_api_key)
        manager._http_client = Mock()
        
        metadata = {"source": "web", "rating": 5}
        expected_response = {"id": 1}
        manager._http_client.post.return_value = expected_response
        
        result = manager.submit_feedback(
            conversation_id="conv1",
            sentiment=Sentiment.POSITIVE,
            metadata=metadata
        )
        
        assert result == expected_response
        call_args = manager._http_client.post.call_args
        assert call_args[1]['data']['metadata'] == metadata
    
    def test_submit_feedback_with_all_fields(self, valid_api_key):
        """Test submitting feedback with all fields."""
        manager = ConversationManager(api_key=valid_api_key)
        manager._http_client = Mock()
        
        metadata = {"source": "mobile"}
        expected_response = {"id": 1}
        manager._http_client.post.return_value = expected_response
        
        result = manager.submit_feedback(
            conversation_id="conv1",
            sentiment=Sentiment.NEUTRAL,
            comment="It was okay",
            metadata=metadata
        )
        
        assert result == expected_response
        call_args = manager._http_client.post.call_args
        data = call_args[1]['data']
        assert data['conversation_id'] == "conv1"
        assert data['sentiment'] == "neutral"
        assert data['comment'] == "It was okay"
        assert data['metadata'] == metadata
    
    def test_submit_feedback_without_conversation_id_raises_exception(self, valid_api_key):
        """Test that submitting feedback without conversation_id raises exception."""
        manager = ConversationManager(api_key=valid_api_key)
        
        with pytest.raises(ValueError, match="conversation_id is required"):
            manager.submit_feedback(
                conversation_id="",
                sentiment=Sentiment.POSITIVE
            )
    
    def test_submit_feedback_with_invalid_sentiment_raises_exception(self, valid_api_key):
        """Test that submitting feedback with invalid sentiment raises exception."""
        manager = ConversationManager(api_key=valid_api_key)
        
        with pytest.raises(InvalidConversationDataException, match="Invalid sentiment"):
            manager.submit_feedback(
                conversation_id="conv1",
                sentiment="invalid_sentiment"
            )
    
    def test_submit_feedback_with_non_string_comment_raises_exception(self, valid_api_key):
        """Test that submitting feedback with non-string comment raises exception."""
        manager = ConversationManager(api_key=valid_api_key)
        
        with pytest.raises(InvalidConversationDataException, match="Field 'comment' must be a string"):
            manager.submit_feedback(
                conversation_id="conv1",
                sentiment=Sentiment.POSITIVE,
                comment=12345
            )
    
    def test_submit_feedback_with_comment_too_long_raises_exception(self, valid_api_key):
        """Test that submitting feedback with comment exceeding 5000 chars raises exception."""
        manager = ConversationManager(api_key=valid_api_key)
        long_comment = "a" * 5001
        
        with pytest.raises(InvalidConversationDataException, match="cannot exceed 5000 characters"):
            manager.submit_feedback(
                conversation_id="conv1",
                sentiment=Sentiment.POSITIVE,
                comment=long_comment
            )
    
    def test_submit_feedback_with_comment_exactly_5000_chars(self, valid_api_key):
        """Test that submitting feedback with comment exactly 5000 chars succeeds."""
        manager = ConversationManager(api_key=valid_api_key)
        manager._http_client = Mock()
        
        comment = "a" * 5000
        expected_response = {"id": 1}
        manager._http_client.post.return_value = expected_response
        
        result = manager.submit_feedback(
            conversation_id="conv1",
            sentiment=Sentiment.POSITIVE,
            comment=comment
        )
        
        assert result == expected_response
    
    def test_submit_feedback_handles_api_error(self, valid_api_key):
        """Test that submit_feedback handles API errors."""
        manager = ConversationManager(api_key=valid_api_key)
        manager._http_client = Mock()
        
        manager._http_client.post.side_effect = ConversationApiException(
            "API error",
            status_code=500
        )
        
        with pytest.raises(ConversationApiException):
            manager.submit_feedback(
                conversation_id="conv1",
                sentiment=Sentiment.POSITIVE
            )


class TestConversationManagerResolvePk:
    """Test cases for _resolve_conversation_pk helper method."""
    
    def test_resolve_with_int_returns_same(self, valid_api_key):
        """Test that integer pk is returned as-is."""
        manager = ConversationManager(api_key=valid_api_key)
        manager._http_client = Mock()
        
        result = manager._resolve_conversation_pk(42)
        
        assert result == 42
        manager._http_client.get.assert_not_called()
    
    def test_resolve_with_string_calls_lookup(self, valid_api_key):
        """Test that string conversation_id triggers lookup."""
        manager = ConversationManager(api_key=valid_api_key)
        manager._http_client = Mock()
        manager._http_client.get.return_value = {'id': 42, 'conversation_id': 'conv1'}
        
        result = manager._resolve_conversation_pk("conv1")
        
        assert result == 42
        manager._http_client.get.assert_called_once_with(
            '/api/conversations/lookup/',
            params={'conversation_id': 'conv1'}
        )
    
    def test_resolve_with_invalid_type_raises_error(self, valid_api_key):
        """Test that invalid type raises ValueError."""
        manager = ConversationManager(api_key=valid_api_key)
        
        with pytest.raises(ValueError, match="must be int or str"):
            manager._resolve_conversation_pk(12.5)
    
    def test_resolve_string_multiple_calls(self, valid_api_key):
        """Test that each string lookup makes an API call (no caching)."""
        manager = ConversationManager(api_key=valid_api_key)
        manager._http_client = Mock()
        manager._http_client.get.return_value = {'id': 42, 'conversation_id': 'conv1'}
        
        # First call
        result1 = manager._resolve_conversation_pk("conv1")
        assert result1 == 42
        
        # Second call - should make another API call (no caching)
        result2 = manager._resolve_conversation_pk("conv1")
        assert result2 == 42
        
        # Should have called API twice (once for each lookup)
        assert manager._http_client.get.call_count == 2
        
        # Both calls should be identical
        manager._http_client.get.assert_called_with(
            '/api/conversations/lookup/',
            params={'conversation_id': 'conv1'}
        )
    
    def test_resolve_missing_id_in_response_raises_error(self, valid_api_key):
        """Test that missing 'id' in lookup response raises ValueError."""
        manager = ConversationManager(api_key=valid_api_key)
        manager._http_client = Mock()
        manager._http_client.get.return_value = {'conversation_id': 'conv1'}  # Missing 'id'
        
        with pytest.raises(ValueError, match="Could not resolve pk"):
            manager._resolve_conversation_pk("conv1")

class TestConversationManagerRenameConversation:
    """Test cases for rename_conversation method."""
    
    def test_rename_conversation_success_with_string_id(self, valid_api_key):
        """Test successfully renaming a conversation using string conversation_id."""
        manager = ConversationManager(api_key=valid_api_key)
        manager._http_client = Mock()
        
        # Mock the lookup
        manager._http_client.get.return_value = {'id': 42, 'conversation_id': 'conv1'}
        
        expected_response = {
            "id": 42,
            "conversation_id": "conv1",
            "name": "New Name"
        }
        manager._http_client.patch.return_value = expected_response
        
        result = manager.rename_conversation("conv1", "New Name")
        
        assert result == expected_response
        manager._http_client.get.assert_called_once_with(
            '/api/conversations/lookup/',
            params={'conversation_id': 'conv1'}
        )
        manager._http_client.patch.assert_called_once_with(
            '/api/conversations/42/rename/',
            data={'name': 'New Name'}
        )
    
    def test_rename_conversation_success_with_int_id(self, valid_api_key):
        """Test successfully renaming a conversation using integer pk."""
        manager = ConversationManager(api_key=valid_api_key)
        manager._http_client = Mock()
        
        expected_response = {
            "id": 42,
            "conversation_id": "conv1",
            "name": "New Name"
        }
        manager._http_client.patch.return_value = expected_response
        
        result = manager.rename_conversation(42, "New Name")
        
        assert result == expected_response
        # Should not call lookup when using integer pk
        manager._http_client.get.assert_not_called()
        manager._http_client.patch.assert_called_once_with(
            '/api/conversations/42/rename/',
            data={'name': 'New Name'}
        )
    
    def test_rename_conversation_strips_whitespace(self, valid_api_key):
        """Test that rename_conversation strips whitespace from name."""
        manager = ConversationManager(api_key=valid_api_key)
        manager._http_client = Mock()
        
        expected_response = {
            "id": 42,
            "conversation_id": "conv1",
            "name": "Trimmed"
        }
        manager._http_client.patch.return_value = expected_response
        
        manager.rename_conversation(42, "  Trimmed  ")
        
        # Verify the name was stripped in the request
        call_args = manager._http_client.patch.call_args
        assert call_args[1]['data']['name'] == "Trimmed"
    
    def test_rename_conversation_without_conversation_id_raises_exception(self, valid_api_key):
        """Test that renaming conversation without conversation_id raises exception."""
        manager = ConversationManager(api_key=valid_api_key)
        
        with pytest.raises(ValueError, match="conversation_id is required"):
            manager.rename_conversation("", "New Name")
    
    def test_rename_conversation_with_none_conversation_id_raises_exception(self, valid_api_key):
        """Test that renaming conversation with None conversation_id raises exception."""
        manager = ConversationManager(api_key=valid_api_key)
        
        with pytest.raises(ValueError, match="conversation_id is required"):
            manager.rename_conversation(None, "New Name")
    
    def test_rename_conversation_with_non_string_name_raises_exception(self, valid_api_key):
        """Test that renaming conversation with non-string name raises exception."""
        manager = ConversationManager(api_key=valid_api_key)
        
        with pytest.raises(InvalidConversationDataException, match="Field 'name' must be a non-empty string"):
            manager.rename_conversation("conv1", 12345)
    
    def test_rename_conversation_with_empty_name_raises_exception(self, valid_api_key):
        """Test that renaming conversation with empty name raises exception."""
        manager = ConversationManager(api_key=valid_api_key)
        
        with pytest.raises(InvalidConversationDataException, match="Field 'name' cannot be empty"):
            manager.rename_conversation("conv1", "   ")
    
    def test_rename_conversation_with_name_too_long_raises_exception(self, valid_api_key):
        """Test that renaming conversation with name exceeding 255 chars raises exception."""
        manager = ConversationManager(api_key=valid_api_key)
        long_name = "a" * 256
        
        with pytest.raises(InvalidConversationDataException, match="cannot exceed 255 characters"):
            manager.rename_conversation("conv1", long_name)
    
    def test_rename_conversation_with_name_exactly_255_chars(self, valid_api_key):
        """Test that renaming conversation with name exactly 255 chars succeeds."""
        manager = ConversationManager(api_key=valid_api_key)
        manager._http_client = Mock()
        
        name = "a" * 255
        expected_response = {
            "id": 42,
            "conversation_id": "conv1",
            "name": name
        }
        manager._http_client.patch.return_value = expected_response
        
        result = manager.rename_conversation(42, name)
        
        assert result == expected_response
        manager._http_client.patch.assert_called_once_with(
            '/api/conversations/42/rename/',
            data={'name': name}
        )
    
    def test_rename_conversation_handles_api_error(self, valid_api_key):
        """Test that rename_conversation handles API errors."""
        manager = ConversationManager(api_key=valid_api_key)
        manager._http_client = Mock()
        
        from agentsight.exceptions import ConversationApiException
        
        manager._http_client.patch.side_effect = ConversationApiException(
            "API error",
            status_code=500
        )
        
        with pytest.raises(ConversationApiException):
            manager.rename_conversation(42, "New Name")
    
    def test_rename_conversation_lookup_fails(self, valid_api_key):
        """Test that rename_conversation handles lookup failures for string IDs."""
        manager = ConversationManager(api_key=valid_api_key)
        manager._http_client = Mock()
        
        from agentsight.exceptions import ConversationApiException
        
        # Mock lookup failure
        manager._http_client.get.side_effect = ConversationApiException(
            "Conversation not found",
            status_code=404
        )
        
        with pytest.raises(ConversationApiException):
            manager.rename_conversation("nonexistent-conv", "New Name")
        
        # Verify patch was never called
        manager._http_client.patch.assert_not_called()

class TestConversationManagerMarkConversation:
    """Test cases for mark_conversation method."""
    
    def test_mark_conversation_with_int_id_true(self, valid_api_key):
        """Test marking a conversation as favorite using integer pk."""
        manager = ConversationManager(api_key=valid_api_key)
        manager._http_client = Mock()
        
        expected_response = {
            "id": 123,
            "conversation_id": "conv1",
            "is_marked": True
        }
        manager._http_client.post.return_value = expected_response
        
        result = manager.mark_conversation(123, True)
        
        assert result == expected_response
        # Should not call lookup when using integer pk
        manager._http_client.get.assert_not_called()
        manager._http_client.post.assert_called_once_with(
            '/api/conversations/123/mark/',
            data={'is_marked': True}
        )
    
    def test_mark_conversation_with_int_id_false(self, valid_api_key):
        """Test unmarking a conversation using integer pk."""
        manager = ConversationManager(api_key=valid_api_key)
        manager._http_client = Mock()
        
        expected_response = {
            "id": 123,
            "conversation_id": "conv1",
            "is_marked": False
        }
        manager._http_client.post.return_value = expected_response
        
        result = manager.mark_conversation(123, False)
        
        assert result == expected_response
        call_args = manager._http_client.post.call_args
        assert call_args[1]['data']['is_marked'] is False
    
    def test_mark_conversation_with_string_id(self, valid_api_key):
        """Test marking conversation using string conversation_id."""
        manager = ConversationManager(api_key=valid_api_key)
        manager._http_client = Mock()
        
        # Mock the lookup
        manager._http_client.get.return_value = {'id': 123, 'conversation_id': 'conv1'}
        
        expected_response = {
            "id": 123,
            "conversation_id": "conv1",
            "is_marked": True
        }
        manager._http_client.post.return_value = expected_response
        
        result = manager.mark_conversation("conv1", True)
        
        assert result == expected_response
        # Should call lookup for string ID
        manager._http_client.get.assert_called_once_with(
            '/api/conversations/lookup/',
            params={'conversation_id': 'conv1'}
        )
        manager._http_client.post.assert_called_once_with(
            '/api/conversations/123/mark/',
            data={'is_marked': True}
        )
    
    def test_mark_conversation_with_different_id(self, valid_api_key):
        """Test marking conversation with different ID."""
        manager = ConversationManager(api_key=valid_api_key)
        manager._http_client = Mock()
        
        expected_response = {
            "id": 456,
            "conversation_id": "conv2",
            "is_marked": True
        }
        manager._http_client.post.return_value = expected_response
        
        result = manager.mark_conversation(456, True)
        
        assert result == expected_response
        manager._http_client.post.assert_called_once_with(
            '/api/conversations/456/mark/',
            data={'is_marked': True}
        )
    
    def test_mark_conversation_with_none_id_raises_exception(self, valid_api_key):
        """Test that marking conversation with None ID raises exception."""
        manager = ConversationManager(api_key=valid_api_key)
        
        with pytest.raises(ValueError, match="conversation_id is required"):
            manager.mark_conversation(None, True)
    
    def test_mark_conversation_with_empty_string_raises_exception(self, valid_api_key):
        """Test that marking conversation with empty string raises exception."""
        manager = ConversationManager(api_key=valid_api_key)
        
        with pytest.raises(ValueError, match="conversation_id is required"):
            manager.mark_conversation("", True)
    
    def test_mark_conversation_with_invalid_type_raises_exception(self, valid_api_key):
        """Test that marking conversation with invalid type raises exception."""
        manager = ConversationManager(api_key=valid_api_key)
        
        with pytest.raises(ValueError, match="must be int or str"):
            manager.mark_conversation(12.5, True)
    
    def test_mark_conversation_converts_is_marked_to_bool(self, valid_api_key):
        """Test that is_marked is converted to boolean."""
        manager = ConversationManager(api_key=valid_api_key)
        manager._http_client = Mock()
        
        expected_response = {
            "id": 123,
            "conversation_id": "conv1",
            "is_marked": True
        }
        manager._http_client.post.return_value = expected_response
        
        # Pass various truthy/falsy values
        manager.mark_conversation(123, 1)
        call_args = manager._http_client.post.call_args
        assert call_args[1]['data']['is_marked'] is True
        
        manager._http_client.reset_mock()
        
        manager.mark_conversation(123, 0)
        call_args = manager._http_client.post.call_args
        assert call_args[1]['data']['is_marked'] is False
    
    def test_mark_conversation_handles_api_error(self, valid_api_key):
        """Test that mark_conversation handles API errors."""
        manager = ConversationManager(api_key=valid_api_key)
        manager._http_client = Mock()
        
        from agentsight.exceptions import ConversationApiException
        
        manager._http_client.post.side_effect = ConversationApiException(
            "API error",
            status_code=500
        )
        
        with pytest.raises(ConversationApiException):
            manager.mark_conversation(123, True)
    
    def test_mark_conversation_lookup_fails(self, valid_api_key):
        """Test that mark_conversation handles lookup failures for string IDs."""
        manager = ConversationManager(api_key=valid_api_key)
        manager._http_client = Mock()
        
        from agentsight.exceptions import ConversationApiException
        
        # Mock lookup failure
        manager._http_client.get.side_effect = ConversationApiException(
            "Conversation not found",
            status_code=404
        )
        
        with pytest.raises(ConversationApiException):
            manager.mark_conversation("nonexistent-conv", True)
        
        # Verify post was never called
        manager._http_client.post.assert_not_called()


class TestConversationManagerDeleteConversation:
    """Test cases for delete_conversation method."""
    
    def test_delete_conversation_success_with_string_id(self, valid_api_key):
        """Test successfully deleting a conversation using string conversation_id."""
        manager = ConversationManager(api_key=valid_api_key)
        manager._http_client = Mock()
        
        # Mock the lookup
        manager._http_client.get.return_value = {'id': 123, 'conversation_id': 'conv1'}
        
        expected_response = {
            "id": 123,
            "conversation_id": "conv1",
            "is_deleted": True,
            "deleted_at": "2024-01-01T00:00:00Z"
        }
        manager._http_client.delete.return_value = expected_response
        
        result = manager.delete_conversation("conv1")
        
        assert result == expected_response
        # Should call lookup for string ID
        manager._http_client.get.assert_called_once_with(
            '/api/conversations/lookup/',
            params={'conversation_id': 'conv1'}
        )
        manager._http_client.delete.assert_called_once_with(
            '/api/conversations/123/delete/'
        )
    
    def test_delete_conversation_success_with_int_id(self, valid_api_key):
        """Test successfully deleting a conversation using integer pk."""
        manager = ConversationManager(api_key=valid_api_key)
        manager._http_client = Mock()
        
        expected_response = {
            "id": 123,
            "conversation_id": "conv1",
            "is_deleted": True,
            "deleted_at": "2024-01-01T00:00:00Z"
        }
        manager._http_client.delete.return_value = expected_response
        
        result = manager.delete_conversation(123)
        
        assert result == expected_response
        # Should not call lookup when using integer pk
        manager._http_client.get.assert_not_called()
        manager._http_client.delete.assert_called_once_with(
            '/api/conversations/123/delete/'
        )
    
    def test_delete_conversation_with_different_string_id(self, valid_api_key):
        """Test deleting conversation with different string ID."""
        manager = ConversationManager(api_key=valid_api_key)
        manager._http_client = Mock()
        
        # Mock the lookup
        manager._http_client.get.return_value = {'id': 456, 'conversation_id': 'conv2'}
        
        expected_response = {
            "id": 456,
            "conversation_id": "conv2",
            "is_deleted": True,
            "deleted_at": "2024-01-01T00:00:00Z"
        }
        manager._http_client.delete.return_value = expected_response
        
        result = manager.delete_conversation("conv2")
        
        assert result == expected_response
        manager._http_client.get.assert_called_once_with(
            '/api/conversations/lookup/',
            params={'conversation_id': 'conv2'}
        )
        manager._http_client.delete.assert_called_once_with(
            '/api/conversations/456/delete/'
        )
    
    def test_delete_conversation_with_different_int_id(self, valid_api_key):
        """Test deleting conversation with different integer ID."""
        manager = ConversationManager(api_key=valid_api_key)
        manager._http_client = Mock()
        
        expected_response = {
            "id": 456,
            "conversation_id": "conv2",
            "is_deleted": True
        }
        manager._http_client.delete.return_value = expected_response
        
        result = manager.delete_conversation(456)
        
        assert result == expected_response
        manager._http_client.delete.assert_called_once_with(
            '/api/conversations/456/delete/'
        )
    
    def test_delete_conversation_with_empty_string_raises_exception(self, valid_api_key):
        """Test that deleting conversation with empty string raises exception."""
        manager = ConversationManager(api_key=valid_api_key)
        
        with pytest.raises(ValueError, match="conversation_id is required"):
            manager.delete_conversation("")
    
    def test_delete_conversation_with_none_raises_exception(self, valid_api_key):
        """Test that deleting conversation with None raises exception."""
        manager = ConversationManager(api_key=valid_api_key)
        
        with pytest.raises(ValueError, match="conversation_id is required"):
            manager.delete_conversation(None)
    
    def test_delete_conversation_with_invalid_type_raises_exception(self, valid_api_key):
        """Test that deleting conversation with invalid type raises exception."""
        manager = ConversationManager(api_key=valid_api_key)
        
        with pytest.raises(ValueError, match="must be int or str"):
            manager.delete_conversation(12.5)
    
    def test_delete_conversation_handles_not_found_with_string_id(self, valid_api_key):
        """Test that delete_conversation handles not found during lookup."""
        manager = ConversationManager(api_key=valid_api_key)
        manager._http_client = Mock()
        
        from agentsight.exceptions import NotFoundException
        
        manager._http_client.get.side_effect = NotFoundException("Conversation not found")
        
        with pytest.raises(NotFoundException):
            manager.delete_conversation("conv1")
        
        # Verify delete was never called
        manager._http_client.delete.assert_not_called()
    
    def test_delete_conversation_handles_not_found_on_delete(self, valid_api_key):
        """Test that delete_conversation handles not found during deletion."""
        manager = ConversationManager(api_key=valid_api_key)
        manager._http_client = Mock()
        
        from agentsight.exceptions import NotFoundException
        
        manager._http_client.delete.side_effect = NotFoundException("Conversation not found or already deleted")
        
        with pytest.raises(NotFoundException):
            manager.delete_conversation(123)
    
    def test_delete_conversation_handles_api_error(self, valid_api_key):
        """Test that delete_conversation handles API errors."""
        manager = ConversationManager(api_key=valid_api_key)
        manager._http_client = Mock()
        
        from agentsight.exceptions import ConversationApiException
        
        manager._http_client.delete.side_effect = ConversationApiException(
            "API error",
            status_code=500
        )
        
        with pytest.raises(ConversationApiException):
            manager.delete_conversation(123)
    
    def test_delete_conversation_lookup_fails(self, valid_api_key):
        """Test that delete_conversation handles lookup failures for string IDs."""
        manager = ConversationManager(api_key=valid_api_key)
        manager._http_client = Mock()
        
        from agentsight.exceptions import ConversationApiException
        
        # Mock lookup failure
        manager._http_client.get.side_effect = ConversationApiException(
            "Conversation not found",
            status_code=404
        )
        
        with pytest.raises(ConversationApiException):
            manager.delete_conversation("nonexistent-conv")
        
        # Verify delete was never called
        manager._http_client.delete.assert_not_called()

class TestConversationManagerAutoInitialized:
    """Test cases for auto-initialized conversation_manager instance."""
    
    def test_auto_initialized_instance_with_env_api_key(self, monkeypatch, valid_api_key):
        """Test that auto-initialized conversation_manager works with API key from env."""
        # Reset singleton
        from threading import Lock
        import importlib
        ConversationManager._instance = None
        ConversationManager._instance_lock = Lock()
        
        # Set API key in environment
        monkeypatch.setenv("AGENTSIGHT_API_KEY", valid_api_key)
        
        # Reload module to trigger auto-initialization
        import agentsight.client.conversation_manager_client
        importlib.reload(agentsight.client.conversation_manager_client)
        
        # Get the auto-initialized instance
        auto_manager = agentsight.client.conversation_manager_client.conversation_manager
        
        # Should be initialized successfully
        assert auto_manager is not None
        assert auto_manager.config.api_key == valid_api_key
        assert auto_manager._initialized is True
    
    def test_auto_initialized_instance_without_api_key_raises_exception(self, monkeypatch):
        """Test that auto-initialized conversation_manager raises exception without API key."""
        # Reset singleton
        from threading import Lock
        import importlib
        ConversationManager._instance = None
        ConversationManager._instance_lock = Lock()
        
        # Ensure no API key in environment
        monkeypatch.delenv("AGENTSIGHT_API_KEY", raising=False)
        
        # Reload module - this should raise NoApiKeyException
        import agentsight.client.conversation_manager_client
        with pytest.raises(NoApiKeyException):
            importlib.reload(agentsight.client.conversation_manager_client)
    
    def test_multiple_instances_return_same_singleton(self, valid_api_key):
        """Test that creating multiple instances returns the same singleton."""
        # Create first instance
        manager1 = ConversationManager(api_key=valid_api_key)
        
        # Create second instance (should return same instance due to singleton)
        manager2 = ConversationManager(api_key="different_key")
        
        # Should be the same instance
        assert manager1 is manager2
        assert id(manager1) == id(manager2)
        
        # Should use the first API key from first initialization
        assert manager1.config.api_key == valid_api_key

    def test_multiple_manual_instances_are_singleton(self, reset_all_singletons, valid_api_key):
        """Test that manually creating multiple instances returns the same singleton."""
        # Create first instance
        manager1 = ConversationManager(api_key=valid_api_key)
        
        # Create second instance (should return same instance due to singleton)
        manager2 = ConversationManager(api_key="different_key")
        
        # Should be the same instance
        assert manager1 is manager2
        assert id(manager1) == id(manager2)
        
        # Should use the first API key
        assert manager1.config.api_key == valid_api_key

    def test_configure_without_api_key_raises_exception(self, valid_api_key):
        """Test that reconfiguration with None API key raises exception."""
        manager = ConversationManager(api_key=valid_api_key)
        
        with pytest.raises(NoApiKeyException, match="API key cannot be None"):
            manager.configure(api_key=None)

    def test_module_level_manager_works_on_first_import(self, valid_api_key, monkeypatch):
        """Test that importing conversation_manager works even without explicit initialization."""
        # Set API key in environment for auto-initialization
        monkeypatch.setenv("AGENTSIGHT_API_KEY", valid_api_key)
        
        # Import the module-level instance
        from agentsight.client.conversation_manager_client import conversation_manager
        
        # Should be initialized and working
        assert conversation_manager is not None
        assert conversation_manager.config.api_key == valid_api_key
        
        # Should be able to use it
        assert hasattr(conversation_manager, 'submit_feedback')
        assert hasattr(conversation_manager, 'rename_conversation')