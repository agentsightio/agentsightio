"""The tickets namespace — full CRUD, filed as the machine."""

import pytest

from agentsight.exceptions import ValidationError
from tests.api.conftest import CONVERSATIONS, TICKETS, conversation, envelope


def ticket(pk=1, **fields):
    record = {
        "id": pk,
        "agent": 7,
        "title": "Timeout in checkout",
        "status": "open",
        "priority": None,
        "tags": [],
        "environment": "production",
        "environment_id": 1,
        "conversation": None,
        "feedback": None,
        "comments": [],
        "comments_count": 0,
    }
    record.update(fields)
    return record


# -- reading ---------------------------------------------------------------


def test_list_filters_reach_the_wire(ags, requests_mock):
    requests_mock.get(TICKETS, json=envelope([ticket()]))

    list(ags.tickets.list(priority="high", has_conversation=True, tags="checkout"))

    query = requests_mock.last_request.qs
    assert query["priority"] == ["high"]
    assert query["has_conversation"] == ["true"]
    assert query["tags"] == ["checkout"]


def test_status_list_repeats_the_key(ags, requests_mock):
    requests_mock.get(TICKETS, json=envelope([]))

    list(ags.tickets.list(status=["open", "in_progress"]))

    assert requests_mock.last_request.qs["status"] == ["open", "in_progress"]


def test_an_unknown_filter_is_refused_locally(ags, requests_mock):
    # `agent` (a key is bound to one) and `environment` (the route has no
    # such filter) must fail before any request widens the result set.
    for name in ("agent", "environment", "definitely_not_a_filter"):
        with pytest.raises(ValidationError, match="ticket filter"):
            ags.tickets.list(**{name: 1})
    assert requests_mock.call_count == 0


def test_a_bad_status_value_is_refused_locally(ags, requests_mock):
    with pytest.raises(ValidationError, match="status"):
        ags.tickets.list(status="opened")
    assert requests_mock.call_count == 0


def test_get(ags, requests_mock):
    requests_mock.get(f"{TICKETS}42/", json=ticket(42))

    assert ags.tickets.get(42)["id"] == 42


def test_comments_paginates_the_nested_route(ags, requests_mock):
    route = requests_mock.get(
        f"{TICKETS}42/comments/",
        json=envelope([{"id": 1, "author": "test-key", "role": "agent", "body": "hi"}]),
    )

    comments = list(ags.tickets.comments(42))

    assert route.call_count == 1
    assert comments[0]["role"] == "agent"


# -- writing ---------------------------------------------------------------


def test_create_sends_only_what_was_given(ags, requests_mock):
    requests_mock.post(TICKETS, json=ticket())

    ags.tickets.create("Timeout in checkout", priority="high", tags=["billing"])

    assert requests_mock.last_request.json() == {
        "title": "Timeout in checkout",
        "priority": "high",
        "tags": ["billing"],
    }


def test_create_resolves_a_business_conversation_id_to_the_pk_field(
    ags, requests_mock
):
    # On this route the WRITE field `conversation_id` wants the DB pk (the
    # serializer keeps `conversation` for its nested summary), unlike the
    # feedback route where conversation_id is the business string. The
    # resolver papers over the asymmetry.
    requests_mock.get(CONVERSATIONS, json=envelope([conversation(pk=4412)]))
    requests_mock.post(TICKETS, json=ticket())

    ags.tickets.create("Anchored", conversation="wa-3859")

    assert requests_mock.last_request.json()["conversation_id"] == 4412


def test_create_by_pk_needs_no_resolution(ags, requests_mock):
    requests_mock.post(TICKETS, json=ticket())

    ags.tickets.create("Anchored", conversation=4412)

    assert requests_mock.call_count == 1
    assert requests_mock.last_request.json()["conversation_id"] == 4412


def test_create_requires_a_title(ags, requests_mock):
    with pytest.raises(ValidationError, match="title"):
        ags.tickets.create("   ")
    assert requests_mock.call_count == 0


def test_update_refuses_unknown_fields(ags, requests_mock):
    # `environment` is write-once server-side; naming it here should say so
    # locally rather than round-trip a 400.
    with pytest.raises(ValidationError, match="environment"):
        ags.tickets.update(42, environment="development")
    assert requests_mock.call_count == 0


def test_update_patches_the_named_fields(ags, requests_mock):
    requests_mock.patch(f"{TICKETS}42/", json=ticket(42, status="closed"))

    ags.tickets.update(42, status="closed", title="Fixed")

    assert requests_mock.last_request.json() == {
        "status": "closed",
        "title": "Fixed",
    }


def test_delete(ags, requests_mock):
    route = requests_mock.delete(f"{TICKETS}42/", status_code=204, json=None)

    ags.tickets.delete(42)

    assert route.call_count == 1


def test_add_comment_sends_the_body_and_no_role(ags, requests_mock):
    # The backend records role="agent" and the key's name regardless; the
    # client never offers a role to make that look negotiable.
    requests_mock.post(
        f"{TICKETS}42/comments/",
        json={"id": 1, "author": "test-key", "role": "agent", "body": "heads up"},
    )

    ags.tickets.add_comment(42, "heads up")

    assert requests_mock.last_request.json() == {"body": "heads up"}
