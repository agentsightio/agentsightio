"""The data_entities namespace, and the filter pair on the routes that take it."""

import pytest

from agentsight.exceptions import NotFoundError, ValidationError
from tests.api.conftest import (
    CONVERSATIONS,
    DATA_ENTITIES,
    FEEDBACKS,
    IDENTITY,
    ME,
    TICKETS,
    USAGE,
    USAGE_SUMMARY,
    envelope,
)

DETAIL = f"{DATA_ENTITIES}3/"


def entity(pk=3, key="hotel-paris", **fields):
    """One row exactly as the route sends it."""
    record = {
        "id": pk,
        "key": key,
        "name": key,
        "description": "",
        "metadata": None,
        "origin": "sdk",
        "first_seen_at": "2026-11-02T10:00:00Z",
        "last_seen_at": "2026-11-02T10:00:00Z",
        "is_deleted": False,
        "deleted_at": None,
        "conversation_count": 4,
        "receiving_traffic": False,
        "embed_token_count": 0,
    }
    record.update(fields)
    return record


@pytest.fixture
def me(requests_mock):
    return requests_mock.get(ME, json=IDENTITY)


# -- list -------------------------------------------------------------------


def test_list_walks_the_agents_route_named_by_the_key(ags, me, requests_mock):
    requests_mock.get(DATA_ENTITIES, json=envelope([entity(), entity(4, "hotel-rome")]))

    rows = list(ags.data_entities.list())

    assert [row["key"] for row in rows] == ["hotel-paris", "hotel-rome"]
    assert requests_mock.last_request.path == "/api/agents/7/data-entities/"


def test_list_does_not_touch_the_network_until_iterated(ags, requests_mock):
    ags.data_entities.list()

    assert requests_mock.request_history == []


def test_deleted_rows_are_asked_for_by_name(ags, me, requests_mock):
    requests_mock.get(DATA_ENTITIES, json=envelope([]))

    list(ags.data_entities.list())
    assert "include_deleted" not in requests_mock.last_request.qs

    list(ags.data_entities.list(include_deleted=True))
    assert requests_mock.last_request.qs["include_deleted"] == ["true"]


def test_list_pages_like_every_other_list(ags, me, requests_mock):
    requests_mock.get(
        DATA_ENTITIES,
        [
            {"json": envelope([entity(1, "a")], count=2, total_pages=2, next="more")},
            {"json": envelope([entity(2, "b")], count=2, total_pages=2, current_page=2)},
        ],
    )

    assert [row["key"] for row in ags.data_entities.list()] == ["a", "b"]


def test_the_agent_is_looked_up_once(ags, me, requests_mock):
    requests_mock.get(DETAIL, json=entity())

    ags.data_entities.get(3)
    ags.data_entities.get(3)

    assert me.call_count == 1


# -- get --------------------------------------------------------------------


def test_get_reads_one_row(ags, me, requests_mock):
    requests_mock.get(DETAIL, json=entity())

    assert ags.data_entities.get(3)["key"] == "hotel-paris"
    assert requests_mock.last_request.path == "/api/agents/7/data-entities/3/"


@pytest.mark.parametrize("method", ["get", "delete", "restore"])
@pytest.mark.parametrize("reference", ["hotel-paris", "3", True, None, 3.0])
def test_only_the_pk_names_a_row(ags, requests_mock, method, reference):
    with pytest.raises(ValidationError, match="integer pk"):
        getattr(ags.data_entities, method)(reference)

    assert requests_mock.request_history == []


def test_update_is_also_by_pk(ags, requests_mock):
    with pytest.raises(ValidationError, match="integer pk"):
        ags.data_entities.update("hotel-paris", name="Paris")

    assert requests_mock.request_history == []


def test_a_foreign_or_missing_row_is_not_found(ags, me, requests_mock):
    requests_mock.get(DETAIL, status_code=404, json={"detail": "Not found."})

    with pytest.raises(NotFoundError):
        ags.data_entities.get(3)


def test_an_old_backend_answers_not_found(ags, me, requests_mock):
    requests_mock.get(DATA_ENTITIES, status_code=404, json={"detail": "Not found."})

    with pytest.raises(NotFoundError):
        list(ags.data_entities.list())


# -- create -----------------------------------------------------------------


def test_create_sends_only_what_was_given(ags, me, requests_mock):
    requests_mock.post(DATA_ENTITIES, status_code=201, json=entity(origin="api"))

    assert ags.data_entities.create("hotel-paris")["origin"] == "api"
    assert requests_mock.last_request.json() == {"key": "hotel-paris"}


