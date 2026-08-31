"""The feedbacks namespace."""

import pytest

from agentsight.exceptions import ValidationError
from tests.api.conftest import BASE, FEEDBACKS, IDENTITY, ME, envelope


def test_create_uses_the_unified_route_not_the_deprecated_one(ags, requests_mock):
    # /api/conversation-feedbacks/ is marked for deletion server-side.
    unified = requests_mock.post(FEEDBACKS, json={"id": 1})
    legacy = requests_mock.post(f"{BASE}/api/conversation-feedbacks/", json={"id": 1})

    ags.feedbacks.create_for_conversation("wa-3859", "positive")

    assert unified.call_count == 1
    assert legacy.call_count == 0


def test_conversation_feedback_sends_the_kind_and_the_business_id(ags, requests_mock):
    requests_mock.post(FEEDBACKS, json={"id": 1})

    ags.feedbacks.create_for_conversation("wa-3859", "negative", comment="slow")

    assert requests_mock.last_request.json() == {
        "kind": "conversation",
        "sentiment": "negative",
        "conversation_id": "wa-3859",
        "comment": "slow",
    }


def test_conversation_feedback_by_pk_uses_the_other_field(ags, requests_mock):
    requests_mock.post(FEEDBACKS, json={"id": 1})

    ags.feedbacks.create_for_conversation(42, "positive")

    body = requests_mock.last_request.json()
    assert body["conversation"] == 42
    assert "conversation_id" not in body


def test_conversation_feedback_needs_no_id_resolution(ags, requests_mock):
    # The backend resolves the business id itself on this route.
    requests_mock.post(FEEDBACKS, json={"id": 1})

    ags.feedbacks.create_for_conversation("wa-3859", "positive")

    assert requests_mock.call_count == 1


def test_agent_feedback_carries_the_environment_slug(ags, requests_mock):
    requests_mock.post(FEEDBACKS, json={"id": 1})

    ags.feedbacks.create_for_agent("positive", agent=7, environment="production")

    assert requests_mock.last_request.json() == {
        "kind": "agent",
        "agent": 7,
        "sentiment": "positive",
        "environment": "production",
    }


def test_agent_feedback_resolves_its_own_agent(ags, requests_mock):
    # The whole point of /api/me/: a key writes to exactly one agent, so
    # naming its pk was redundant — and the pk used to be discoverable only
    # as a side effect of listing conversations.
    requests_mock.get(ME, json=IDENTITY)
    requests_mock.post(FEEDBACKS, json={"id": 1})

    ags.feedbacks.create_for_agent("positive")

    assert requests_mock.last_request.json()["agent"] == IDENTITY["agent_id"]


def test_the_agent_lookup_happens_once(ags, requests_mock):
    requests_mock.get(ME, json=IDENTITY)
    requests_mock.post(FEEDBACKS, json={"id": 1})

    ags.feedbacks.create_for_agent("positive")
    ags.feedbacks.create_for_agent("negative")

    assert len(requests_mock.request_history) == 3  # one GET, two POSTs


def test_conversation_feedback_cannot_carry_an_environment(ags):
    # The backend rejects it on this kind, which is why the two kinds are
    # separate methods rather than one create(kind=...).
    with pytest.raises(TypeError):
        ags.feedbacks.create_for_conversation("wa-3859", "positive", environment="prod")


def test_no_method_takes_metadata(ags):
    # 0.0.x sent it and the backend silently discarded it.
    with pytest.raises(TypeError):
        ags.feedbacks.create_for_conversation("wa-3859", "positive", metadata={"a": 1})


def test_product_feedback_has_no_method(ags):
    # Staff-only server-side; triple-guarded against API keys.
    assert not hasattr(ags.feedbacks, "create_for_product")


def test_message_feedback_sends_the_kind_and_the_slugs(ags, requests_mock):
    requests_mock.post(FEEDBACKS, json={"id": 1})

    ags.feedbacks.create_for_message(
        4821, "negative", comment="loud", topic="style", reason="too_bold"
    )

    assert requests_mock.last_request.json() == {
        "kind": "message",
        "message": 4821,
        "sentiment": "negative",
        "comment": "loud",
        "topic": "style",
        "reason": "too_bold",
    }


def test_message_feedback_omits_unset_optionals(ags, requests_mock):
    requests_mock.post(FEEDBACKS, json={"id": 1})

    ags.feedbacks.create_for_message(4821, "positive")

    assert requests_mock.last_request.json() == {
        "kind": "message",
        "message": 4821,
        "sentiment": "positive",
    }


@pytest.mark.parametrize("bad", [None, "4821", 3.5, True])
def test_a_nonsense_message_reference_is_refused(ags, requests_mock, bad):
    # int pk only — messages have no string alias, and True is an int
    # subclass that would silently target pk 1.
    requests_mock.post(FEEDBACKS, json={"id": 1})

    with pytest.raises(ValidationError):
        ags.feedbacks.create_for_message(bad, "positive")

    assert requests_mock.call_count == 0


