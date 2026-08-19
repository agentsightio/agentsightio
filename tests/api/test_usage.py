"""The usage namespace — token spend, and what it cost."""

import pytest

from agentsight.exceptions import ValidationError
from tests.api.conftest import USAGE, USAGE_SUMMARY, envelope

SUMMARY = {
    "group_by": "model",
    "currency": "EUR",
    "results": [
        {"group": "gpt-4o", "total_tokens": 34230, "cost_usd": "3.00000000",
         "cost_eur": "2.40000000", "calls": 12, "rows": 9, "prompt_tokens": 18320},
    ],
}


# -- list -------------------------------------------------------------------


def test_list_walks_the_envelope(ags, requests_mock):
    requests_mock.get(USAGE, json=envelope([{"id": 1, "model": "gpt-4o"}]))

    assert [row["model"] for row in ags.usage.list()] == ["gpt-4o"]


def test_environment_is_not_rewritten_to_env(ags, requests_mock):
    # The conversation and feedback routes call this filter `env`; this one
    # calls it `environment` and does not answer to `env`. Sending the wrong
    # name is silently ignored server-side, which returns MORE rows than were
    # asked for — the exact failure the filter sets exist to prevent.
    requests_mock.get(USAGE, json=envelope([]))

    list(ags.usage.list(environment="production"))

    query = requests_mock.last_request.qs
    assert query["environment"] == ["production"]
    assert "env" not in query


def test_filters_reach_the_wire(ags, requests_mock):
    requests_mock.get(USAGE, json=envelope([]))

    list(ags.usage.list(model="gpt-4o", turn_id="t-1", incomplete=False))

    query = requests_mock.last_request.qs
    assert query["model"] == ["gpt-4o"]
    assert query["turn_id"] == ["t-1"]
    assert query["incomplete"] == ["false"]  # Django reads the lowercase string


def test_an_unknown_filter_is_refused(ags):
    with pytest.raises(ValidationError, match="cost"):
        ags.usage.list(cost="lots")


def test_an_invalid_cost_source_is_refused_locally(ags):
    with pytest.raises(ValidationError, match="cost_source"):
        ags.usage.list(cost_source="guessed")


@pytest.mark.parametrize("source", ["backend", "reported", "unpriced"])
def test_every_real_cost_source_is_accepted(ags, requests_mock, source):
    requests_mock.get(USAGE, json=envelope([]))

    list(ags.usage.list(cost_source=source))

    assert requests_mock.last_request.qs["cost_source"] == [source]


# -- summary ----------------------------------------------------------------


def test_summary_returns_the_envelope_untouched(ags, requests_mock):
    # Not a page: no count, no next, and walking it would be meaningless.
    requests_mock.get(USAGE_SUMMARY, json=SUMMARY)

    assert ags.usage.summary() == SUMMARY


def test_summary_defaults_to_grouping_by_model_in_usd(ags, requests_mock):
    requests_mock.get(USAGE_SUMMARY, json=SUMMARY)

    ags.usage.summary()

    query = requests_mock.last_request.qs
    assert query["group_by"] == ["model"]
    assert query["currency"] == ["usd"]


def test_summary_honours_the_same_filters_as_list(ags, requests_mock):
    # A summary must never cover rows the matching list() would not have shown.
    requests_mock.get(USAGE_SUMMARY, json=SUMMARY)

    ags.usage.summary("day", currency="eur", model="gpt-4o", environment="production")

    query = requests_mock.last_request.qs
    assert query["group_by"] == ["day"]
    assert query["currency"] == ["eur"]
    assert query["model"] == ["gpt-4o"]
    assert query["environment"] == ["production"]


@pytest.mark.parametrize("bad", ["agent", "hour", "", "MODEL"])
def test_an_invalid_group_by_is_refused_locally(ags, bad):
    with pytest.raises(ValidationError, match="group_by"):
        ags.usage.summary(bad)


@pytest.mark.parametrize("bad", ["gbp", "USD", ""])
def test_an_invalid_currency_is_refused_locally(ags, bad):
    with pytest.raises(ValidationError, match="currency"):
        ags.usage.summary(currency=bad)


def test_a_missing_exchange_rate_omits_cost_eur_rather_than_zeroing_it(
    ags, requests_mock
):
    # A missing rate is "unknown", not "free" — and the client must not invent
    # the key, because a caller doing `row.get("cost_eur", 0)` would then be
    # reporting a month of spend as nothing.
    requests_mock.get(USAGE_SUMMARY, json={
        "group_by": "model", "currency": "EUR",
        "results": [{"group": "gpt-4o", "cost_usd": "3.00000000", "calls": 2}],
    })

    row = ags.usage.summary(currency="eur")["results"][0]

    assert "cost_eur" not in row
    assert row["cost_usd"] == "3.00000000"


# -- write surface ----------------------------------------------------------


def test_usage_is_read_only(ags):
    # Rows are written by the tracking SDK from what each provider reported.
    for method in ("create", "update", "delete"):
        assert not hasattr(ags.usage, method)
