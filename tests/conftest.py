import pytest

VALID_API_KEY = "ags_1a2b3c4d5e6f7890abcdef1234567890_a1b2c3"


@pytest.fixture(autouse=True)
def isolated_env(monkeypatch):
    """
    A fixture that automatically runs for every test to ensure an
    isolated environment by removing specific environment variables.
    This ensures tests don't pick up values from .env files.
    """
    monkeypatch.delenv("AGENTSIGHT_API_KEY", raising=False)
    monkeypatch.delenv("AGENTSIGHT_API_ENDPOINT", raising=False)
    monkeypatch.delenv("AGENTSIGHT_APP_URL", raising=False)
    monkeypatch.delenv("AGENTSIGHT_CONVERSATION_ID", raising=False)
    # Both change what init() builds, so a developer's shell must not decide
    # which transport the suite exercises or which environment it stamps.
    monkeypatch.delenv("AGENTSIGHT_FILE_EXPORTER", raising=False)
    monkeypatch.delenv("AGENTSIGHT_ENVIRONMENT", raising=False)


@pytest.fixture
def valid_api_key():
    """Valid API key for testing."""
    return VALID_API_KEY
