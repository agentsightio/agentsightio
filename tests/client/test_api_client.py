import pytest
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime
from agentsight.client.api_client import AgentSightAPI, agentsight_api
from agentsight.exceptions import (
    NoApiKeyException,
    ConversationApiException,
    NotFoundException,
    UnauthorizedException,
    ForbiddenException
)
from agentsight.config import Config


class TestAgentSightAPIInitialization:
    """Test cases for AgentSightAPI initialization."""
    
    def test_init_with_api_key(self, valid_api_key):
        """Test initialization with API key."""
        api = AgentSightAPI(api_key=valid_api_key)
        assert api.config.api_key == valid_api_key
        assert api._http_client is not None
        assert api._initialized is True
    
    def test_init_with_config_object(self, test_config):
        """Test initialization with Config object."""
        api = AgentSightAPI(config=test_config)
        assert api.config.api_key == test_config.api_key
        assert api.config.endpoint == test_config.endpoint
    
    def test_init_with_all_parameters(self, valid_api_key):
        """Test initialization with all parameters."""
        api = AgentSightAPI(
            api_key=valid_api_key,
            endpoint="https://test.example.com"
        )
        
        assert api.config.api_key == valid_api_key
        assert api.config.endpoint == "https://test.example.com"
    
    def test_init_without_api_key_raises_exception(self):
        """Test that initialization without API key raises NoApiKeyException."""
        with pytest.raises(NoApiKeyException):
            AgentSightAPI()
    
    def test_init_with_empty_api_key_raises_exception(self):
        """Test that initialization with empty API key raises NoApiKeyException."""
        with pytest.raises(NoApiKeyException):
            AgentSightAPI(api_key="")
    
    def test_init_with_none_api_key_raises_exception(self):
        """Test that initialization with None API key raises NoApiKeyException."""
        with pytest.raises(NoApiKeyException):
            AgentSightAPI(api_key=None)
    
    def test_http_client_initialization(self, valid_api_key):
        """Test that HTTPClient is initialized correctly."""
        api = AgentSightAPI(api_key=valid_api_key)
        
        assert hasattr(api, '_http_client')
        assert api._http_client is not None
        assert api._http_client.config == api.config
    
    def test_init_default_endpoint(self, valid_api_key):
        """Test that default endpoint is set correctly."""
        api = AgentSightAPI(api_key=valid_api_key)
        
        assert api.config.endpoint == "https://api.agentsight.io"
    
    def test_init_with_custom_endpoint(self, valid_api_key):
        """Test initialization with custom endpoint."""
        api = AgentSightAPI(
            api_key=valid_api_key,
            endpoint="https://custom.api.com"
        )
        
        assert api.config.endpoint == "https://custom.api.com"
    
    def test_init_with_none_config_creates_new_config(self, valid_api_key):
        """Test that None config creates new Config instance."""
        api = AgentSightAPI(api_key=valid_api_key, config=None)
        
        assert api.config is not None
        assert isinstance(api.config, Config)
        assert api.config.api_key == valid_api_key
    
    def test_singleton_pattern_returns_same_instance(self, valid_api_key):
        """Test that singleton pattern returns the same instance."""
        # Reset singleton for AgentSightAPI
        from threading import Lock
        AgentSightAPI._instance = None
        AgentSightAPI._instance_lock = Lock()
        
        api1 = AgentSightAPI(api_key=valid_api_key)
        api2 = AgentSightAPI(api_key=valid_api_key)
        
        # Should be the same instance
        assert api1 is api2
        assert id(api1) == id(api2)
    
    def test_singleton_reinitialization_prevented(self, valid_api_key):
        """Test that singleton prevents re-initialization."""
        # Reset singleton for AgentSightAPI
        from threading import Lock
        AgentSightAPI._instance = None
        AgentSightAPI._instance_lock = Lock()
        
        api1 = AgentSightAPI(api_key=valid_api_key, endpoint="https://first.com")
        api2 = AgentSightAPI(api_key=valid_api_key, endpoint="https://second.com")
        
        # Both should be the same instance
        assert api1 is api2
        # Endpoint from first initialization should be preserved
        assert api1.config.endpoint == "https://first.com"
        assert api2.config.endpoint == "https://first.com"


