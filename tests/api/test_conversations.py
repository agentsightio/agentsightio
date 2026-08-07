"""The conversations namespace."""

from datetime import datetime, timezone

import pytest

from agentsight.exceptions import PermissionDeniedError, ValidationError
from tests.api.conftest import BASE, CONVERSATIONS, conversation, envelope

DETAIL = f"{BASE}/api/conversations/42/"


@pytest.fixture
def resolved(requests_mock):
    """Make `wa-3859` resolve to pk 42."""
    requests_mock.get(CONVERSATIONS, json=envelope([conversation(42, "wa-3859")]))
    return requests_mock


# -- listing ----------------------------------------------------------------


def test_list_asks_for_the_lean_payload(ags, requests_mock):
    # The backend defaults an API key to full=true, i.e. every row carrying
    # its whole transcript. That is rarely what a list is for.
    requests_mock.get(CONVERSATIONS, json=envelope([]))

    list(ags.conversations.list())

    assert requests_mock.last_request.qs["full"] == ["false"]


def test_list_full_asks_for_the_transcripts(ags, requests_mock):
    requests_mock.get(CONVERSATIONS, json=envelope([]))

    list(ags.conversations.list_full())

    assert requests_mock.last_request.qs["full"] == ["true"]


def test_booleans_are_sent_the_way_django_reads_them(ags, requests_mock):
    requests_mock.get(CONVERSATIONS, json=envelope([]))

    list(ags.conversations.list(is_marked=True, has_feedback=False))

    assert requests_mock.last_request.qs["is_marked"] == ["true"]
    assert requests_mock.last_request.qs["has_feedback"] == ["false"]


def test_datetimes_are_sent_as_iso_8601(ags, requests_mock):
    requests_mock.get(CONVERSATIONS, json=envelope([]))
    since = datetime(2026, 8, 1, 12, 30, tzinfo=timezone.utc)

    list(ags.conversations.list(started_at_after=since))

    assert requests_mock.last_request.qs["started_at_after"] == [
        since.isoformat().lower()
    ]


def test_environment_is_sent_as_the_env_filter(ags, requests_mock):
    requests_mock.get(CONVERSATIONS, json=envelope([]))

    list(ags.conversations.list(environment="production"))

    assert requests_mock.last_request.qs["env"] == ["production"]


def test_unset_filters_are_omitted_rather_than_sent_as_none(ags, requests_mock):
    requests_mock.get(CONVERSATIONS, json=envelope([]))

    list(ags.conversations.list(device=None, language="en"))

    assert "device" not in requests_mock.last_request.qs


def test_an_unknown_filter_is_refused_locally(ags):
    # A filter the backend ignores silently returns MORE rows than asked for.
    with pytest.raises(ValidationError) as excinfo:
        ags.conversations.list(custmer_id="c-1")

    assert "custmer_id" in str(excinfo.value)


def test_an_invalid_sentiment_is_refused_locally(ags):
    with pytest.raises(ValidationError):
        ags.conversations.list(feedback_sentiment="grumpy")


# -- reading ----------------------------------------------------------------


def test_get_defaults_to_the_full_payload(ags, requests_mock):
    requests_mock.get(DETAIL, json=conversation(42))

    ags.conversations.get(42)

    assert requests_mock.last_request.qs["full"] == ["true"]


def test_get_accepts_a_business_id(ags, resolved, requests_mock):
    requests_mock.get(DETAIL, json=conversation(42, "wa-3859"))

    assert ags.conversations.get("wa-3859")["id"] == 42


def test_attachments_reads_the_signed_urls(ags, requests_mock):
    requests_mock.get(
        f"{BASE}/api/conversations/42/attachments/",
        json={"conversation": 42, "attachment_count": 1, "attachments": []},
    )

    assert ags.conversations.attachments(42)["attachment_count"] == 1


def test_metadata_keys(ags, requests_mock):
    requests_mock.get(f"{CONVERSATIONS}metadata-keys/", json=["tier", "region"])

    assert ags.conversations.metadata_keys() == ["tier", "region"]


def test_metadata_values_passes_the_key(ags, requests_mock):
    requests_mock.get(f"{CONVERSATIONS}metadata-values/", json=["gold"])

    assert ags.conversations.metadata_values("tier") == ["gold"]
    assert requests_mock.last_request.qs["key"] == ["tier"]


def test_metadata_values_needs_a_key(ags):
    with pytest.raises(ValidationError):
        ags.conversations.metadata_values("")


def test_message_metadata_keys(ags, requests_mock):
    requests_mock.get(f"{CONVERSATIONS}message-metadata-keys/", json=["latency_ms"])

    assert ags.conversations.message_metadata_keys() == ["latency_ms"]


# -- managing ---------------------------------------------------------------


def test_rename_patches_the_rename_route(ags, requests_mock):
    requests_mock.patch(f"{DETAIL}rename/", json={"name": "Refund"})

    ags.conversations.rename(42, "  Refund  ")

    assert requests_mock.last_request.json() == {"name": "Refund"}


@pytest.mark.parametrize("bad", ["", "   ", None, 7])
def test_rename_refuses_an_empty_name(ags, bad):
    with pytest.raises(ValidationError):
        ags.conversations.rename(42, bad)


def test_rename_refuses_an_overlong_name(ags):
    with pytest.raises(ValidationError):
        ags.conversations.rename(42, "x" * 256)


def test_mark_posts_a_boolean(ags, requests_mock):
    requests_mock.post(f"{DETAIL}mark/", json={})

    ags.conversations.mark(42)

    assert requests_mock.last_request.json() == {"is_marked": True}


def test_unmark(ags, requests_mock):
    requests_mock.post(f"{DETAIL}mark/", json={})

    ags.conversations.mark(42, False)

    assert requests_mock.last_request.json() == {"is_marked": False}


def test_update_sends_only_what_changed(ags, requests_mock):
    requests_mock.patch(f"{DETAIL}update/", json={})

    ags.conversations.update(42, name="Refund", language=None, is_marked=True)

    assert requests_mock.last_request.json() == {"name": "Refund", "is_marked": True}


def test_update_refuses_an_immutable_field(ags):
    with pytest.raises(ValidationError) as excinfo:
        ags.conversations.update(42, conversation_id="something-else")

    assert "conversation_id" in str(excinfo.value)


def test_update_needs_at_least_one_field(ags):
    with pytest.raises(ValidationError):
        ags.conversations.update(42)


def test_update_refuses_non_dict_metadata(ags):
    with pytest.raises(ValidationError):
        ags.conversations.update(42, metadata="tier=gold")


def test_soft_delete_and_hard_delete_are_different_routes(ags, requests_mock):
    soft = requests_mock.delete(f"{DETAIL}delete/", json={})
    hard = requests_mock.delete(DETAIL, json={})

    ags.conversations.delete(42)
    ags.conversations.purge(42)

    assert soft.call_count == 1
    assert hard.call_count == 1


def test_a_read_key_hitting_a_write_route_gets_permission_denied(ags, requests_mock):
    requests_mock.patch(
        f"{DETAIL}rename/",
        status_code=403,
        json={"detail": "You do not have permission to perform this action."},
    )

    with pytest.raises(PermissionDeniedError) as excinfo:
        ags.conversations.rename(42, "Refund")

    assert "permission" in excinfo.value.detail.lower()


# -- surface ----------------------------------------------------------------


def test_the_client_cannot_create_conversations(ags):
    # Conversation creation belongs to the tracking SDK; two write paths for
    # one row would mean two sets of projection semantics.
    assert not hasattr(ags.conversations, "create")
