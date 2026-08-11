"""``ags.me()`` — the preflight the client had no way to perform."""

import pytest

from agentsight.exceptions import PermissionDeniedError
from tests.api.conftest import IDENTITY, ME, environment


def test_me_reports_the_agent_role_and_environments(ags, requests_mock):
    requests_mock.get(ME, json=IDENTITY)

    assert ags.me() == IDENTITY


def test_the_role_no_longer_has_to_be_learned_from_a_403(ags, requests_mock):
    # Previously the only way to discover a key's role was to attempt a write
    # and catch the refusal.
    requests_mock.get(ME, json={**IDENTITY, "role": "read"})

    assert ags.me()["role"] == "read"


def test_it_is_cached(ags, requests_mock):
    # None of it changes for the life of a key.
    requests_mock.get(ME, json=IDENTITY)

    ags.me()
    ags.me()
    ags.me()

    assert requests_mock.call_count == 1


def test_refresh_asks_again(ags, requests_mock):
    grown = [*IDENTITY["environments"], environment("staging", 3)]
    requests_mock.get(ME, [{"json": IDENTITY},
                           {"json": {**IDENTITY, "environments": grown}}])

    assert ags.environments() == ["production", "development"]
    assert ags.environments(refresh=True)[-1] == "staging"


def test_environments_flattens_the_objects_the_route_actually_sends(ags,
                                                                    requests_mock):
    # /api/me/ serialises whole AgentEnvironment rows. Reading them as strings
    # yielded "{'id': 1, 'slug': 'production', ...}" — entries that look like
    # slugs, compare equal to nothing, and fail only downstream.
    requests_mock.get(ME, json=IDENTITY)

    assert ags.environments() == ["production", "development"]


def test_environments_still_accepts_bare_slugs(ags, requests_mock):
    # The contract of this method is a list of slugs; it should not break if
    # the route ever flattens what it sends.
    requests_mock.get(ME, json={**IDENTITY, "environments": ["production", "canary"]})

    assert ags.environments() == ["production", "canary"]


def test_environments_is_the_authoritative_list(ags, requests_mock):
    # The tracking plane hard-codes the pair because it may not perform I/O;
    # this is what a slug added server-side reaches an already-published
    # client through.
    requests_mock.get(
        ME,
        json={**IDENTITY, "environments": [environment("production", 1),
                                           environment("canary", 9)]},
    )

    assert ags.environments() == ["production", "canary"]


def test_environments_survives_a_payload_without_the_key(ags, requests_mock):
    requests_mock.get(ME, json={"agent_id": 7, "agent_name": "x", "role": "read"})

    assert ags.environments() == []


def test_environments_skips_entries_with_no_slug(ags, requests_mock):
    # Better a short list than one carrying a placeholder nothing matches.
    requests_mock.get(ME, json={**IDENTITY,
                                "environments": [{"id": 4, "name": "Broken"},
                                                 environment("production", 1)]})

    assert ags.environments() == ["production"]


def test_a_403_is_not_swallowed(ags, requests_mock):
    # This route is API-key only; a JWT session gets 403 by design. Caching a
    # failure as an identity would be worse than raising.
    requests_mock.get(ME, status_code=403, json={"detail": "no"})

    with pytest.raises(PermissionDeniedError):
        ags.me()

    assert ags._identity is None
