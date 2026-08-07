"""The feedbacks namespace."""

import pytest

from agentsight.exceptions import ValidationError
from tests.api.conftest import BASE, FEEDBACKS, envelope


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

    ags.feedbacks.create_for_agent(7, "positive", environment="production")

    assert requests_mock.last_request.json() == {
        "kind": "agent",
        "agent": 7,
        "sentiment": "positive",
        "environment": "production",
    }


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

    list(ags.feedbacks.list(sentiment="negative", has_ticket=True, kind="conversation"))

    qs = requests_mock.last_request.qs
    assert qs["sentiment"] == ["negative"]
    assert qs["has_ticket"] == ["true"]
    assert qs["kind"] == ["conversation"]


def test_an_unknown_filter_is_refused(ags):
    with pytest.raises(ValidationError):
        ags.feedbacks.list(sentimnet="negative")


def test_page_exposes_the_counts_block(ags, requests_mock):
    # The only place these totals are published.
    requests_mock.get(
        FEEDBACKS,
        json=envelope([], counts={"all": 12, "open_tickets": 3, "done": 9}),
    )

    page = ags.feedbacks.page()

    assert page.extra["counts"]["open_tickets"] == 3


def test_get(ags, requests_mock):
    requests_mock.get(f"{FEEDBACKS}5/", json={"id": 5, "sentiment": "positive"})

    assert ags.feedbacks.get(5)["sentiment"] == "positive"


# -- writing ----------------------------------------------------------------


def test_update(ags, requests_mock):
    requests_mock.patch(f"{FEEDBACKS}5/", json={})

    ags.feedbacks.update(5, comment="on reflection, fine")

    assert requests_mock.last_request.json() == {"comment": "on reflection, fine"}


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