def test_create_sends_every_field(ags, me, requests_mock):
    requests_mock.post(DATA_ENTITIES, status_code=201, json=entity())

    ags.data_entities.create(
        "  hotel-paris ",
        name="Hotel Paris",
        description="Flagship.",
        metadata={"rooms": 220},
    )

    assert requests_mock.last_request.json() == {
        "key": "hotel-paris",
        "name": "Hotel Paris",
        "description": "Flagship.",
        "metadata": {"rooms": 220},
    }


@pytest.mark.parametrize("key", ["", "   ", None, 42, "x" * 256])
def test_a_bad_key_is_refused_rather_than_changed(ags, requests_mock, key):
    """A key is permanent, and this is the moment someone chooses it, so it is
    not clamped here the way tracking clamps one on the wire."""
    with pytest.raises(ValidationError):
        ags.data_entities.create(key)

    assert requests_mock.request_history == []


def test_the_longest_key_is_accepted(ags, me, requests_mock):
    requests_mock.post(DATA_ENTITIES, status_code=201, json=entity())

    ags.data_entities.create("x" * 255)

    assert requests_mock.last_request.json() == {"key": "x" * 255}


@pytest.mark.parametrize(
    "fields",
    [{"name": 42}, {"name": "x" * 256}, {"description": 42}, {"metadata": "not a dict"}],
)
def test_create_refuses_a_bad_field(ags, requests_mock, fields):
    with pytest.raises(ValidationError):
        ags.data_entities.create("hotel-paris", **fields)

    assert requests_mock.request_history == []


def test_a_duplicate_key_or_full_agent_arrives_as_a_validation_error(ags, me, requests_mock):
    requests_mock.post(
        DATA_ENTITIES, status_code=400, json={"key": ["already exists for this agent"]}
    )

    with pytest.raises(ValidationError) as caught:
        ags.data_entities.create("hotel-paris")

    assert caught.value.errors == {"key": ["already exists for this agent"]}


# -- update -----------------------------------------------------------------


def test_update_sends_the_label_fields(ags, me, requests_mock):
    requests_mock.patch(DETAIL, json=entity(name="Hotel Paris"))

    ags.data_entities.update(
        3, name="Hotel Paris", description="Flagship.", metadata={"rooms": 220}
    )

    assert requests_mock.last_request.method == "PATCH"
    assert requests_mock.last_request.json() == {
        "name": "Hotel Paris",
        "description": "Flagship.",
        "metadata": {"rooms": 220},
    }


def test_an_empty_name_and_description_are_sent(ags, me, requests_mock):
    # An empty name goes back to the key, and an empty description clears it.
    requests_mock.patch(DETAIL, json=entity())

    ags.data_entities.update(3, name="", description="")

    assert requests_mock.last_request.json() == {"name": "", "description": ""}


def test_metadata_none_clears_it(ags, me, requests_mock):
    requests_mock.patch(DETAIL, json=entity())

    ags.data_entities.update(3, metadata=None)

    assert requests_mock.last_request.json() == {"metadata": None}


def test_the_key_cannot_be_updated(ags, requests_mock):
    with pytest.raises(ValidationError, match="permanent"):
        ags.data_entities.update(3, key="hotel-rome")

    assert requests_mock.request_history == []


def test_an_unknown_field_is_refused(ags, requests_mock):
    with pytest.raises(ValidationError, match="Updatable fields"):
        ags.data_entities.update(3, origin="api")

    assert requests_mock.request_history == []


def test_update_needs_something_to_change(ags, requests_mock):
    with pytest.raises(ValidationError, match="at least one"):
        ags.data_entities.update(3)

    assert requests_mock.request_history == []


@pytest.mark.parametrize(
    "fields", [{"name": None}, {"description": None}, {"metadata": "not a dict"}]
)
def test_update_refuses_a_bad_value(ags, requests_mock, fields):
    with pytest.raises(ValidationError):
        ags.data_entities.update(3, **fields)

    assert requests_mock.request_history == []


# -- delete and restore -----------------------------------------------------


def test_delete_is_a_204_with_nothing_to_parse(ags, me, requests_mock):
    requests_mock.delete(DETAIL, status_code=204)

    assert ags.data_entities.delete(3) == {}
    assert requests_mock.last_request.path == "/api/agents/7/data-entities/3/"