def test_message_feedback_cannot_carry_an_environment(ags):
    # Derived from the message's conversation server-side, same as
    # conversation-kind — so no method parameter either.
    with pytest.raises(TypeError):
        ags.feedbacks.create_for_message(4821, "positive", environment="prod")


@pytest.mark.parametrize("bad", ["", None, "grumpy"])
def test_an_invalid_sentiment_is_refused_locally(ags, bad):
    with pytest.raises(ValidationError):
        ags.feedbacks.create_for_conversation("wa-3859", bad)


@pytest.mark.parametrize("bad", [None, 3.5, True, ""])
def test_a_nonsense_conversation_reference_is_refused(ags, bad):
    with pytest.raises(ValidationError):
        ags.feedbacks.create_for_conversation(bad, "positive")


# -- reading ----------------------------------------------------------------


def test_list_filters(ags, requests_mock):
    requests_mock.get(FEEDBACKS, json=envelope([]))

    list(ags.feedbacks.list(sentiment="negative", has_comment=True, kind="conversation"))

    qs = requests_mock.last_request.qs
    assert qs["sentiment"] == ["negative"]
    assert qs["has_comment"] == ["true"]
    assert qs["kind"] == ["conversation"]


def test_include_tickets_reaches_the_wire(ags, requests_mock):
    # The gate to the feedback ticket surface: it both narrows (only promoted
    # rows come back) and includes (each row carries `ticket` at full depth).
    requests_mock.get(FEEDBACKS, json=envelope([]))

    list(ags.feedbacks.list(include_tickets=True))

    assert requests_mock.last_request.qs["include_tickets"] == ["true"]


def test_ticket_filters_pass_through_alongside_the_gate(ags, requests_mock):
    # ticket_status accepts a list and ORs it — sent as repeated keys, which
    # is how django-filter's MultipleChoiceFilter reads it.
    requests_mock.get(FEEDBACKS, json=envelope([]))

    list(ags.feedbacks.list(
        include_tickets=True, has_ticket=True,
        ticket_status=["open", "in_progress"],
    ))

    qs = requests_mock.last_request.qs
    assert qs["has_ticket"] == ["true"]
    assert qs["ticket_status"] == ["open", "in_progress"]


def test_message_filters_reach_the_wire(ags, requests_mock):
    requests_mock.get(FEEDBACKS, json=envelope([]))

    list(ags.feedbacks.list(kind="message", message=4821, topic="style", reason="too_bold"))

    qs = requests_mock.last_request.qs
    assert qs["message"] == ["4821"]
    assert qs["topic"] == ["style"]
    assert qs["reason"] == ["too_bold"]


def test_an_unknown_filter_is_refused(ags):
    with pytest.raises(ValidationError):
        ags.feedbacks.list(sentimnet="negative")


def test_page_exposes_the_counts_block(ags, requests_mock):
    # Without include_tickets this collapses to {"all": N}; `extra` passes the
    # envelope through generically, so nothing here has to track its shape.
    requests_mock.get(FEEDBACKS, json=envelope([], counts={"all": 12}))

    page = ags.feedbacks.page()

    assert page.extra["counts"] == {"all": 12}


def test_page_carries_the_ticket_aggregates_behind_the_gate(ags, requests_mock):
    # With include_tickets=True the per-status tallies arrive alongside `all`
    # (actions/closed/015 reversed their removal). Still pure pass-through.
    counts = {"all": 3, "tickets": 3, "open_tickets": 2, "open": 1, "in_progress": 1, "done": 1}
    requests_mock.get(FEEDBACKS, json=envelope([], counts=counts))

    page = ags.feedbacks.page(include_tickets=True)

    assert page.extra["counts"] == counts
    assert requests_mock.last_request.qs["include_tickets"] == ["true"]


def test_get(ags, requests_mock):
    requests_mock.get(f"{FEEDBACKS}5/", json={"id": 5, "sentiment": "positive"})

    assert ags.feedbacks.get(5)["sentiment"] == "positive"


# -- writing ----------------------------------------------------------------


def test_update(ags, requests_mock):
    requests_mock.patch(f"{FEEDBACKS}5/", json={})

    ags.feedbacks.update(5, comment="on reflection, fine")

    assert requests_mock.last_request.json() == {"comment": "on reflection, fine"}


def test_update_accepts_the_slugs_and_drops_none(ags, requests_mock):
    # None values never reach the wire, so update() can replace a slug but
    # never clear one — documented on the method.
    requests_mock.patch(f"{FEEDBACKS}5/", json={})

    ags.feedbacks.update(5, topic="fit", reason=None)

    assert requests_mock.last_request.json() == {"topic": "fit"}


def test_update_validates_sentiment(ags):
    with pytest.raises(ValidationError):
        ags.feedbacks.update(5, sentiment="grumpy")


def test_update_refuses_unknown_fields(ags):
    with pytest.raises(ValidationError):
        ags.feedbacks.update(5, kind="agent")


def test_update_needs_a_field(ags):
    with pytest.raises(ValidationError):
        ags.feedbacks.update(5)


def test_delete(ags, requests_mock):
    requests_mock.delete(f"{FEEDBACKS}5/", status_code=204, text="")

    assert ags.feedbacks.delete(5) == {}
