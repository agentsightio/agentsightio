import pytest
from unittest.mock import patch, MagicMock
from agentsight.exceptions import NoApiKeyException, InvalidApiKeyException
from agentsight.client import ConversationTracker
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
    
    def test_singleton_pattern_returns_same_instance(self, valid_api_key):
        """Test that singleton pattern returns the same instance."""
        # Reset singleton for this test
        ConversationTracker._instance = None
        ConversationTracker._instance_lock = __import__('threading').Lock()
        
        tracker1 = ConversationTracker(api_key=valid_api_key)
        tracker2 = ConversationTracker(api_key=valid_api_key)
        
        # Should be the same instance
        assert tracker1 is tracker2
        assert id(tracker1) == id(tracker2)
    
    def test_singleton_reinitialization_prevented(self, valid_api_key):
        """Test that singleton prevents re-initialization."""
        # Reset singleton for this test
        ConversationTracker._instance = None
        ConversationTracker._instance_lock = __import__('threading').Lock()
        
        tracker1 = ConversationTracker(api_key=valid_api_key, conversation_id="conv1")
        tracker2 = ConversationTracker(api_key=valid_api_key, conversation_id="conv2")
        
        # Both should be the same instance
        assert tracker1 is tracker2
        # conversation_id from first initialization should be preserved
        assert tracker1.config.conversation_id == "conv1"
        assert tracker2.config.conversation_id == "conv1"
    
    def test_auto_initialized_instance_with_env_api_key(self, monkeypatch, valid_api_key):
        """Test that auto-initialized conversation_tracker works with API key from env."""
        # Reset singleton
        ConversationTracker._instance = None
        ConversationTracker._instance_lock = __import__('threading').Lock()
        
        # Set API key in environment
        monkeypatch.setenv("AGENTSIGHT_API_KEY", valid_api_key)
        
        # Import to trigger auto-initialization
        from agentsight.client.main_client import conversation_tracker
        
        # Should be initialized successfully
        assert conversation_tracker is not None
        assert conversation_tracker.config.api_key == valid_api_key
        assert conversation_tracker._initialized is True
    
    def test_initialization_without_api_key_raises_exception(self, monkeypatch):
        """Test that creating tracker without API key raises exception."""
        # Reset singleton
        ConversationTracker._instance = None
        ConversationTracker._instance_lock = __import__('threading').Lock()
        
        # Ensure no API key in environment
        monkeypatch.delenv("AGENTSIGHT_API_KEY", raising=False)
        
        # Creating instance should raise NoApiKeyException
        with pytest.raises(NoApiKeyException):
            ConversationTracker()

    def test_configure_without_api_key_raises_exception(self, valid_api_key):
        """Test that reconfiguration with None API key raises exception."""
        tracker = ConversationTracker(api_key=valid_api_key)
        
        with pytest.raises(NoApiKeyException, match="API key cannot be None"):
            tracker.configure(api_key=None)

    def test_configure_updates_conversation_id(self, valid_api_key):
        """Test that configure can update conversation_id."""
        tracker = ConversationTracker(
            api_key=valid_api_key,
            conversation_id="conv-123"
        )
        
        assert tracker.config.conversation_id == "conv-123"
        
        # Update conversation_id
        tracker.configure(conversation_id="conv-456")
        
        assert tracker.config.conversation_id == "conv-456"
        # API key should remain unchanged
        assert tracker.config.api_key == valid_api_key

    def test_configure_without_params_keeps_existing_config(self, valid_api_key):
        """Test that configure without params doesn't change existing config."""
        tracker = ConversationTracker(
            api_key=valid_api_key,
            conversation_id="conv-123",
            endpoint="https://test.agentsight.io"
        )
        
        original_api_key = tracker.config.api_key
        original_conv_id = tracker.config.conversation_id
        original_endpoint = tracker.config.endpoint
        
        # Call configure without params
        tracker.configure()
        
        # All should remain the same
        assert tracker.config.api_key == original_api_key
        assert tracker.config.conversation_id == original_conv_id
        assert tracker.config.endpoint == original_endpoint

    def test_configure_updates_only_specified_params(self, valid_api_key):
        """Test that configure only updates specified parameters."""
        tracker = ConversationTracker(
            api_key=valid_api_key,
            conversation_id="conv-123",
            endpoint="https://test.agentsight.io"
        )
        
        # Update only conversation_id
        tracker.configure(conversation_id="conv-new")
        
        assert tracker.config.conversation_id == "conv-new"
        # Others should remain unchanged
        assert tracker.config.api_key == valid_api_key
        assert tracker.config.endpoint == "https://test.agentsight.io"

    def test_singleton_returns_same_instance(self, valid_api_key):
        """Test that multiple instantiations return the same singleton instance."""
        tracker1 = ConversationTracker(api_key=valid_api_key, conversation_id="conv1")
        tracker2 = ConversationTracker(api_key=valid_api_key, conversation_id="conv2")
        
        # Should be the same instance (singleton behavior)
        assert tracker1 is tracker2
        assert id(tracker1) == id(tracker2)
        
        # Should keep the first configuration (singleton ignores new params)
        assert tracker1.config.conversation_id == "conv1"
        assert tracker2.config.conversation_id == "conv1"
        
        # Should share everything (because they're the same object)
        assert tracker1._tracked_data is tracker2._tracked_data
        assert tracker1._lock is tracker2._lock
        assert tracker1._http_client is tracker2._http_client

    def test_singleton_uses_first_initialization_params(self, valid_api_key):
        """Test that singleton uses parameters from first initialization only."""
        # First initialization with conv1
        tracker1 = ConversationTracker(api_key=valid_api_key, conversation_id="conv1")
        
        # Second "initialization" with conv2 - should be ignored
        tracker2 = ConversationTracker(api_key="different_key", conversation_id="conv2")
        
        # Same instance
        assert tracker1 is tracker2
        
        # Uses first initialization values
        assert tracker2.config.api_key == valid_api_key
        assert tracker2.config.conversation_id == "conv1"

    def test_singleton_can_be_reconfigured_via_configure(self, valid_api_key):
        """Test that singleton can be reconfigured using configure() method."""
        tracker = ConversationTracker(api_key=valid_api_key, conversation_id="conv1")
        
        assert tracker.config.conversation_id == "conv1"
        
        # Reconfigure the singleton (this is the correct way to change config)
        tracker.configure(conversation_id="conv2")
        
        assert tracker.config.conversation_id == "conv2"
        
        # Any reference to the tracker will have the updated config
        tracker_ref = ConversationTracker()
        assert tracker_ref is tracker
        assert tracker_ref.config.conversation_id == "conv2"

    def test_auto_initialized_instance_with_env_api_key(self, monkeypatch, valid_api_key):
        """Test that auto-initialized tracker works with API key from env."""
        from agentsight.client.main_client import ConversationTracker
        from threading import Lock
        
        # MUST reset singleton before this test
        ConversationTracker._instance = None
        ConversationTracker._instance_lock = Lock()
        
        # Set API key in environment
        monkeypatch.setenv("AGENTSIGHT_API_KEY", valid_api_key)
        
        # Create instance (will read from env via Config)
        tracker = ConversationTracker()
        
        # Should be initialized successfully with env API key
        assert tracker is not None
        assert tracker.config.api_key == valid_api_key
        assert tracker._initialized is True

    def test_module_level_tracker_is_singleton(self, valid_api_key):
        """Test that module-level tracker instance follows singleton pattern."""
        from agentsight.client.main_client import ConversationTracker
        from threading import Lock
        
        # Reset singleton
        ConversationTracker._instance = None
        ConversationTracker._instance_lock = Lock()
        
        # Create an instance
        tracker1 = ConversationTracker(api_key=valid_api_key)
        
        # Create another "instance"
        tracker2 = ConversationTracker()
        
        # Should be the same
        assert tracker1 is tracker2

    def test_cannot_create_multiple_independent_instances(self, valid_api_key):
        """Test that it's impossible to create independent instances."""
        tracker1 = ConversationTracker(
            api_key=valid_api_key,
            conversation_id="conv1",
            endpoint="https://endpoint1.com"
        )
        
        tracker2 = ConversationTracker(
            api_key="different_key",
            conversation_id="conv2",
            endpoint="https://endpoint2.com"
        )
        
        # Must be the same instance
        assert tracker1 is tracker2
        
        # Second initialization is completely ignored
        assert tracker1.config.api_key == valid_api_key
        assert tracker1.config.conversation_id == "conv1"
        assert tracker1.config.endpoint == "https://endpoint1.com"
        
        # To change config, must use configure()
        tracker1.configure(conversation_id="conv2")
        assert tracker2.config.conversation_id == "conv2"
