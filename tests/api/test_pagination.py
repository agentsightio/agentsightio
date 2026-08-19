"""Walking list endpoints, across both response shapes the backend uses."""


from agentsight.api._pagination import MAX_PAGE_SIZE, Page, PageIterator
from tests.api.conftest import CONVERSATIONS, conversation, envelope

# -- Page -------------------------------------------------------------------


def test_the_seven_key_envelope_is_unpacked():
    page = Page.from_response(
        envelope([{"id": 1}], count=137, total_pages=10, current_page=2, next="?page=3")
    )

    assert page.count == 137
    assert page.total_pages == 10
    assert page.current_page == 2
    assert page.next == "?page=3"
    assert list(page) == [{"id": 1}]


def test_a_bare_array_becomes_a_single_page():
    # buttons/stats/, actions/{pk}/logs/ and every pagination_class = None view.
    page = Page.from_response([{"button_event": "cta", "count": 4}])

    assert len(page) == 1
    assert page.count == 1
    assert page.next is None


def test_per_endpoint_envelope_extras_are_kept():
    # `counts` on the feedback lists is published nowhere else.
    page = Page.from_response(envelope([], counts={"all": 12, "open": 3}))

    assert page.extra["counts"] == {"all": 12, "open": 3}


def test_envelope_keys_do_not_leak_into_extra():
    page = Page.from_response(envelope([{"id": 1}]))

    assert page.extra == {}


def test_a_lone_object_is_not_lost():
    page = Page.from_response({"id": 7})

    assert page.results == [{"id": 7}]


# -- PageIterator -----------------------------------------------------------


def test_nothing_is_fetched_until_iteration(ags, requests_mock):
    requests_mock.get(CONVERSATIONS, json=envelope([]))

    ags.conversations.list()

    assert requests_mock.call_count == 0


def test_iteration_flattens_across_pages(ags, requests_mock):
    requests_mock.get(
        CONVERSATIONS,
        [
            {
                "json": envelope(
                    [conversation(1, "a"), conversation(2, "b")],
                    count=3,
                    total_pages=2,
                    current_page=1,
                    next=f"{CONVERSATIONS}?page=2",
                )
            },
            {
                "json": envelope(
                    [conversation(3, "c")], count=3, total_pages=2, current_page=2
                )
            },
        ],
    )

    ids = [c["conversation_id"] for c in ags.conversations.list()]

    assert ids == ["a", "b", "c"]
    assert requests_mock.call_count == 2


def test_paging_increments_page_rather_than_following_next(ags, requests_mock):
    # The envelope's `next` is an absolute URL the server built from whatever
    # host header it saw; going through the transport keeps auth and retries.
    requests_mock.get(
        CONVERSATIONS,
        [
            {
                "json": envelope(
                    [conversation(1)],
                    total_pages=2,
                    current_page=1,
                    next="http://an-internal-host:8000/api/conversations/?page=2",
                )
            },
            {"json": envelope([conversation(2)], total_pages=2, current_page=2)},
        ],
    )

    list(ags.conversations.list())

    assert requests_mock.request_history[1].qs["page"] == ["2"]
    assert requests_mock.request_history[1].netloc == "api.test.agentsight.io"


def test_iteration_stops_when_next_is_none(ags, requests_mock):
    requests_mock.get(CONVERSATIONS, json=envelope([conversation(1)]))

    assert len(list(ags.conversations.list())) == 1
    assert requests_mock.call_count == 1


def test_iteration_stops_at_total_pages_even_if_next_lies(ags, requests_mock):
    requests_mock.get(
        CONVERSATIONS,
        json=envelope(
            [conversation(1)], total_pages=1, current_page=1, next="?page=2"
        ),
    )

    assert len(list(ags.conversations.list())) == 1
    assert requests_mock.call_count == 1


def test_an_empty_page_ends_the_walk(ags, requests_mock):
    requests_mock.get(CONVERSATIONS, json=envelope([], next="?page=2", total_pages=9))

    assert list(ags.conversations.list()) == []
    assert requests_mock.call_count == 1


def test_page_size_defaults_to_the_backend_maximum(ags, requests_mock):
    requests_mock.get(CONVERSATIONS, json=envelope([]))

    list(ags.conversations.list())

    assert requests_mock.last_request.qs["page_size"] == [str(MAX_PAGE_SIZE)]


def test_page_size_above_the_maximum_is_clamped(ags, requests_mock, caplog):
    requests_mock.get(CONVERSATIONS, json=envelope([]))

    iterator = PageIterator(
        lambda q: ags._request("GET", "/api/conversations/", params=q), page_size=5000
    )
    iterator.page(1)

    assert requests_mock.last_request.qs["page_size"] == [str(MAX_PAGE_SIZE)]
    assert "exceeds the backend maximum" in caplog.text


def test_page_reads_count_without_walking_everything(ags, requests_mock):
    requests_mock.get(
        CONVERSATIONS, json=envelope([conversation(1)], count=4210, total_pages=43)
    )

    page = ags.conversations.list().page()

    assert page.count == 4210
    assert requests_mock.call_count == 1


def test_count_helper_fetches_one_page(ags, requests_mock):
    requests_mock.get(CONVERSATIONS, json=envelope([conversation(1)], count=99))

    assert ags.conversations.list().count() == 99
    assert requests_mock.call_count == 1


def test_first_stops_after_one_record(ags, requests_mock):
    requests_mock.get(
        CONVERSATIONS,
        json=envelope([conversation(1, "a"), conversation(2, "b")], next="?page=2"),
    )

    assert ags.conversations.list().first()["conversation_id"] == "a"
    assert requests_mock.call_count == 1


def test_first_on_an_empty_result_is_none(ags, requests_mock):
    requests_mock.get(CONVERSATIONS, json=envelope([]))

    assert ags.conversations.list().first() is None


def test_pages_yields_page_objects(ags, requests_mock):
    requests_mock.get(CONVERSATIONS, json=envelope([conversation(1)], count=1))

    pages = list(ags.conversations.list().pages())

    assert len(pages) == 1
    assert isinstance(pages[0], Page)


def test_paginate_false_is_never_sent(ags, requests_mock):
    # It returns the whole result set as one unbounded array.
    requests_mock.get(CONVERSATIONS, json=envelope([]))

    list(ags.conversations.list())

    assert "paginate" not in requests_mock.last_request.qs
