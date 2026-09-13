"""The messages namespace: one message by pk, and its metadata."""

import pytest

from agentsight.exceptions import ValidationError
from tests.api.conftest import TRACK

DETAIL = f"{TRACK}17/"


def message(pk=17, **fields):
    record = {
        "id": pk,
        "conversation": 42,
        "sender": "agent",
        "content": "Try the Yoda table.",
        "timestamp": "2026-09-12T10:00:00Z",
        "metadata": {"recommended_product": {"sifra": "YODA-140"}},
    }
    record.update(fields)
    return record


def _fetch_and_patch(requests_mock, stored, patched=None):
    """The two round trips update_metadata makes: read, then write."""
    requests_mock.get(DETAIL, json=message(metadata=stored))
    return requests_mock.patch(DETAIL, json=patched or message())


# -- get --------------------------------------------------------------------


def test_get_reads_the_message_route(ags, requests_mock):
    requests_mock.get(DETAIL, json=message())

    record = ags.messages.get(17)

    assert record["id"] == 17
    assert requests_mock.last_request.path == "/api/track/17/"


@pytest.mark.parametrize("bad", ["17", "wa-3859", True, None, 17.0])
def test_a_message_is_named_by_its_integer_pk_only(ags, requests_mock, bad):
    """Messages have no business id, so there is nothing to look a string up
    by — and a bool is an int that nobody means."""
    get = requests_mock.get(DETAIL, json=message())

    with pytest.raises(ValidationError):
        ags.messages.get(bad)

    assert get.call_count == 0


# -- update -----------------------------------------------------------------


def test_update_patches_the_metadata_document(ags, requests_mock):
    patch = requests_mock.patch(DETAIL, json=message())

    ags.messages.update(17, metadata={"visualization": {"status": "completed"}})

    assert patch.last_request.method == "PATCH"
    assert patch.last_request.json() == {
        "metadata": {"visualization": {"status": "completed"}}
    }


def test_update_sends_nothing_but_metadata(ags):
    """Content, sender and timestamp are the transcript; the client cannot
    reach them even though the endpoint would accept them."""
    with pytest.raises(TypeError):
        ags.messages.update(17, content="rewritten")  # type: ignore[call-arg]


def test_update_refuses_non_dict_metadata(ags, requests_mock):
    patch = requests_mock.patch(DETAIL, json=message())

    with pytest.raises(ValidationError):
        ags.messages.update(17, metadata="not a dict")  # type: ignore[arg-type]

    assert patch.call_count == 0


# -- update_metadata --------------------------------------------------------


def test_update_metadata_keeps_what_the_turn_recorded(ags, requests_mock):
    """The reason this method exists: a job enriching a message after the
    turn must not wipe the keys the turn wrote."""
    _fetch_and_patch(requests_mock, {"recommended_product": {"sifra": "YODA-140"}})

    ags.messages.update_metadata(17, {"visualization": {"status": "completed"}})

    assert requests_mock.last_request.json() == {
        "metadata": {
            "recommended_product": {"sifra": "YODA-140"},
            "visualization": {"status": "completed"},
        }
    }


def test_update_metadata_reads_before_it_writes(ags, requests_mock):
    _fetch_and_patch(requests_mock, {"a": 1})

    ags.messages.update_metadata(17, {"b": 2})

    methods = [request.method for request in requests_mock.request_history]
    paths = [request.path for request in requests_mock.request_history]
    assert methods == ["GET", "PATCH"]
    assert paths == ["/api/track/17/", "/api/track/17/"]


def test_update_metadata_removes_keys(ags, requests_mock):
    _fetch_and_patch(requests_mock, {"keep": 1, "draft": True})

    ags.messages.update_metadata(17, remove=["draft"])

    assert requests_mock.last_request.json() == {"metadata": {"keep": 1}}


@pytest.mark.parametrize("value", [None, False, 0, ""])
def test_update_metadata_stores_falsy_values(ags, requests_mock, value):
    """Removing a key is said with `remove=`. A falsy value is data."""
    _fetch_and_patch(requests_mock, {"keep": 1})

    ags.messages.update_metadata(17, {"flag": value})

    assert requests_mock.last_request.json() == {
        "metadata": {"keep": 1, "flag": value}
    }


def test_update_metadata_handles_a_message_with_none_stored(ags, requests_mock):
    _fetch_and_patch(requests_mock, None)

    ags.messages.update_metadata(17, {"a": 1})

    assert requests_mock.last_request.json() == {"metadata": {"a": 1}}


def test_update_metadata_reads_a_document_stored_as_a_json_string(ags, requests_mock):
    _fetch_and_patch(requests_mock, '{"recommended_product": "x"}')

    ags.messages.update_metadata(17, {"visualization": 1})

    assert requests_mock.last_request.json() == {
        "metadata": {"recommended_product": "x", "visualization": 1}
    }


def test_update_metadata_refuses_when_the_server_withholds_the_field(ags, requests_mock):
    """Merging into {} here would write an empty document over whatever is
    stored. The field is visibility-flagged server-side."""
    requests_mock.get(DETAIL, json={"id": 17, "conversation": 42})
    patch = requests_mock.patch(DETAIL, json={})

    with pytest.raises(ValidationError):
        ags.messages.update_metadata(17, {"a": 1})

    assert patch.call_count == 0


def test_update_metadata_refuses_a_bare_string_for_remove(ags, requests_mock):
    get = requests_mock.get(DETAIL, json=message())

    with pytest.raises(ValidationError) as excinfo:
        ags.messages.update_metadata(17, remove="draft")

    assert "remove=['draft']" in str(excinfo.value)
    assert get.call_count == 0


def test_update_metadata_needs_something_to_do(ags):
    with pytest.raises(ValidationError):
        ags.messages.update_metadata(17)


def test_update_metadata_refuses_a_string_pk_before_any_request(ags, requests_mock):
    get = requests_mock.get(DETAIL, json=message())

    with pytest.raises(ValidationError):
        ags.messages.update_metadata("17", {"a": 1})

    assert get.call_count == 0


# -- what it deliberately is not -------------------------------------------


def test_the_client_cannot_create_or_list_messages(ags):
    assert not hasattr(ags.messages, "create")
    assert not hasattr(ags.messages, "list")
