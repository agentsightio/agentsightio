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


# -- merging metadata -------------------------------------------------------


def _fetch_and_patch(requests_mock, stored, patched=None):
    """The two round trips update_metadata makes: read, then write."""
    requests_mock.get(DETAIL, json=conversation(42, "wa-3859", metadata=stored))
    return requests_mock.patch(f"{DETAIL}update/", json=patched or {})


def test_update_metadata_merges_instead_of_replacing(ags, requests_mock):
    """`update(metadata=...)` replaces the whole document, because that is all
    the endpoint can do. This is the version that keeps what is already there."""
    _fetch_and_patch(requests_mock, {"order_id": "A-1", "plan": "trial"})

    ags.conversations.update_metadata(42, {"plan": "enterprise"})

    assert requests_mock.last_request.json() == {
        "metadata": {"order_id": "A-1", "plan": "enterprise"}
    }


def test_update_metadata_reads_before_it_writes(ags, requests_mock):
    _fetch_and_patch(requests_mock, {"a": 1})

    ags.conversations.update_metadata(42, {"b": 2})

    methods = [request.method for request in requests_mock.request_history]
    assert methods == ["GET", "PATCH"]


def test_update_metadata_removes_keys(ags, requests_mock):
    _fetch_and_patch(requests_mock, {"plan": "trial", "trial_ends": "friday"})

    ags.conversations.update_metadata(42, remove=["trial_ends"])

    assert requests_mock.last_request.json() == {"metadata": {"plan": "trial"}}


@pytest.mark.parametrize("value", [None, False, 0, ""])
def test_update_metadata_stores_falsy_values(ags, requests_mock, value):
    """Removing a key is said with `remove=`. A falsy value is data."""
    _fetch_and_patch(requests_mock, {"keep": 1})

    ags.conversations.update_metadata(42, {"flag": value})

    assert requests_mock.last_request.json() == {
        "metadata": {"keep": 1, "flag": value}
    }


def test_update_metadata_handles_a_conversation_with_none_stored(ags, requests_mock):
    _fetch_and_patch(requests_mock, None)

    ags.conversations.update_metadata(42, {"a": 1})

    assert requests_mock.last_request.json() == {"metadata": {"a": 1}}


def test_update_metadata_reads_a_document_stored_as_a_json_string(ags, requests_mock):
    """Rows written by older SDK builds hold the document as a JSON string.
    Merging into one of those must preserve its keys, not discard them."""
    _fetch_and_patch(requests_mock, '{"order_id": "A-1"}')

    ags.conversations.update_metadata(42, {"plan": "enterprise"})

    assert requests_mock.last_request.json() == {
        "metadata": {"order_id": "A-1", "plan": "enterprise"}
    }


def test_update_metadata_refuses_when_the_server_withholds_the_field(ags, requests_mock):
    """Merging into {} here would write an empty document over whatever is
    stored. The field is visibility-flagged server-side."""
    requests_mock.get(DETAIL, json={"id": 42, "conversation_id": "wa-3859"})
    patch = requests_mock.patch(f"{DETAIL}update/", json={})

    with pytest.raises(ValidationError):
        ags.conversations.update_metadata(42, {"a": 1})

    assert patch.call_count == 0


def test_update_metadata_refuses_a_bare_string_for_remove(ags, requests_mock):
    get = requests_mock.get(DETAIL, json=conversation(42, metadata={}))

    with pytest.raises(ValidationError) as excinfo:
        ags.conversations.update_metadata(42, remove="plan")

    assert "remove=['plan']" in str(excinfo.value)
    # Rejected before it costs a round trip.
    assert get.call_count == 0


def test_update_metadata_needs_something_to_do(ags):
    with pytest.raises(ValidationError):
        ags.conversations.update_metadata(42)


def test_update_metadata_syncs_a_live_tracking_scope(ags, resolved, requests_mock):
    """Conversation metadata rides on every span and ingest takes the newest
    document it has seen. Without this, the PATCH lands and is then overwritten
    seconds later by the next span carrying the scope's stale copy."""
    import agentsight

    _fetch_and_patch(requests_mock, {"a": 1})

    with agentsight.conversation("wa-3859", metadata={"a": 1}) as scope:
        ags.conversations.update_metadata("wa-3859", {"b": 2})

        assert scope.metadata == {"a": 1, "b": 2}


def test_update_metadata_leaves_an_unrelated_scope_alone(ags, resolved, requests_mock):
    import agentsight

    _fetch_and_patch(requests_mock, {"a": 1})

    with agentsight.conversation("somebody-else", metadata={"x": 9}) as scope:
        ags.conversations.update_metadata("wa-3859", {"b": 2})

        assert scope.metadata == {"x": 9}


def test_update_metadata_syncs_a_live_scope_named_by_pk(ags, requests_mock):
    """The read it already makes names both ids, so passing the pk loses
    nothing — the scope is still found and still updated."""
    import agentsight

    _fetch_and_patch(requests_mock, {"a": 1})

    with agentsight.conversation("wa-3859", metadata={"a": 1}) as scope:
        ags.conversations.update_metadata(42, {"b": 2})

        assert scope.metadata == {"a": 1, "b": 2}


