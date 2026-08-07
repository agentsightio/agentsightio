"""The actions and buttons namespaces — and the bare-array endpoints."""

import pytest

from agentsight.exceptions import ValidationError
from tests.api.conftest import ACTIONS, BUTTONS, envelope

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


# -- buttons ----------------------------------------------------------------


def test_button_stats_come_back_as_a_bare_array(ags, requests_mock):
    requests_mock.get(
        f"{BUTTONS}stats/",
        json=[{"button_event": "cta", "value": "buy", "label": "Buy", "count": 12}],
    )

    stats = ags.buttons.stats()

    assert stats[0]["count"] == 12


def test_button_stats_can_be_narrowed_to_one_event(ags, requests_mock):
    requests_mock.get(f"{BUTTONS}stats/", json=[])

    ags.buttons.stats(event="cta")

    assert requests_mock.last_request.qs["event"] == ["cta"]


def test_list_buttons(ags, requests_mock):
    requests_mock.get(BUTTONS, json=envelope([{"id": 1, "button_event": "cta"}]))

    assert [b["button_event"] for b in ags.buttons.list()] == ["cta"]


def test_buttons_are_read_only(ags):
    # Button events are recorded by agentsight.button() on the tracking side.
    for method in ("create", "update", "delete"):
        assert not hasattr(ags.buttons, method)
