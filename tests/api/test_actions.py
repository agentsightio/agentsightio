"""The actions namespace — and the bare-array endpoints."""

import pytest

from agentsight.exceptions import ValidationError
from tests.api.conftest import ACTIONS, envelope

# -- actions ----------------------------------------------------------------


def test_list_actions(ags, requests_mock):
    requests_mock.get(ACTIONS, json=envelope([{"id": 1, "name": "refund"}]))

    assert [a["name"] for a in ags.actions.list()] == ["refund"]


def test_action_logs_come_back_as_a_bare_array(ags, requests_mock):
    # This endpoint is not paginated at all.
    requests_mock.get(f"{ACTIONS}1/logs/", json=[{"id": 9}, {"id": 10}])

    assert ags.actions.logs(1) == [{"id": 9}, {"id": 10}]


def test_create_sets_the_dashboard_facing_fields(ags, requests_mock):
    # The reason this method survives: tracking upserts an Action by name but
    # can never set display_name or description.
    requests_mock.post(ACTIONS, json={"id": 1})

    ags.actions.create("refund", display_name="Issue refund", description="…")

    assert requests_mock.last_request.json() == {
        "name": "refund",
        "display_name": "Issue refund",
        "description": "…",
    }


@pytest.mark.parametrize("bad", ["", "   ", None, 7])
def test_create_needs_a_name(ags, bad):
    with pytest.raises(ValidationError):
        ags.actions.create(bad)


def test_update(ags, requests_mock):
    requests_mock.patch(f"{ACTIONS}1/", json={})

    ags.actions.update(1, display_name="Issue refund")

    assert requests_mock.last_request.json() == {"display_name": "Issue refund"}


def test_update_refuses_unknown_fields(ags):
    with pytest.raises(ValidationError):
        ags.actions.update(1, agent=2)


def test_delete(ags, requests_mock):
    requests_mock.delete(f"{ACTIONS}1/", status_code=204, text="")

    assert ags.actions.delete(1) == {}


# -- filters ----------------------------------------------------------------


def test_filters_reach_the_wire(ags, requests_mock):
    requests_mock.get(ACTIONS, json=envelope([]))

    list(ags.actions.list(name__icontains="ref", display_name="Refund", search="r"))

    query = requests_mock.last_request.qs
    assert query["name__icontains"] == ["ref"]
    assert query["display_name"] == ["refund"]  # qs lowercases values
    assert query["search"] == ["r"]


def test_agent_is_not_a_filter(ags):
    # An API key is bound to one agent and the scoping runs before any filter,
    # so `agent` could only ever be a no-op or a contradiction. Refusing it
    # locally is the point of the filter set.
    with pytest.raises(ValidationError, match="agent"):
        list(ags.actions.list(agent=2))


# -- buttons ----------------------------------------------------------------


def test_there_is_no_buttons_namespace(ags):
    # agentsight.button() writes to the span archive, but nothing projects
    # those clicks into a readable table — so a buttons.list() here would
    # return an empty page for every caller and read as "no clicks" rather
    # than "not surfaced yet".
    assert not hasattr(ags, "buttons")