class TestAgentSightAPIConfigure:
    """Test cases for AgentSightAPI configure method."""
    
    def test_configure_with_new_api_key(self, valid_api_key):
        """Test reconfiguration with new API key."""
        api = AgentSightAPI(api_key=valid_api_key)
        new_api_key = "ags_22222222222222222222222222222222_222222"
        
        api.configure(api_key=new_api_key)
        
        assert api.config.api_key == new_api_key
        assert api._http_client.config.api_key == new_api_key
    
    def test_configure_with_new_endpoint(self, valid_api_key):
        """Test reconfiguration with new endpoint."""
        api = AgentSightAPI(api_key=valid_api_key)
        new_endpoint = "https://new.endpoint.com"
        
        api.configure(endpoint=new_endpoint)
        
        assert api.config.endpoint == new_endpoint
        assert api._http_client.config.endpoint == new_endpoint
    
    def test_configure_without_api_key_raises_exception(self, valid_api_key):
        """Test that reconfiguration with None API key raises exception."""
        api = AgentSightAPI(api_key=valid_api_key)
        
        with pytest.raises(NoApiKeyException, match="API key cannot be None"):
            api.configure(api_key=None)
    
    def test_configure_with_empty_api_key_raises_exception(self, valid_api_key):
        """Test that reconfiguration with empty API key raises exception."""
        api = AgentSightAPI(api_key=valid_api_key)
        
        with pytest.raises(NoApiKeyException):
            api.configure(api_key="")