def test_restore_posts_to_its_action_and_returns_the_row(ags, me, requests_mock):
    requests_mock.post(f"{DETAIL}restore/", json=entity(is_deleted=False))

    assert ags.data_entities.restore(3)["is_deleted"] is False
    assert requests_mock.last_request.path == "/api/agents/7/data-entities/3/restore/"


def test_restoring_past_the_cap_arrives_as_a_validation_error(ags, me, requests_mock):
    requests_mock.post(
        f"{DETAIL}restore/",
        status_code=400,
        json={"non_field_errors": ["This agent already has the maximum"]},
    )

    with pytest.raises(ValidationError):
        ags.data_entities.restore(3)


# -- me ---------------------------------------------------------------------


def test_me_carries_the_cap_and_refresh_reads_it_again(ags, requests_mock):
    status = {"limit": 500, "active_count": 3, "overflow_count": 0, "overflow_at": None}
    moved = dict(status, active_count=4)
    requests_mock.get(
        ME,
        [
            {"json": dict(IDENTITY, data_entities=status)},
            {"json": dict(IDENTITY, data_entities=moved)},
        ],
    )

    assert ags.me()["data_entities"]["active_count"] == 3
    assert ags.me()["data_entities"]["active_count"] == 3
    assert ags.me(refresh=True)["data_entities"]["active_count"] == 4


# -- the filter pair --------------------------------------------------------


ROUTES = [
    (CONVERSATIONS, lambda ags: ags.conversations, "list"),
    (CONVERSATIONS, lambda ags: ags.conversations, "list_full"),
    (FEEDBACKS, lambda ags: ags.feedbacks, "list"),
    (TICKETS, lambda ags: ags.tickets, "list"),
    (USAGE, lambda ags: ags.usage, "list"),
]


@pytest.mark.parametrize("url, namespace, method", ROUTES)
def test_the_key_filter_reaches_the_route(ags, me, requests_mock, url, namespace, method):
    requests_mock.get(url, json=envelope([]))

    list(getattr(namespace(ags), method)(data_entity="Hotel-Paris"))

    # The backend matches case-insensitively, so the spelling is left alone.
    # (`qs` lowercases what it reports, hence the raw query.)
    assert "data_entity=Hotel-Paris" in requests_mock.last_request.url


@pytest.mark.parametrize("url, namespace, method", ROUTES)
@pytest.mark.parametrize("value, sent", [(True, "true"), (False, "false")])
def test_the_unassigned_filter_reaches_the_route(
    ags, me, requests_mock, url, namespace, method, value, sent
):
    requests_mock.get(url, json=envelope([]))

    list(getattr(namespace(ags), method)(data_entity_unassigned=value))

    assert requests_mock.last_request.qs["data_entity_unassigned"] == [sent]


def test_the_usage_rollup_takes_the_pair_too(ags, me, requests_mock):
    requests_mock.get(USAGE_SUMMARY, json={"group_by": "model", "results": []})

    ags.usage.summary(data_entity="hotel-paris")

    assert requests_mock.last_request.qs["data_entity"] == ["hotel-paris"]


@pytest.mark.parametrize("url, namespace, method", ROUTES)
@pytest.mark.parametrize("blank", ["", "   "])
def test_a_blank_key_filter_is_refused(ags, requests_mock, url, namespace, method, blank):
    """The backend reads it as no filter, so an empty variable would answer
    with every tenant's rows."""
    requests_mock.get(url, json=envelope([]))

    with pytest.raises(ValidationError, match="must not be blank"):
        list(getattr(namespace(ags), method)(data_entity=blank))

    assert requests_mock.request_history == []


# -- a backend that would ignore the filter is never sent it -----------------
#
# A backend that predates data entities drops the parameter and answers with
# every row. From a filter that means every other client's rows, so the client
# asks what the backend supports first and refuses to send what it would ignore.

OLD_BACKEND = dict(IDENTITY, capabilities=["gzip-ingest"])
REFUSED = "does not support data entities"


@pytest.mark.parametrize("url, namespace, method", ROUTES)
@pytest.mark.parametrize(
    "filters", [{"data_entity": "hotel-paris"}, {"data_entity_unassigned": True}]
)
def test_a_backend_without_data_entities_is_never_sent_the_filter(
    ags, requests_mock, url, namespace, method, filters
):
    requests_mock.get(ME, json=OLD_BACKEND)
    route = requests_mock.get(url, json=envelope([{"id": 1}]))

    listing = getattr(namespace(ags), method)(**filters)
    assert requests_mock.request_history == []  # still lazy: nothing asked yet

    with pytest.raises(ValidationError, match=REFUSED):
        list(listing)
    assert route.call_count == 0


