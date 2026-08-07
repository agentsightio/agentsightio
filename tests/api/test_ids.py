"""Resolving business conversation ids to primary keys, and caching them."""

import threading

import pytest

from agentsight.exceptions import NotFoundError, ValidationError
from tests.api.conftest import BASE, CONVERSATIONS, conversation, envelope


def test_an_integer_passes_straight_through(ags, requests_mock):
    assert ags.conversations.resolve(42) == 42
    assert requests_mock.call_count == 0


def test_a_string_is_resolved_through_the_list_filter(ags, requests_mock):
    requests_mock.get(CONVERSATIONS, json=envelope([conversation(42, "wa-3859")]))

    assert ags.conversations.resolve("wa-3859") == 42
    assert requests_mock.last_request.qs["conversation_id"] == ["wa-3859"]


def test_resolution_does_not_use_the_lookup_route(ags, requests_mock):
    # /api/conversations/lookup/ is a GET, but falls through to the write
    # branch of the view's permissions, so a read-only key gets 403 on it.
    requests_mock.get(CONVERSATIONS, json=envelope([conversation(42, "wa-3859")]))

    ags.conversations.resolve("wa-3859")

    assert "lookup" not in requests_mock.last_request.path


def test_resolution_includes_soft_deleted_conversations(ags, requests_mock):
    # So a deleted conversation can still be inspected or restored.
    requests_mock.get(CONVERSATIONS, json=envelope([conversation(42, "wa-3859")]))

    ags.conversations.resolve("wa-3859")

    assert requests_mock.last_request.qs["include_deleted"] == ["true"]


def test_resolution_asks_for_the_lean_payload(ags, requests_mock):
    requests_mock.get(CONVERSATIONS, json=envelope([conversation(42, "wa-3859")]))

    ags.conversations.resolve("wa-3859")

    assert requests_mock.last_request.qs["full"] == ["false"]


def test_an_unknown_id_raises_not_found(ags, requests_mock):
    requests_mock.get(CONVERSATIONS, json=envelope([]))

    with pytest.raises(NotFoundError) as excinfo:
        ags.conversations.resolve("nope")

    assert "nope" in str(excinfo.value)


def test_multiple_matches_warn_and_take_the_first(ags, requests_mock, caplog):
    requests_mock.get(
        CONVERSATIONS,
        json=envelope([conversation(42, "dupe"), conversation(43, "dupe")]),
    )

    assert ags.conversations.resolve("dupe") == 42
    assert "matched 2 conversations" in caplog.text


@pytest.mark.parametrize("bad", [None, 3.5, True, "", "   ", []])
def test_a_nonsense_reference_is_refused(ags, bad):
    with pytest.raises(ValidationError):
        ags.conversations.resolve(bad)


# -- caching ----------------------------------------------------------------


def test_a_resolved_id_is_remembered(ags, requests_mock):
    requests_mock.get(CONVERSATIONS, json=envelope([conversation(42, "wa-3859")]))

    ags.conversations.resolve("wa-3859")
    ags.conversations.resolve("wa-3859")

    assert requests_mock.call_count == 1


def test_listing_primes_the_cache(ags, requests_mock):
    # Every conversation payload names both its id and its conversation_id,
    # so listing then managing costs no lookups at all.
    requests_mock.get(
        CONVERSATIONS, json=envelope([conversation(42, "a"), conversation(43, "b")])
    )

    list(ags.conversations.list())
    before = requests_mock.call_count

    assert ags.conversations.resolve("a") == 42
    assert ags.conversations.resolve("b") == 43
    assert requests_mock.call_count == before


def test_get_primes_the_cache(ags, requests_mock):
    requests_mock.get(f"{BASE}/api/conversations/42/", json=conversation(42, "wa-3859"))

    ags.conversations.get(42)

    assert ags._cache_snapshot()["wa-3859"] == 42


def test_soft_delete_forgets_the_mapping(ags, requests_mock):
    requests_mock.get(CONVERSATIONS, json=envelope([conversation(42, "wa-3859")]))
    requests_mock.delete(f"{BASE}/api/conversations/42/delete/", json={})

    ags.conversations.resolve("wa-3859")
    ags.conversations.delete("wa-3859")

    assert "wa-3859" not in ags._cache_snapshot()


def test_purge_forgets_the_mapping_given_only_a_pk(ags, requests_mock):
    requests_mock.get(CONVERSATIONS, json=envelope([conversation(42, "wa-3859")]))
    requests_mock.delete(f"{BASE}/api/conversations/42/", json={})

    ags.conversations.resolve("wa-3859")
    ags.conversations.purge(42)

    assert ags._cache_snapshot() == {}


def test_the_cache_is_bounded(ags):
    from agentsight.api._client import _MAX_CACHED_IDS

    for n in range(_MAX_CACHED_IDS + 50):
        ags.remember({"id": n, "conversation_id": f"c-{n}"})

    snapshot = ags._cache_snapshot()
    assert len(snapshot) == _MAX_CACHED_IDS
    # Least-recently-used went first.
    assert "c-0" not in snapshot
    assert f"c-{_MAX_CACHED_IDS + 49}" in snapshot


def test_remember_ignores_payloads_without_both_ids(ags):
    ags.remember({"id": 1})
    ags.remember({"conversation_id": "a"})
    ags.remember("not a dict")

    assert ags._cache_snapshot() == {}


def test_the_cache_survives_concurrent_writers(ags):
    def fill(start):
        for n in range(start, start + 200):
            ags.remember({"id": n, "conversation_id": f"c-{n}"})

    threads = [threading.Thread(target=fill, args=(i * 200,)) for i in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(ags._cache_snapshot()) == 800


def test_caches_are_per_client(ags, requests_mock):
    from agentsight.api import AgentSight
    from tests.conftest import VALID_API_KEY

    requests_mock.get(CONVERSATIONS, json=envelope([conversation(42, "wa-3859")]))
    ags.conversations.resolve("wa-3859")

    with AgentSight(api_key=VALID_API_KEY, endpoint=BASE) as other:
        assert other._cache_snapshot() == {}
