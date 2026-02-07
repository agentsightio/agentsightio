import pytest
from unittest.mock import MagicMock
from threading import Lock
from agentsight.config import Config
from io import BytesIO
from agentsight.client import ConversationTracker
from unittest.mock import Mock

@pytest.fixture(autouse=True)
def isolated_env(monkeypatch):
    """
    A fixture that automatically runs for every test to ensure an
    isolated environment by removing specific environment variables.
    This ensures tests don't pick up values from .env files.
    """
    # Remove any environment variables that could interfere with tests
    # monkeypatch.delenv makes os.getenv() return None for these keys
    monkeypatch.delenv("AGENTSIGHT_TOKEN_HANDLER_TYPE", raising=False)
    monkeypatch.delenv("AGENTSIGHT_API_KEY", raising=False)
    monkeypatch.delenv("AGENTSIGHT_CONVERSATION_ID", raising=False)

@pytest.fixture
def valid_api_key():
    """Valid API key for testing."""
    return "ags_1a2b3c4d5e6f7890abcdef1234567890_a1b2c3"

@pytest.fixture
def test_config(valid_api_key):
    """Test configuration object."""
    config = Config()
    config.configure(
        api_key=valid_api_key,
        endpoint="https://test.agentsight.io"
    )
    return config

@pytest.fixture
def mock_successful_response():
    """Mock successful HTTP response."""
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {"status": "success", "message": "Saved successfully"}
    response.content = b'{"status": "success", "message": "Saved successfully"}'
    return response

@pytest.fixture
def mock_error_response():
    """Mock error HTTP response."""
    response = MagicMock()
    response.status_code = 400
    response.json.return_value = {"error": "Bad Request", "message": "Invalid data"}
    return response

@pytest.fixture
def valid_conversation_data():
    """Fixture providing valid conversation data."""
    return {
        "conversation": "conv_123",
        "content": "Hello world"
    }

@pytest.fixture
def valid_action_data():
    """Fixture providing valid action data."""
    return {
        "conversation": "conv_123",
        "action_name": "calculate"
    }

@pytest.fixture
def valid_button_data():
    """Fixture providing valid button data."""
    return {
        "conversation": "conv_123",
        "button_event": "click",
        "label": "Submit",
        "value": "submit_form"
    }

@pytest.fixture
def sample_attachment():
    """Fixture providing a sample attachment."""
    return {
        'filename': 'sample.txt',
        'mime_type': 'text/plain',
        'data': BytesIO(b"sample content")
    }

@pytest.fixture
def multiple_attachments():
    """Fixture providing multiple attachments."""
    return [
        {
            'filename': 'file1.txt',
            'mime_type': 'text/plain',
            'data': BytesIO(b"content 1")
        },
        {
            'filename': 'file2.pdf',
            'mime_type': 'application/pdf',
            'data': BytesIO(b"content 2")
        }
    ]

@pytest.fixture
def tracker():
    """Fixture providing a ConversationTracker instance."""
    return ConversationTracker(api_key="ags_1a2b3c4d5e6f7890abcdef1234567890_a1b2c3")

@pytest.fixture
def mock_http_client():
    """Fixture providing a mock HTTP client."""
    mock_client = Mock()
    mock_client.send_payload.return_value = {"success": True}
    mock_client.send_form_data_payload.return_value = {"success": True}
    return mock_client

@pytest.fixture
def sample_attachments():
    """Fixture providing sample attachment data."""
    return [
        {
            "filename": "test1.txt",
            "mime_type": "text/plain",
            "data": BytesIO(b"test content 1")
        },
        {
            "filename": "test2.pdf",
            "mime_type": "application/pdf",
            "data": BytesIO(b"test content 2")
        }
    ]

@pytest.fixture
def reset_singleton():
    """Fixture to reset ConversationTracker singleton before each test."""
    # Save original state
    original_instance = ConversationTracker._instance
    original_lock = ConversationTracker._instance_lock
    
    # Reset singleton
    ConversationTracker._instance = None
    ConversationTracker._instance_lock = Lock()
    
    yield
    
    # Restore original state after test
    ConversationTracker._instance = original_instance
    ConversationTracker._instance_lock = original_lock

@pytest.fixture(autouse=True)
def reset_all_singletons(request):
    """Fixture to reset all client singletons before each test to prevent state leakage."""

    if 'no_reset' in request.keywords:
        yield
        return

    from agentsight.client.api_client import AgentSightAPI
    from agentsight.client.conversation_manager_client import ConversationManager
    from agentsight.client.main_client import ConversationTracker
    
    # Reset all singletons BEFORE the test
    ConversationTracker._instance = None
    ConversationTracker._instance_lock = Lock()
    AgentSightAPI._instance = None
    AgentSightAPI._instance_lock = Lock()
    ConversationManager._instance = None
    ConversationManager._instance_lock = Lock()
    
    yield
