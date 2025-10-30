import pytest
from unittest.mock import patch, MagicMock
from agentsight.client import ConversationTracker
from agentsight.config import Config
from agentsight.enums import TokenHandlerType, LogLevel
from agentsight.exceptions import NoDataToSendException, InvalidApiKeyException


class TestConversationTrackerTokenUsage:
    """Test cases for token usage tracking methods."""
    
    def test_token_handler_initializes_as_none_by_default(self, valid_api_key):
        """Test that token handler starts as None when not configured."""
        tracker = ConversationTracker(api_key=valid_api_key)
        
        assert tracker._token_handler is None
        assert tracker.config.token_handler is None
    
    def test_token_handler_from_constructor_param(self, valid_api_key):
        """Test that token handler can be set via constructor parameter."""
        tracker = ConversationTracker(
            api_key=valid_api_key,
            token_handler=TokenHandlerType.LLAMAINDEX
        )
        
        assert tracker.config.token_handler == TokenHandlerType.LLAMAINDEX
    
    def test_token_handler_from_kwargs_string_value(self, valid_api_key):
        """Test that token handler can be set via kwargs with string value."""
        tracker = ConversationTracker(
            api_key=valid_api_key,
            token_handler=TokenHandlerType.LLAMAINDEX.value
        )
        
        # Config should normalize string to enum
        assert tracker.config.token_handler == TokenHandlerType.LLAMAINDEX
    
    def test_token_handler_from_config_object(self, valid_api_key):
        """Test that token handler can be set via Config object."""
        config = Config(
            api_key=valid_api_key,
            token_handler=TokenHandlerType.LLAMAINDEX
        )
        
        tracker = ConversationTracker(config=config)
        
        assert tracker.config.token_handler == TokenHandlerType.LLAMAINDEX
    
    @patch.dict('os.environ', {'AGENTSIGHT_TOKEN_HANDLER_TYPE': 'llamaindex'})
    def test_token_handler_from_env_variable(self, valid_api_key):
        """Test that token handler can be set via environment variable."""
        # Config should pick up from env var
        config = Config(api_key=valid_api_key)
        tracker = ConversationTracker(config=config)
        
        assert tracker.config.token_handler == TokenHandlerType.LLAMAINDEX
    
    def test_token_handler_with_different_log_levels(self, valid_api_key):
        """Test that token handler respects different log levels."""
        # Test with DEBUG
        tracker_debug = ConversationTracker(
            api_key=valid_api_key,
            token_handler=TokenHandlerType.LLAMAINDEX,
            log_level=LogLevel.DEBUG
        )
        assert tracker_debug.config.log_level == LogLevel.DEBUG
        assert tracker_debug.config.token_handler == TokenHandlerType.LLAMAINDEX
        
        # Test with INFO
        tracker_info = ConversationTracker(
            api_key=valid_api_key,
            token_handler=TokenHandlerType.LLAMAINDEX,
            log_level=LogLevel.INFO
        )
        assert tracker_info.config.log_level == LogLevel.INFO
        assert tracker_info.config.token_handler == TokenHandlerType.LLAMAINDEX
    
    def test_config_normalizes_string_token_handler(self, valid_api_key):
        """Test that Config.__post_init__ normalizes string to TokenHandlerType enum."""
        config = Config(
            api_key=valid_api_key,
            token_handler="llamaindex"
        )
        
        assert config.token_handler == TokenHandlerType.LLAMAINDEX
        assert isinstance(config.token_handler, TokenHandlerType)
    
    def test_config_normalizes_string_log_level(self, valid_api_key):
        """Test that Config.__post_init__ normalizes string log_level to LogLevel enum."""
        config = Config(
            api_key=valid_api_key,
            log_level="DEBUG"
        )
        
        assert config.log_level == LogLevel.DEBUG
        assert isinstance(config.log_level, LogLevel)
    
    def test_set_llamaindex_token_handler_import_error(self):
        """Test that ImportError is handled gracefully when llama-index not installed."""
        with patch.dict('sys.modules', {'llama_index.core': None}):
            from agentsight.token_handlers import set_llamaindex_token_handler
            result = set_llamaindex_token_handler(LogLevel.INFO)
            assert result is None
    
    def test_track_token_usage_initializes_token_handler(self, tracker):
        """Test that tracking tokens initializes the token handler."""
        assert tracker._token_handler is None
        
        tracker.track_token_usage(prompt_tokens=10)
        
        assert tracker._token_handler is not None
    
    def test_track_token_usage_accumulates_tokens(self, tracker):
        """Test that token counts are accumulated correctly."""
        tracker.track_token_usage(
            prompt_tokens=50,
            completion_tokens=30,
            total_tokens=80,
            embedding_tokens=10
        )
        
        tracker.track_token_usage(
            prompt_tokens=25,
            completion_tokens=15,
            total_tokens=40,
            embedding_tokens=5
        )
        
        usage = tracker.get_token_usage()
        assert usage["prompt_tokens"] == 75
        assert usage["completion_tokens"] == 45
        assert usage["total_tokens"] == 120
        assert usage["embedding_tokens"] == 15
    
    def test_track_token_usage_with_defaults(self, tracker):
        """Test tracking tokens with default values (0)."""
        tracker.track_token_usage()
        
        usage = tracker.get_token_usage()
        assert usage["prompt_tokens"] == 0
        assert usage["completion_tokens"] == 0
        assert usage["total_tokens"] == 0
        assert usage["embedding_tokens"] == 0
    
    def test_track_token_usage_partial_values(self, tracker):
        """Test tracking only some token types."""
        tracker.track_token_usage(prompt_tokens=100)
        
        usage = tracker.get_token_usage()
        assert usage["prompt_tokens"] == 100
        assert usage["completion_tokens"] == 0
        assert usage["total_tokens"] == 0
        assert usage["embedding_tokens"] == 0
    
    def test_get_token_usage_returns_empty_dict_when_no_handler(self, tracker):
        """Test that get_token_usage returns empty dict when handler is None."""
        assert tracker._token_handler is None
        
        usage = tracker.get_token_usage()
        
        assert usage == {}
    
    def test_get_token_usage_returns_current_counts(self, tracker):
        """Test that get_token_usage returns current token counts."""
        tracker.track_token_usage(
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150,
            embedding_tokens=20
        )
        
        usage = tracker.get_token_usage()
        
        assert usage == {
            "prompt_tokens": 100,
            "completion_tokens": 50,
            "total_tokens": 150,
            "embedding_tokens": 20
        }

    
    @patch('agentsight.helpers.get_iso_timestamp')
    def test_add_token_usage_inserts_before_last_item(self, mock_timestamp, tracker):
        """Test that _add_token_usage inserts before last item."""
        mock_timestamp.return_value = "2024-01-01T12:00:00.000Z"
        
        conv_id = "conv_123"
        tracker.get_or_create_conversation(conv_id)
        
        # Add some items
        tracker._tracked_data[conv_id] = {
            "items": [
                {"type": "question", "data": {"content": "test"}},
                {"type": "answer", "data": {"content": "response"}}
            ]
        }
        
        # Track some token usage
        tracker.track_token_usage(
            prompt_tokens=50,
            completion_tokens=30,
            total_tokens=80,
            embedding_tokens=10
        )
        
        tracker._add_token_usage(conv_id)
        
        items = tracker._tracked_data[conv_id]["items"]
        
        # Should have 3 items now
        assert len(items) == 3
        
        # Token usage should be inserted at index 1 (before last item)
        token_item = items[1]
        assert token_item["type"] == "action"
        assert token_item["data"]["action_name"] == "token_usage"
        assert token_item["data"]["conversation_id"] == conv_id
        assert token_item["data"]["metadata"] == {
            "prompt_tokens": 50,
            "completion_tokens": 30,
            "total_tokens": 80,
            "embedding_tokens": 10
        }
        
        # Last item should still be the answer
        assert items[2]["type"] == "answer"
        assert items[2]["data"]["content"] == "response"
        
        # First item should still be the question
        assert items[0]["type"] == "question"
        assert items[0]["data"]["content"] == "test"
    
    @patch('agentsight.helpers.get_iso_timestamp')
    def test_add_token_usage_appends_with_single_item(self, mock_timestamp, tracker):
        """Test that _add_token_usage appends when there's only one item."""
        mock_timestamp.return_value = "2024-01-01T12:00:00.000Z"
        
        conv_id = "conv_456"
        tracker.get_or_create_conversation(conv_id)
        
        tracker._tracked_data[conv_id] = {
            "items": [
                {"type": "question", "data": {"content": "test"}}
            ]
        }
        
        tracker.track_token_usage(total_tokens=100)
        tracker._add_token_usage(conv_id)
        
        items = tracker._tracked_data[conv_id]["items"]
        assert len(items) == 2
        
        # Token usage should be appended at the end
        assert items[1]["type"] == "action"
        assert items[1]["data"]["action_name"] == "token_usage"
        assert items[1]["data"]["metadata"]["total_tokens"] == 100
    
    @patch('agentsight.helpers.get_iso_timestamp')
    def test_add_token_usage_appends_with_no_items(self, mock_timestamp, tracker):
        """Test that _add_token_usage appends when there are no items."""
        mock_timestamp.return_value = "2024-01-01T12:00:00.000Z"
        
        conv_id = "conv_789"
        tracker.get_or_create_conversation(conv_id)
        
        tracker._tracked_data[conv_id] = {"items": []}
        
        tracker.track_token_usage(total_tokens=50)
        tracker._add_token_usage(conv_id)
        
        items = tracker._tracked_data[conv_id]["items"]
        assert len(items) == 1
        assert items[0]["type"] == "action"
        assert items[0]["data"]["action_name"] == "token_usage"
    
    @patch('agentsight.helpers.get_iso_timestamp')
    def test_add_token_usage_with_no_token_handler(self, mock_timestamp, tracker):
        """Test _add_token_usage when no tokens have been tracked."""
        mock_timestamp.return_value = "2024-01-01T12:00:00.000Z"
        
        conv_id = "conv_no_tokens"
        tracker.get_or_create_conversation(conv_id)
        
        tracker._tracked_data[conv_id] = {
            "items": [
                {"type": "question", "data": {"content": "test"}},
                {"type": "answer", "data": {"content": "response"}}
            ]
        }
        
        # Don't track any tokens
        assert tracker._token_handler is None
        
        tracker._add_token_usage(conv_id)
        
        items = tracker._tracked_data[conv_id]["items"]
        
        # Token usage should still be added with empty dict
        assert len(items) == 3
        assert items[1]["type"] == "action"
        assert items[1]["data"]["action_name"] == "token_usage"
        assert items[1]["data"]["metadata"] == {}