class TestAgentSightAPIFetchConversations:
    """Test cases for fetch_conversations method."""
    
    def test_fetch_conversations_no_filters(self, valid_api_key):
        """Test fetching conversations with no filters."""
        api = AgentSightAPI(api_key=valid_api_key)
        api._http_client = Mock()
        
        expected_response = {
            "count": 2,
            "next": None,
            "previous": None,
            "results": [
                {"id": 1, "conversation_id": "conv1"},
                {"id": 2, "conversation_id": "conv2"}
            ]
        }
        api._http_client.get.return_value = expected_response
        
        result = api.fetch_conversations()
        
        assert result == expected_response
        api._http_client.get.assert_called_once_with(
            '/api/conversations/',
            params={}
        )
    
    def test_fetch_conversations_with_conversation_id_filter(self, valid_api_key):
        """Test fetching conversations with conversation_id filter."""
        api = AgentSightAPI(api_key=valid_api_key)
        api._http_client = Mock()
        
        expected_response = {
            "count": 1,
            "results": [{"id": 1, "conversation_id": "conv1"}]
        }
        api._http_client.get.return_value = expected_response
        
        result = api.fetch_conversations(conversation_id="conv1")
        
        assert result == expected_response
        api._http_client.get.assert_called_once_with(
            '/api/conversations/',
            params={'conversation_id': 'conv1'}
        )
    
    def test_fetch_conversations_with_multiple_filters(self, valid_api_key):
        """Test fetching conversations with multiple filters."""
        api = AgentSightAPI(api_key=valid_api_key)
        api._http_client = Mock()
        
        expected_response = {"count": 1, "results": []}
        api._http_client.get.return_value = expected_response
        
        result = api.fetch_conversations(
            customer_id="customer123",
            device="mobile",
            language="en",
            has_messages=True
        )
        
        assert result == expected_response
        api._http_client.get.assert_called_once_with(
            '/api/conversations/',
            params={
                'customer_id': 'customer123',
                'device': 'mobile',
                'language': 'en',
                'has_messages': 'true'
            }
        )
    
    def test_fetch_conversations_with_pagination(self, valid_api_key):
        """Test fetching conversations with pagination."""
        api = AgentSightAPI(api_key=valid_api_key)
        api._http_client = Mock()
        
        expected_response = {"count": 100, "results": []}
        api._http_client.get.return_value = expected_response
        
        result = api.fetch_conversations(page=2, page_size=20)
        
        assert result == expected_response
        api._http_client.get.assert_called_once_with(
            '/api/conversations/',
            params={'page': 2, 'page_size': 20}
        )
    
    def test_fetch_conversations_with_datetime_string(self, valid_api_key):
        """Test fetching conversations with datetime as string."""
        api = AgentSightAPI(api_key=valid_api_key)
        api._http_client = Mock()
        
        expected_response = {"count": 0, "results": []}
        api._http_client.get.return_value = expected_response
        
        result = api.fetch_conversations(
            started_at_after="2024-01-01T00:00:00Z",
            started_at_before="2024-12-31T23:59:59Z"
        )
        
        assert result == expected_response
        api._http_client.get.assert_called_once_with(
            '/api/conversations/',
            params={
                'started_at_after': '2024-01-01T00:00:00Z',
                'started_at_before': '2024-12-31T23:59:59Z'
            }
        )
    
    def test_fetch_conversations_with_datetime_object(self, valid_api_key):
        """Test fetching conversations with datetime object."""
        api = AgentSightAPI(api_key=valid_api_key)
        api._http_client = Mock()
        
        expected_response = {"count": 0, "results": []}
        api._http_client.get.return_value = expected_response
        
        dt_after = datetime(2024, 1, 1, 0, 0, 0)
        dt_before = datetime(2024, 12, 31, 23, 59, 59)
        
        result = api.fetch_conversations(
            started_at_after=dt_after,
            started_at_before=dt_before
        )
        
        assert result == expected_response
        call_args = api._http_client.get.call_args
        assert call_args[0][0] == '/api/conversations/'
        params = call_args[1]['params']
        assert 'started_at_after' in params
        assert 'started_at_before' in params
        # Check that datetime was converted to ISO format
        assert '2024-01-01' in params['started_at_after']
        assert '2024-12-31' in params['started_at_before']
    
    def test_fetch_conversations_with_all_filters(self, valid_api_key):
        """Test fetching conversations with all possible filters."""
        api = AgentSightAPI(api_key=valid_api_key)
        api._http_client = Mock()
        
        expected_response = {"count": 0, "results": []}
        api._http_client.get.return_value = expected_response
        
        result = api.fetch_conversations(
            action_name="test_action",
            conversation_id="conv1",
            customer_id="customer1",
            customer_ip_address="192.168.1.1",
            device="desktop",
            has_messages=False,
            language="es",
            message_contains="test",
            page=1,
            page_size=10,
            started_at_after="2024-01-01T00:00:00Z",
            started_at_before="2024-12-31T23:59:59Z"
        )
        
        assert result == expected_response
        call_args = api._http_client.get.call_args
        params = call_args[1]['params']
        assert params['action_name'] == 'test_action'
        assert params['conversation_id'] == 'conv1'
        assert params['customer_id'] == 'customer1'
        assert params['customer_ip_address'] == '192.168.1.1'
        assert params['device'] == 'desktop'
        assert params['has_messages'] == 'false'
        assert params['language'] == 'es'
        assert params['message_contains'] == 'test'
        assert params['page'] == 1
        assert params['page_size'] == 10
    
    def test_fetch_conversations_handles_http_error(self, valid_api_key):
        """Test that fetch_conversations handles HTTP errors."""
        api = AgentSightAPI(api_key=valid_api_key)
        api._http_client = Mock()
        
        api._http_client.get.side_effect = ConversationApiException(
            "API error",
            status_code=500
        )
        
        with pytest.raises(ConversationApiException):
            api.fetch_conversations()
    
    def test_fetch_conversations_handles_not_found(self, valid_api_key):
        """Test that fetch_conversations handles NotFoundException."""
        api = AgentSightAPI(api_key=valid_api_key)
        api._http_client = Mock()
        
        api._http_client.get.side_effect = NotFoundException("Not found")
        
        with pytest.raises(NotFoundException):
            api.fetch_conversations()


