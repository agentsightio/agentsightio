import pytest
from unittest.mock import patch, MagicMock
from agentsight.client import ConversationTracker
from agentsight.exceptions import NoApiKeyException, InvalidApiKeyException
from agentsight.config import Config
from agentsight.enums import LogLevel, TokenHandlerType

class TestConversationTrackerInitialization:
    """Test cases for ConversationTracker initialization."""
    
    def test_init_with_api_key(self, valid_api_key):
        """Test initialization with API key."""
        tracker = ConversationTracker(api_key=valid_api_key)
        assert tracker.config.api_key == valid_api_key
        assert tracker._tracked_data == {}
        assert tracker._lock is not None
    
    def test_init_with_config_object(self, test_config):
        """Test initialization with Config object."""
        tracker = ConversationTracker(config=test_config)
        assert tracker.config.api_key == test_config.api_key
        assert tracker.config.endpoint == test_config.endpoint
    
    def test_init_with_all_parameters(self, valid_api_key):
        """Test initialization with all parameters."""
        tracker = ConversationTracker(
            api_key=valid_api_key,
            conversation_id="test-conv-id",
            endpoint="https://test.example.com",
            log_level=LogLevel.DEBUG
        )
        
        assert tracker.config.api_key == valid_api_key
        assert tracker.config.conversation_id == "test-conv-id"
        assert tracker.config.endpoint == "https://test.example.com"
        assert tracker.config.log_level == LogLevel.DEBUG
    
    def test_init_without_api_key_raises_exception(self):
        """Test that initialization without API key raises NoApiKeyException."""
        with pytest.raises(NoApiKeyException):
            ConversationTracker()
    
    def test_init_with_empty_api_key_raises_exception(self):
        """Test that initialization with empty API key raises NoApiKeyException."""
        with pytest.raises(NoApiKeyException):
            ConversationTracker(api_key="")
    
    def test_init_with_none_api_key_raises_exception(self):
        """Test that initialization with None API key raises NoApiKeyException."""
        with pytest.raises(NoApiKeyException):
            ConversationTracker(api_key=None)
    
    def test_http_client_initialization(self, valid_api_key):
        """Test that HTTPClient is initialized correctly."""
        tracker = ConversationTracker(api_key=valid_api_key)
        
        # Test that _http_client attribute exists and is properly initialized
        assert hasattr(tracker, '_http_client')
        assert tracker._http_client is not None
        
        # Test that the http client has the expected config
        assert tracker._http_client.config == tracker.config
    
    def test_init_with_string_log_level(self, valid_api_key):
        """Test initialization with string log level."""
        tracker = ConversationTracker(
            api_key=valid_api_key,
            log_level="DEBUG"
        )
        assert tracker.config.log_level == LogLevel.DEBUG  # Should be converted to enum
    
    def test_init_with_enum_log_level(self, valid_api_key):
        """Test initialization with enum log level."""
        tracker = ConversationTracker(
            api_key=valid_api_key,
            log_level=LogLevel.INFO
        )
        assert tracker.config.log_level == LogLevel.INFO
    
    def test_init_with_config_and_parameters_precedence(self, valid_api_key):
        """Test that individual parameters take precedence over config object."""
        config = Config()
        config.configure(
            api_key="ags_11111111111111111111111111111111_111111",
            conversation_id="config-conv-id",
            endpoint="https://config.example.com"
        )
        
        tracker = ConversationTracker(
            api_key=valid_api_key,
            conversation_id="param-conv-id",
            config=config
        )
        
        # Parameters should override config
        assert tracker.config.api_key == valid_api_key
        assert tracker.config.conversation_id == "param-conv-id"
        # Endpoint should come from config since not provided as parameter
        assert tracker.config.endpoint == "https://config.example.com"
    
    def test_init_with_kwargs_passed_to_config(self, valid_api_key):
        """Test initialization with additional kwargs passed to config."""
        # The configure method doesn't accept arbitrary kwargs, so we test the valid ones
        tracker = ConversationTracker(
            api_key=valid_api_key,
            app_url="https://custom.app.com",
            token_handler=TokenHandlerType.LLAMAINDEX
        )
        
        assert tracker.config.api_key == valid_api_key
        assert tracker.config.app_url == "https://custom.app.com"
        assert tracker.config.token_handler == TokenHandlerType.LLAMAINDEX
    
    def test_init_default_values(self, valid_api_key):
        """Test that default values are set correctly."""
        tracker = ConversationTracker(api_key=valid_api_key)
        
        # Test default values
        assert tracker.config.api_key == valid_api_key
        assert tracker.config.conversation_id is None
        assert tracker.config.endpoint is not None  # Should have default endpoint
        assert tracker.config.log_level is not None  # Should have default log level
    
    def test_init_creates_empty_tracked_data(self, valid_api_key):
        """Test that tracked data is initialized as empty dictionary."""
        tracker = ConversationTracker(api_key=valid_api_key)
        
        assert isinstance(tracker._tracked_data, dict)
        assert len(tracker._tracked_data) == 0
    
    def test_init_creates_lock_for_thread_safety(self, valid_api_key):
        """Test that lock is created for thread safety."""
        tracker = ConversationTracker(api_key=valid_api_key)
        
        assert hasattr(tracker, '_lock')
        assert tracker._lock is not None
        # Should be a threading.Lock instance
        from threading import Lock
        assert isinstance(tracker._lock, type(Lock()))
    
    def test_init_token_handler_defaults_to_none(self, valid_api_key):
        """Test that token handler defaults to None."""
        tracker = ConversationTracker(api_key=valid_api_key)
        
        assert tracker._token_handler is None
    
    def test_init_with_none_config_creates_new_config(self, valid_api_key):
        """Test that None config creates new Config instance."""
        tracker = ConversationTracker(api_key=valid_api_key, config=None)
        
        assert tracker.config is not None
        assert isinstance(tracker.config, Config)
        assert tracker.config.api_key == valid_api_key
    
    def test_init_with_whitespace_api_key_raises_exception(self):
        """Test that initialization with whitespace-only API key raises exception."""
        with pytest.raises(NoApiKeyException):
            ConversationTracker(api_key="   ")
    
    def test_init_with_conversation_id_only_raises_exception(self):
        """Test that providing only conversation_id without api_key raises exception."""
        with pytest.raises(NoApiKeyException):
            ConversationTracker(conversation_id="test-conv-id")
    
    def test_init_with_endpoint_only_raises_exception(self):
        """Test that providing only endpoint without api_key raises exception."""
        with pytest.raises(NoApiKeyException):
            ConversationTracker(endpoint="https://test.com")
    
    def test_init_patch_llm_clients_called(self, valid_api_key):
        """Test that _patch_llm_clients is called during initialization."""
        with patch.object(ConversationTracker, '_patch_llm_clients') as mock_patch:
            tracker = ConversationTracker(api_key=valid_api_key)
            mock_patch.assert_called_once()
    
    def test_init_multiple_instances_independent(self, valid_api_key):
        """Test that multiple instances are independent."""
        tracker1 = ConversationTracker(api_key=valid_api_key, conversation_id="conv1")
        tracker2 = ConversationTracker(api_key=valid_api_key, conversation_id="conv2")
        
        assert tracker1.config.conversation_id == "conv1"
        assert tracker2.config.conversation_id == "conv2"
        
        # Different instances should have different tracked data
        assert tracker1._tracked_data is not tracker2._tracked_data
        assert tracker1._lock is not tracker2._lock
        assert tracker1._http_client is not tracker2._http_client
    
    def test_init_with_whitespace_api_key_raises_exception(self):
        """Test that initialization with whitespace-only API key raises exception."""
        with pytest.raises(NoApiKeyException):
            ConversationTracker(api_key="   ")

    def test_init_with_invalid_api_key_format(self):
        """Test initialization with invalid API key format."""
        with pytest.raises(InvalidApiKeyException):
            ConversationTracker(api_key="invalid-key-format")

    def test_init_with_api_key_with_spaces(self):
        """Test initialization with API key containing spaces."""
        with pytest.raises(InvalidApiKeyException):
            ConversationTracker(api_key=" ags_1a2b3c4d5e6f7890abcdef1234567890_a1b2c3 ")

    def test_init_with_wrong_prefix(self):
        """Test initialization with wrong prefix."""
        with pytest.raises(InvalidApiKeyException):
            ConversationTracker(api_key="wrong_1a2b3c4d5e6f7890abcdef1234567890_a1b2c3")

    def test_init_with_wrong_hash_length(self):
        """Test initialization with wrong hash length."""
        with pytest.raises(InvalidApiKeyException):
            ConversationTracker(api_key="ags_1a2b3c4d5e6f7890abcdef123456789_a1b2c3")  # 31 chars instead of 32

    def test_init_with_wrong_checksum_length(self):
        """Test initialization with wrong checksum length."""
        with pytest.raises(InvalidApiKeyException):
            ConversationTracker(api_key="ags_1a2b3c4d5e6f7890abcdef1234567890_a1b2c34") 
    
    def test_init_numeric_values_in_strings(self, valid_api_key):
        """Test initialization with numeric values as strings."""
        tracker = ConversationTracker(
            api_key=valid_api_key,
            conversation_id="123456",
            endpoint="https://api.example.com"
        )
        
        assert tracker.config.api_key == valid_api_key
        assert tracker.config.conversation_id == "123456"
        assert tracker.config.endpoint == "https://api.example.com"
    
    def test_init_with_existing_config_object_precedence(self, valid_api_key):
        """Test that existing config object values are preserved when not overridden."""
        config = Config()
        config.configure(
            api_key="ags_11111111111111111111111111111111_111111",
            conversation_id="old-conv",
            endpoint="https://old.example.com",
            log_level=LogLevel.ERROR
        )
        
        # Pass config with some overrides
        tracker = ConversationTracker(
            api_key=valid_api_key,  # Override this
            conversation_id="new-conv",  # Override this
            config=config
            # endpoint and log_level should come from config
        )
        
        assert tracker.config.api_key == valid_api_key  # Overridden
        assert tracker.config.conversation_id == "new-conv"  # Overridden
        assert tracker.config.endpoint == "https://old.example.com"  # From config
        assert tracker.config.log_level == LogLevel.ERROR  # From config
    
    def test_init_with_config_none_creates_fresh_config(self, valid_api_key):
        """Test initialization with config=None creates a fresh Config instance."""
        tracker = ConversationTracker(
            api_key=valid_api_key,
            conversation_id="test-conv",
            config=None
        )
        
        assert isinstance(tracker.config, Config)
        assert tracker.config.api_key == valid_api_key
        assert tracker.config.conversation_id == "test-conv"
    
    def test_init_with_app_url_parameter(self, valid_api_key):
        """Test initialization with app_url parameter."""
        tracker = ConversationTracker(
            api_key=valid_api_key,
            app_url="https://custom.app.com"
        )
        
        assert tracker.config.app_url == "https://custom.app.com"
    
    def test_init_with_token_handler_string(self, valid_api_key):
        """Test initialization with token handler as string."""
        tracker = ConversationTracker(
            api_key=valid_api_key,
            token_handler="llamaindex"
        )
        
        assert tracker.config.token_handler == TokenHandlerType.LLAMAINDEX
    
    def test_init_with_token_handler_enum(self, valid_api_key):
        """Test initialization with token handler as enum."""
        tracker = ConversationTracker(
            api_key=valid_api_key,
            token_handler=TokenHandlerType.LLAMAINDEX
        )
        
        assert tracker.config.token_handler == TokenHandlerType.LLAMAINDEX
