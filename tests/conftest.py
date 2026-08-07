import pytest
from threading import Lock
from unittest.mock import MagicMock

from agentsight.config import Config


@pytest.fixture(autouse=True)
def isolated_env(monkeypatch):
    """
    A fixture that automatically runs for every test to ensure an
    isolated environment by removing specific environment variables.
    This ensures tests don't pick up values from .env files.
    """
    # Remove any environment variables that could interfere with tests
    # monkeypatch.delenv makes os.getenv() return None for these keys
    monkeypatch.delenv("AGENTSIGHT_API_KEY", raising=False)
    monkeypatch.delenv("AGENTSIGHT_CONVERSATION_ID", raising=False)
    # Both change what init() builds, so a developer's shell must not decide
    # which transport the suite exercises or which environment it stamps.
    monkeypatch.delenv("AGENTSIGHT_FILE_EXPORTER", raising=False)
    monkeypatch.delenv("AGENTSIGHT_ENVIRONMENT", raising=False)


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


@pytest.fixture(autouse=True)
def reset_all_singletons(request):
    """Fixture to reset all client singletons before each test to prevent state leakage."""

    if 'no_reset' in request.keywords:
        yield
        return

    from agentsight.client.api_client import AgentSightAPI
    from agentsight.client.conversation_manager_client import ConversationManager

    # Reset all singletons BEFORE the test
    AgentSightAPI._instance = None
    AgentSightAPI._instance_lock = Lock()
    ConversationManager._instance = None
    ConversationManager._instance_lock = Lock()

    yield
