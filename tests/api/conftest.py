"""Shared fixtures for the data-plane client tests.

One place, unlike ``tests/sdk/`` where the span fixtures are copied per file.
"""

import pytest

from agentsight.api import AgentSight
from tests.conftest import VALID_API_KEY

BASE = "https://api.test.agentsight.io"

CONVERSATIONS = f"{BASE}/api/conversations/"
FEEDBACKS = f"{BASE}/api/feedbacks/"
ACTIONS = f"{BASE}/api/actions/"
USAGE = f"{BASE}/api/token-usage/"
USAGE_SUMMARY = f"{USAGE}summary/"
ME = f"{BASE}/api/me/"

IDENTITY = {
    "agent_id": 7,
    "agent_name": "Support bot",
    "role": "write",
    "environments": ["production", "development"],
}


@pytest.fixture
def ags():
    """A client pointed at a base URL nothing will ever resolve."""
    client = AgentSight(api_key=VALID_API_KEY, endpoint=BASE)
    yield client
    client.close()


def envelope(results, **extra):
    """The backend's seven-key list envelope, plus any per-endpoint additions."""
    body = {
        "count": extra.pop("count", len(results)),
        "page_size": extra.pop("page_size", 100),
        "total_pages": extra.pop("total_pages", 1),
        "current_page": extra.pop("current_page", 1),
        "next": extra.pop("next", None),
        "previous": extra.pop("previous", None),
        "results": results,
    }
    body.update(extra)
    return body


def conversation(pk=1, conversation_id="wa-3859", **fields):
    record = {"id": pk, "conversation_id": conversation_id, "name": "Refund"}
    record.update(fields)
    return record