def test_page_count_and_first_are_refused_the_same_way(ags, requests_mock):
    requests_mock.get(ME, json=OLD_BACKEND)
    route = requests_mock.get(CONVERSATIONS, json=envelope([{"id": 1}]))
    listing = ags.conversations.list(data_entity="hotel-paris")

    for read in (listing.page, listing.count, listing.first):
        with pytest.raises(ValidationError, match=REFUSED):
            read()
    with pytest.raises(ValidationError, match=REFUSED):
        ags.feedbacks.page(data_entity="hotel-paris")
    assert route.call_count == 0


def test_the_usage_rollup_is_refused_the_same_way(ags, requests_mock):
    requests_mock.get(ME, json=OLD_BACKEND)
    route = requests_mock.get(USAGE_SUMMARY, json={"results": []})

    with pytest.raises(ValidationError, match=REFUSED):
        ags.usage.summary(data_entity="hotel-paris")
    assert route.call_count == 0


@pytest.mark.parametrize(
    "identity",
    [
        {k: v for k, v in IDENTITY.items() if k != "capabilities"},
        dict(IDENTITY, capabilities=None),
        dict(IDENTITY, capabilities="data-entities"),
        dict(IDENTITY, capabilities={"data-entities": True}),
    ],
)
def test_only_a_listed_capability_counts(ags, requests_mock, identity):
    # The bare string would pass a substring test, and the dict a key test.
    requests_mock.get(ME, json=identity)
    requests_mock.get(CONVERSATIONS, json=envelope([]))

    with pytest.raises(ValidationError, match=REFUSED):
        list(ags.conversations.list(data_entity="hotel-paris"))


def test_a_backend_with_no_identity_route_is_refused(ags, requests_mock):
    # That route is older than the capability list, so it supports none of it.
    requests_mock.get(ME, status_code=404, json={"detail": "Not found."})
    route = requests_mock.get(CONVERSATIONS, json=envelope([]))

    with pytest.raises(ValidationError, match=REFUSED):
        list(ags.conversations.list(data_entity="hotel-paris"))
    assert route.call_count == 0


def test_an_upgrade_under_a_live_client_is_noticed(ags, requests_mock):
    """A client can outlive a backend upgrade. A cached "no" is checked once
    more before a filter is refused on it."""
    identity = requests_mock.get(ME, [{"json": OLD_BACKEND}, {"json": IDENTITY}])
    requests_mock.get(CONVERSATIONS, json=envelope([]))
    assert "data-entities" not in ags.me()["capabilities"]  # cached, from before

    list(ags.conversations.list(data_entity="hotel-paris"))

    assert identity.call_count == 2
    assert "data_entity=hotel-paris" in requests_mock.last_request.url


def test_an_old_backend_costs_one_identity_read_per_refusal(ags, requests_mock):
    identity = requests_mock.get(ME, json=OLD_BACKEND)
    requests_mock.get(CONVERSATIONS, json=envelope([]))

    for expected_reads in (1, 2, 3):
        with pytest.raises(ValidationError, match=REFUSED):
            list(ags.conversations.list(data_entity="hotel-paris"))
        assert identity.call_count == expected_reads


def test_a_supporting_backend_is_asked_once(ags, requests_mock):
    identity = requests_mock.get(ME, json=IDENTITY)
    requests_mock.get(CONVERSATIONS, json=envelope([]))

    list(ags.conversations.list(data_entity="hotel-paris"))
    list(ags.conversations.list(data_entity_unassigned=True))

    assert identity.call_count == 1


def test_a_list_without_the_filter_never_asks(ags, requests_mock):
    # No /api/me/ mock: a request to it would fail this test.
    requests_mock.get(CONVERSATIONS, json=envelope([]))

    list(ags.conversations.list(device="mobile"))

    assert [r.path for r in requests_mock.request_history] == ["/api/conversations/"]


def test_spans_do_not_take_the_pair(ags):
    # No such filter on that route: refused locally rather than widening.
    with pytest.raises(ValidationError, match="unknown span filter"):
        list(ags.spans.list(data_entity="hotel-paris"))


def test_a_conversations_entity_cannot_be_reassigned(ags, requests_mock):
    with pytest.raises(ValidationError, match="cannot update: data_entity"):
        ags.conversations.update("wa-3859", data_entity="hotel-paris")

    assert requests_mock.request_history == []
