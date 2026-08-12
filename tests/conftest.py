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


@pytest.fixture(autouse=True)
def fresh_learned_environments():
    """The learned-environment set is process-wide by design; tests are not.

    Any test that runs the key preflight against a mock naming custom
    environments would otherwise leak them into every test after it.
    """
    from agentsight import _settings

    _settings._reset_environments_for_tests()
    yield
    _settings._reset_environments_for_tests()


@pytest.fixture(autouse=True)
def fresh_learned_capabilities():
    """Same isolation, same reason, for the backend-capability set — a test
    that teaches the process "gzip-ingest" must not leave every later
    exporter test silently compressing."""
    from agentsight import _settings

    _settings._reset_capabilities_for_tests()
    yield
    _settings._reset_capabilities_for_tests()


@pytest.fixture
def valid_api_key():
    """Valid API key for testing."""
    return VALID_API_KEY