class TestAgentSightAPIFetchConversation:
    """Test cases for fetch_conversation method."""
    
    def test_fetch_conversation_success(self, valid_api_key):
        """Test successfully fetching a single conversation."""
        api = AgentSightAPI(api_key=valid_api_key)
        api._http_client = Mock()
        
        expected_response = {
            "id": 123,
            "conversation_id": "conv1",
            "messages": []
        }
        api._http_client.get.return_value = expected_response
        
        result = api.fetch_conversation(123)
        
        assert result == expected_response
        api._http_client.get.assert_called_once_with(
            '/api/conversations/123/'
        )
    
    def test_fetch_conversation_with_different_id(self, valid_api_key):
        """Test fetching conversation with different ID."""
        api = AgentSightAPI(api_key=valid_api_key)
        api._http_client = Mock()
        
        expected_response = {"id": 456, "conversation_id": "conv2"}
        api._http_client.get.return_value = expected_response
        
        result = api.fetch_conversation(456)
        
        assert result == expected_response
        api._http_client.get.assert_called_once_with(
            '/api/conversations/456/'
        )
    
    def test_fetch_conversation_handles_not_found(self, valid_api_key):
        """Test that fetch_conversation handles NotFoundException."""
        api = AgentSightAPI(api_key=valid_api_key)
        api._http_client = Mock()
        
        api._http_client.get.side_effect = NotFoundException("Conversation not found")
        
        with pytest.raises(NotFoundException) as exc_info:
            api.fetch_conversation(999)
        
        assert "Conversation not found" in str(exc_info.value)
    
    def test_fetch_conversation_handles_unauthorized(self, valid_api_key):
        """Test that fetch_conversation handles UnauthorizedException."""
        api = AgentSightAPI(api_key=valid_api_key)
        api._http_client = Mock()
        
        api._http_client.get.side_effect = UnauthorizedException("Unauthorized")
        
        with pytest.raises(UnauthorizedException):
            api.fetch_conversation(123)
    
    def test_fetch_conversation_handles_forbidden(self, valid_api_key):
        """Test that fetch_conversation handles ForbiddenException."""
        api = AgentSightAPI(api_key=valid_api_key)
        api._http_client = Mock()
        
        api._http_client.get.side_effect = ForbiddenException("Forbidden")
        
        with pytest.raises(ForbiddenException):
            api.fetch_conversation(123)


class TestAgentSightAPIFetchConversationAttachments:
    """Test cases for fetch_conversation_attachments method."""
    
    def test_fetch_conversation_attachments_success(self, valid_api_key):
        """Test successfully fetching conversation attachments."""
        api = AgentSightAPI(api_key=valid_api_key)
        api._http_client = Mock()
        
        expected_response = {
            "conversation_id": 123,
            "messages": [
                {
                    "id": 1,
                    "attachments": [
                        {"filename": "file1.pdf", "mime_type": "application/pdf"}
                    ]
                }
            ]
        }
        api._http_client.get.return_value = expected_response
        
        result = api.fetch_conversation_attachments(123)
        
        assert result == expected_response
        api._http_client.get.assert_called_once_with(
            '/api/conversations/123/attachments/'
        )
    
    def test_fetch_conversation_attachments_empty(self, valid_api_key):
        """Test fetching attachments when conversation has no attachments."""
        api = AgentSightAPI(api_key=valid_api_key)
        api._http_client = Mock()
        
        expected_response = {
            "conversation_id": 123,
            "messages": []
        }
        api._http_client.get.return_value = expected_response
        
        result = api.fetch_conversation_attachments(123)
        
        assert result == expected_response
    
    def test_fetch_conversation_attachments_handles_not_found(self, valid_api_key):
        """Test that fetch_conversation_attachments handles NotFoundException."""
        api = AgentSightAPI(api_key=valid_api_key)
        api._http_client = Mock()
        
        api._http_client.get.side_effect = NotFoundException("Conversation not found")
        
        with pytest.raises(NotFoundException):
            api.fetch_conversation_attachments(999)
    
    def test_fetch_conversation_attachments_handles_api_error(self, valid_api_key):
        """Test that fetch_conversation_attachments handles API errors."""
        api = AgentSightAPI(api_key=valid_api_key)
        api._http_client = Mock()
        
        api._http_client.get.side_effect = ConversationApiException(
            "API error",
            status_code=500
        )
        
        with pytest.raises(ConversationApiException):
            api.fetch_conversation_attachments(123)


