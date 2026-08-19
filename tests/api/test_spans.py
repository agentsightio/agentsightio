"""The spans namespace — the raw archive, and one trace as a tree."""

import pytest

from agentsight.exceptions import ValidationError
from tests.api.conftest import SPANS, TRACES, envelope, span

TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"

TREE = {
    "trace_id": TRACE_ID,
    "span_count": 3,
    "truncated": False,
    "roots": [
        {
            **span(1, "aaaa0001", name="turn-one"),
            "children": [
                {**span(2, "bbbb0001", kind="llm", name="chat"), "children": []},
                {**span(3, "cccc0001", kind="tool", name="lookup"), "children": []},
            ],
        },
    ],
}


# -- list -------------------------------------------------------------------


def test_list_walks_the_envelope(ags, requests_mock):
    requests_mock.get(SPANS, json=envelope([span(1, name="checkout turn")]))

    assert [row["name"] for row in ags.spans.list()] == ["checkout turn"]


def test_nothing_is_fetched_until_the_iterator_is_walked(ags, requests_mock):
    requests_mock.get(SPANS, json=envelope([]))

    ags.spans.list(kind="tool")

    assert requests_mock.call_count == 0


def test_the_list_never_asks_for_payloads(ags, requests_mock):
    # The point of the route's shape, pinned client-side rather than trusted to
    # the server's default — the conversation list is what happens otherwise.
    requests_mock.get(SPANS, json=envelope([]))

    list(ags.spans.list())

    assert requests_mock.last_request.qs["payload"] == ["false"]


def test_filters_reach_the_wire(ags, requests_mock):
    requests_mock.get(SPANS, json=envelope([]))

    list(ags.spans.list(
        kind="tool", status="error", trace_id=TRACE_ID, conversation_id="wa-3859"
    ))

    query = requests_mock.last_request.qs
    assert query["kind"] == ["tool"]
    assert query["status"] == ["error"]
    assert query["trace_id"] == [TRACE_ID.lower()]  # values arrive lowercased
    assert query["conversation_id"] == ["wa-3859"]


def test_datetimes_are_converted(ags, requests_mock):
    from datetime import datetime

    requests_mock.get(SPANS, json=envelope([]))

    list(ags.spans.list(started_at_after=datetime(2026, 1, 1, 12, 0)))

    assert requests_mock.last_request.qs["started_at_after"] == ["2026-01-01t12:00:00"]


def test_environment_is_not_rewritten_to_env(ags, requests_mock):
    # Like /api/token-usage/, this route spells the filter `environment`. `env`
    # would be silently ignored server-side, returning MORE rows than asked for.
    requests_mock.get(SPANS, json=envelope([]))

    list(ags.spans.list(environment="production"))

    query = requests_mock.last_request.qs
    assert query["environment"] == ["production"]
    assert "env" not in query


def test_an_unknown_filter_is_refused(ags):
    with pytest.raises(ValidationError, match="attributes"):
        ags.spans.list(attributes="agentsight.tool.name:lookup")


def test_a_kind_this_release_has_never_heard_of_is_still_sent(ags, requests_mock):
    # Deliberately no local allowlist: the backend stores whatever kind an SDK
    # sends, so a fixed tuple here would refuse data a newer release produces.
    requests_mock.get(SPANS, json=envelope([]))

    list(ags.spans.list(kind="retrieval"))

    assert requests_mock.last_request.qs["kind"] == ["retrieval"]


# -- get --------------------------------------------------------------------


def test_get_returns_the_row_and_omits_the_payload_by_default(ags, requests_mock):
    requests_mock.get(f"{SPANS}91823/", json=span(91823))

    record = ags.spans.get(91823)

    assert record["id"] == 91823
    assert requests_mock.last_request.qs["payload"] == ["false"]


def test_get_asks_for_the_verbatim_span_when_told_to(ags, requests_mock):
    requests_mock.get(f"{SPANS}91823/", json=span(91823, payload={"verbatim": True}))

    record = ags.spans.get(91823, payload=True)

    assert requests_mock.last_request.qs["payload"] == ["true"]
    assert record["payload"] == {"verbatim": True}


@pytest.mark.parametrize("bad", ["aaaa0001", None, True, 1.5])
def test_get_refuses_anything_that_is_not_a_row_id(ags, bad):
    # `span_id` is the OpenTelemetry identifier and is only unique within a
    # conversation; passing it here would fetch someone else's row or 404.
    with pytest.raises(ValidationError, match="span id"):
        ags.spans.get(bad)


# -- trace ------------------------------------------------------------------


def test_trace_returns_the_tree_untouched(ags, requests_mock):
    # Not a page: no count, no next, and walking it would be meaningless.
    requests_mock.get(f"{TRACES}{TRACE_ID}/", json=TREE)

    assert ags.spans.trace(TRACE_ID) == TREE


def test_trace_nests_children_under_their_parent(ags, requests_mock):
    requests_mock.get(f"{TRACES}{TRACE_ID}/", json=TREE)

    roots = ags.spans.trace(TRACE_ID)["roots"]

    assert [root["name"] for root in roots] == ["turn-one"]
    assert [child["name"] for child in roots[0]["children"]] == ["chat", "lookup"]


def test_a_truncated_trace_says_so(ags, requests_mock):
    # It means spans are MISSING from this tree, not that the trace ended.
    requests_mock.get(f"{TRACES}{TRACE_ID}/", json={**TREE, "truncated": True})

    assert ags.spans.trace(TRACE_ID)["truncated"] is True


@pytest.mark.parametrize("bad", ["", None])
def test_trace_needs_a_trace_id(ags, bad):
    with pytest.raises(ValidationError, match="trace_id"):
        ags.spans.trace(bad)


# -- write surface ----------------------------------------------------------


def test_spans_are_read_only(ags):
    # Rows are written by the exporter and projected server-side; a second way
    # to write one would mean two sets of semantics for how it projects.
    for method in ("create", "update", "delete", "purge"):
        assert not hasattr(ags.spans, method)