# -- the same problem, for every other field that rides on a span -----------


def test_update_syncs_the_span_fields_into_a_live_scope(ags, resolved,
                                                        requests_mock):
    """`customer_id`, `device`, `language` and `name` are stamped on every span
    and written onto the row by ingest, exactly like metadata. Without this the
    PATCH lands and the next span puts the old values straight back."""
    import agentsight
    from agentsight.sdk.semconv import ConversationAttributes as CA

    requests_mock.patch(f"{DETAIL}update/", json={})

    with agentsight.conversation("wa-3859", customer_id="user-1",
                                 device="ios") as scope:
        ags.conversations.update("wa-3859", customer_id="user-42",
                                 device="android", language="en")

        assert scope.attributes[CA.CUSTOMER_ID] == "user-42"
        assert scope.attributes[CA.DEVICE] == "android"
        assert scope.attributes[CA.LANGUAGE] == "en"


def test_update_syncs_metadata_and_fields_together(ags, resolved, requests_mock):
    import agentsight
    from agentsight.sdk.semconv import ConversationAttributes as CA

    requests_mock.patch(f"{DETAIL}update/", json={})

    with agentsight.conversation("wa-3859", metadata={"a": 1}) as scope:
        ags.conversations.update("wa-3859", name="Refund", metadata={"b": 2})

        assert scope.attributes[CA.NAME] == "Refund"
        # update() replaces the document; that is what the endpoint does.
        assert scope.metadata == {"b": 2}


def test_rename_syncs_a_live_scope(ags, resolved, requests_mock):
    import agentsight
    from agentsight.sdk.semconv import ConversationAttributes as CA

    requests_mock.patch(f"{DETAIL}rename/", json={})

    with agentsight.conversation("wa-3859", name="Untitled") as scope:
        ags.conversations.rename("wa-3859", "Refund — resolved")

        assert scope.attributes[CA.NAME] == "Refund — resolved"


@pytest.fixture
def spans():
    """A real span pipeline, so the sync can be checked where it matters: in
    the payload the exporter would have posted."""
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
        InMemorySpanExporter,
    )

    from agentsight.sdk import core
    from agentsight.sdk.processors import TurnBufferingProcessor

    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(TurnBufferingProcessor(SimpleSpanProcessor(exporter)))

    previous = (core._state.enabled, core._state.provider, core._state.tracer)
    core._state.provider = provider
    core._state.tracer = provider.get_tracer("agentsight-test")
    core._state.enabled = True
    try:
        yield exporter
    finally:
        core._state.enabled, core._state.provider, core._state.tracer = previous


def test_a_synced_field_reaches_the_next_span(ags, resolved, requests_mock,
                                              spans):
    """The whole point, end to end: what the next payload block carries."""
    import agentsight
    from agentsight.sdk.exporter import build_payload

    requests_mock.patch(f"{DETAIL}update/", json={})

    with agentsight.conversation("wa-3859", customer_id="user-1"):
        ags.conversations.update("wa-3859", customer_id="user-42")
        with agentsight.turn():
            agentsight.user_message("after the patch")

    block = build_payload(spans.get_finished_spans())["conversations"][0]
    assert block["customer_id"] == "user-42"


def test_update_leaves_an_unrelated_scope_alone(ags, resolved, requests_mock):
    import agentsight
    from agentsight.sdk.semconv import ConversationAttributes as CA

    requests_mock.patch(f"{DETAIL}update/", json={})

    with agentsight.conversation("somebody-else", customer_id="user-9") as scope:
        ags.conversations.update("wa-3859", customer_id="user-42")

        assert scope.attributes[CA.CUSTOMER_ID] == "user-9"


def test_is_marked_has_nowhere_to_sync_and_that_is_fine(ags, resolved,
                                                        requests_mock):
    """The one updatable field no span carries. It must not raise on the way
    through, and it must not invent an attribute."""
    import agentsight

    requests_mock.patch(f"{DETAIL}update/", json={})

    with agentsight.conversation("wa-3859") as scope:
        ags.conversations.update("wa-3859", is_marked=True)

        assert not any("marked" in key for key in scope.attributes)


def test_a_synced_value_is_clamped_like_any_other(ags, resolved, requests_mock):
    """It travels on the wire, so it goes through the same 255-char clamp the
    constructor uses — otherwise a value the API accepted could be what
    rejects the batch it next rides in."""
    import agentsight
    from agentsight.sdk.semconv import ConversationAttributes as CA

    requests_mock.patch(f"{DETAIL}update/", json={})

    with agentsight.conversation("wa-3859") as scope:
        ags.conversations.update("wa-3859", customer_id="x" * 400)

        assert len(scope.attributes[CA.CUSTOMER_ID]) == 255


def test_the_sync_is_silent_without_the_tracking_sdk(ags, resolved,
                                                     requests_mock):
    """This client is usable on its own. Managing a conversation from a process
    that never initialised tracking must not raise."""
    requests_mock.patch(f"{DETAIL}update/", json={"ok": True})

    assert ags.conversations.update("wa-3859", customer_id="user-42") == {"ok": True}


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
