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
SPANS = f"{BASE}/api/spans/"
TRACES = f"{BASE}/api/traces/"
ME = f"{BASE}/api/me/"

def environment(slug, pk=1, is_production=False):
    """One environment exactly as ``AgentEnvironmentSerializer`` sends it.

    Spelled out rather than reduced to a slug string because that reduction is
    precisely the bug this fixture used to hide: the route serialises whole
    objects, and a client reading them as strings gets entries that look like
    slugs and match nothing.
    """
    return {
        "id": pk,
        "slug": slug,
        "name": slug.title(),
        "is_production": is_production,
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:00Z",
    }


IDENTITY = {
    "agent_id": 7,
    "agent_name": "Support bot",
    "role": "write",
    "environments": [
        environment("production", 1, is_production=True),
        environment("development", 2),
    ],
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


def span(pk=1, span_id="aaaa0001", **fields):
    """One span row exactly as ``IngestSpanSerializer`` sends it.

    No ``payload`` key, because the list route never sends one — a fixture
    that carried it would let a test pass against a shape the server does not
    produce.
    """
    record = {
        "id": pk,
        "conversation": 4412,
        "conversation_id": "wa-3859",
        "trace_id": "4bf92f3577b34da6a3ce929d0e0e4736",
        "span_id": span_id,
        "parent_span_id": None,
        "kind": "turn",
        "name": "turn",
        "started_at": "2026-01-01T00:00:00Z",
        "ended_at": "2026-01-01T00:00:01Z",
        "duration_ms": 1000.0,
        "status": "ok",
        "attributes": {"agentsight.span.kind": "turn"},
        "events": [],
    }
    record.update(fields)
    return record