class TestAgentSightAPIFormatDateTime:
    """Test cases for _format_datetime helper method."""
    
    def test_format_datetime_with_datetime_object(self, valid_api_key):
        """Test _format_datetime with datetime object."""
        api = AgentSightAPI(api_key=valid_api_key)
        
        dt = datetime(2024, 1, 15, 14, 30, 45)
        result = api._format_datetime(dt)
        
        assert isinstance(result, str)
        assert "2024-01-15" in result
        assert "14:30:45" in result
    
    def test_format_datetime_with_string(self, valid_api_key):
        """Test _format_datetime with string (should return as-is)."""
        api = AgentSightAPI(api_key=valid_api_key)
        
        dt_string = "2024-01-15T14:30:45Z"
        result = api._format_datetime(dt_string)
        
        assert result == dt_string
        assert isinstance(result, str)
    
    def test_format_datetime_with_iso_string(self, valid_api_key):
        """Test _format_datetime with ISO format string."""
        api = AgentSightAPI(api_key=valid_api_key)
        
        dt_string = "2024-12-31T23:59:59.999999"
        result = api._format_datetime(dt_string)
        
        assert result == dt_string


class TestAgentSightAPIAutoInitialized:
    """Test cases for auto-initialized agentsight_api instance."""
    
    def test_auto_initialized_instance_with_env_api_key(self, monkeypatch, valid_api_key):
        """Test that auto-initialized agentsight_api works with API key from env."""
        # Reset singleton
        from threading import Lock
        import importlib
        AgentSightAPI._instance = None
        AgentSightAPI._instance_lock = Lock()
        
        # Set API key in environment
        monkeypatch.setenv("AGENTSIGHT_API_KEY", valid_api_key)
        
        # Reload module to trigger auto-initialization
        import agentsight.client.api_client
        importlib.reload(agentsight.client.api_client)
        
        # Get the auto-initialized instance
        auto_api = agentsight.client.api_client.agentsight_api
        
        # Should be initialized successfully
        assert auto_api is not None
        assert auto_api.config.api_key == valid_api_key
        assert auto_api._initialized is True
    
    def test_auto_initialized_instance_without_api_key_raises_exception(self, monkeypatch):
        """Test that auto-initialized agentsight_api raises exception without API key."""
        # Reset singleton
        from threading import Lock
        import importlib
        AgentSightAPI._instance = None
        AgentSightAPI._instance_lock = Lock()
        
        # Ensure no API key in environment
        monkeypatch.delenv("AGENTSIGHT_API_KEY", raising=False)
        
        # Reload module - this should raise NoApiKeyException
        import agentsight.client.api_client
        with pytest.raises(NoApiKeyException):
            importlib.reload(agentsight.client.api_client)
    
    def test_multiple_instances_return_same_singleton(self, valid_api_key):
        """Test that creating multiple instances returns the same singleton."""
        # Create first instance
        api1 = AgentSightAPI(api_key=valid_api_key)
        
        # Create second instance (should return same instance due to singleton)
        api2 = AgentSightAPI(api_key="different_key")
        
        # Should be the same instance
        assert api1 is api2
        assert id(api1) == id(api2)
        
        # Should use the first API key
        assert api1.config.api_key == valid_api_key
