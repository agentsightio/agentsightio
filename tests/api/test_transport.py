"""The shared transport: auth, URL joining, retries and error mapping."""

import pytest
import requests

from agentsight._settings import USER_AGENT
from agentsight._transport import Transport
from agentsight.api import AgentSight
from agentsight.exceptions import (
    APIError,
    AuthenticationError,
    InvalidApiKeyError,
    MethodNotAllowedError,
    MissingApiKeyError,
    NetworkError,
    NotFoundError,
    PermissionDeniedError,
    ServerError,
    SubscriptionInactiveError,
    ValidationError,
)
from tests.api.conftest import BASE, CONVERSATIONS
from tests.conftest import VALID_API_KEY


@pytest.fixture
def transport():
    t = Transport(VALID_API_KEY, BASE, max_retries=3)
    yield t
    t.close()


# -- headers and URLs -------------------------------------------------------


def test_sends_the_api_key_with_the_literal_keyword(transport, requests_mock):
    requests_mock.get(CONVERSATIONS, json={})
    transport.request("GET", "/api/conversations/")

    assert requests_mock.last_request.headers["Authorization"] == f"Api-Key {VALID_API_KEY}"


def test_asks_for_json_so_the_browsable_renderer_stays_out_of_the_way(
    transport, requests_mock
):
    requests_mock.get(CONVERSATIONS, json={})
    transport.request("GET", "/api/conversations/")

    assert requests_mock.last_request.headers["Accept"] == "application/json"
    assert requests_mock.last_request.headers["User-Agent"] == USER_AGENT


def test_a_trailing_slash_on_the_endpoint_does_not_double_up(requests_mock):
    requests_mock.get(CONVERSATIONS, json={})
    trailing = Transport(VALID_API_KEY, BASE + "/")
    try:
        trailing.request("GET", "/api/conversations/")
    finally:
        trailing.close()

    assert "//api/" not in requests_mock.last_request.url
    assert requests_mock.last_request.path == "/api/conversations/"


def test_path_trailing_slash_is_preserved(transport, requests_mock):
    # APPEND_SLASH is off on the backend, so this is load-bearing.
    requests_mock.get(CONVERSATIONS, json={})
    transport.request("GET", "/api/conversations/")

    assert requests_mock.last_request.path == "/api/conversations/"


# -- success ----------------------------------------------------------------


@pytest.mark.parametrize("status", [200, 201, 202, 204])
def test_success_statuses_return_the_body(transport, requests_mock, status):
    requests_mock.get(CONVERSATIONS, status_code=status, json={"ok": True})

    assert transport.request("GET", "/api/conversations/") == {"ok": True}


def test_an_empty_body_is_an_empty_dict(transport, requests_mock):
    requests_mock.delete(CONVERSATIONS, status_code=204, text="")

    assert transport.request("DELETE", "/api/conversations/") == {}


def test_a_non_json_body_does_not_explode(transport, requests_mock):
    requests_mock.get(CONVERSATIONS, status_code=200, text="<html>nope</html>")

    assert transport.request("GET", "/api/conversations/") == {}


# -- error mapping ----------------------------------------------------------


@pytest.mark.parametrize(
    "status,expected",
    [
        (400, ValidationError),
        (401, AuthenticationError),
        (403, PermissionDeniedError),
        (404, NotFoundError),
        (405, MethodNotAllowedError),
        (409, APIError),
        (500, ServerError),
        (503, ServerError),
    ],
)
def test_status_codes_map_to_the_taxonomy(transport, requests_mock, status, expected):
    requests_mock.post(CONVERSATIONS, status_code=status, json={"detail": "nope"})

    with pytest.raises(expected) as excinfo:
        transport.request("POST", "/api/conversations/")

    assert excinfo.value.status_code == status
    assert excinfo.value.detail == "nope"


def test_a_400_carrying_detail_is_still_a_validation_error(transport, requests_mock):
    # This backend raises ValidationError({"detail": ...}) all over the place,
    # so classifying on the body rather than the status would get it wrong.
    requests_mock.get(
        CONVERSATIONS, status_code=400, json={"detail": "Must provide agent."}
    )

    with pytest.raises(ValidationError) as excinfo:
        transport.request("GET", "/api/conversations/")

    assert excinfo.value.detail == "Must provide agent."


def test_a_field_map_is_flattened_into_the_message_and_kept_on_errors(
    transport, requests_mock
):
    requests_mock.post(
        CONVERSATIONS,
        status_code=400,
        json={"name": ["This field is required."], "sentiment": ["Invalid."]},
    )

    with pytest.raises(ValidationError) as excinfo:
        transport.request("POST", "/api/conversations/")

    assert "name: This field is required." in excinfo.value.detail
    assert excinfo.value.errors["sentiment"] == ["Invalid."]


def test_the_hand_rolled_error_key_is_read_too(transport, requests_mock):
    # /api/attachments/ and /api/buttons/ answer with {"error": ...}.
    requests_mock.post(
        CONVERSATIONS, status_code=400, json={"error": "No attachment files found"}
    )

    with pytest.raises(ValidationError) as excinfo:
        transport.request("POST", "/api/conversations/")

    assert excinfo.value.detail == "No attachment files found"


def test_an_unparseable_error_body_falls_back_to_text(transport, requests_mock):
    requests_mock.get(CONVERSATIONS, status_code=502, text="upstream is unwell")

    with pytest.raises(ServerError) as excinfo:
        transport.request("GET", "/api/conversations/")

    assert "upstream is unwell" in excinfo.value.detail


# -- the four 401s ----------------------------------------------------------


@pytest.mark.parametrize(
    "detail",
    [
        "Invalid API key.",
        "API key is inactive, expired or revoked.",
        "API key is not linked to any agent.",
    ],
)
def test_credential_401s_are_authentication_errors(transport, requests_mock, detail):
    requests_mock.get(CONVERSATIONS, status_code=401, json={"detail": detail})

    with pytest.raises(AuthenticationError) as excinfo:
        transport.request("GET", "/api/conversations/")

    assert not isinstance(excinfo.value, SubscriptionInactiveError)
    assert excinfo.value.detail == detail


def test_the_billing_401_gets_its_own_class(transport, requests_mock):
    # The one 401 that rotating a key will not fix.
    requests_mock.get(
        CONVERSATIONS,
        status_code=401,
        json={"detail": "Agent does not have an active subscription or development phase."},
    )

    with pytest.raises(SubscriptionInactiveError):
        transport.request("GET", "/api/conversations/")


def test_an_unrecognised_401_degrades_rather_than_breaking(transport, requests_mock):
    requests_mock.get(CONVERSATIONS, status_code=401, json={"detail": "Some new copy."})

    with pytest.raises(AuthenticationError):
        transport.request("GET", "/api/conversations/")


# -- retries ----------------------------------------------------------------


def test_a_get_retries_a_5xx_and_succeeds(transport, requests_mock, monkeypatch):
    monkeypatch.setattr("agentsight._transport.time.sleep", lambda _: None)
    requests_mock.get(
        CONVERSATIONS,
        [
            {"status_code": 503, "json": {}},
            {"status_code": 200, "json": {"ok": True}},
        ],
    )

    assert transport.request("GET", "/api/conversations/") == {"ok": True}
    assert requests_mock.call_count == 2


def test_a_get_gives_up_after_max_retries(transport, requests_mock, monkeypatch):
    monkeypatch.setattr("agentsight._transport.time.sleep", lambda _: None)
    requests_mock.get(CONVERSATIONS, status_code=503, json={})

    with pytest.raises(ServerError):
        transport.request("GET", "/api/conversations/")

    assert requests_mock.call_count == 3


def test_a_get_retries_network_errors(transport, requests_mock, monkeypatch):
    monkeypatch.setattr("agentsight._transport.time.sleep", lambda _: None)
    requests_mock.get(
        CONVERSATIONS,
        [
            {"exc": requests.ConnectionError},
            {"status_code": 200, "json": {"ok": True}},
        ],
    )

    assert transport.request("GET", "/api/conversations/") == {"ok": True}


def test_exhausted_network_retries_raise_network_error(
    transport, requests_mock, monkeypatch
):
    monkeypatch.setattr("agentsight._transport.time.sleep", lambda _: None)
    requests_mock.get(CONVERSATIONS, exc=requests.ConnectionError)

    with pytest.raises(NetworkError):
        transport.request("GET", "/api/conversations/")


def test_a_get_never_retries_a_4xx(transport, requests_mock):
    requests_mock.get(CONVERSATIONS, status_code=404, json={})

    with pytest.raises(NotFoundError):
        transport.request("GET", "/api/conversations/")

    assert requests_mock.call_count == 1


@pytest.mark.parametrize("method", ["POST", "PATCH", "PUT", "DELETE"])
def test_no_write_is_ever_retried(transport, requests_mock, method, monkeypatch):
    # POST /api/feedbacks/ is not idempotent and the backend publishes no
    # 429 or Retry-After, so replaying a write is guessing with user data.
    monkeypatch.setattr("agentsight._transport.time.sleep", lambda _: None)
    getattr(requests_mock, method.lower())(CONVERSATIONS, status_code=503, json={})

    with pytest.raises(ServerError):
        transport.request(method, "/api/conversations/")

    assert requests_mock.call_count == 1


def test_a_write_network_failure_raises_immediately(transport, requests_mock):
    requests_mock.post(CONVERSATIONS, exc=requests.ConnectionError)

    with pytest.raises(NetworkError):
        transport.request("POST", "/api/conversations/")

    assert requests_mock.call_count == 1


# -- raw() ------------------------------------------------------------------


def test_raw_hands_back_the_response_without_raising(transport, requests_mock):
    requests_mock.post(CONVERSATIONS, status_code=400, json={"detail": "nope"})

    response = transport.raw("POST", "/api/conversations/")

    assert response.status_code == 400


# -- client construction ----------------------------------------------------


def test_a_missing_key_is_caught_before_any_request():
    with pytest.raises(MissingApiKeyError):
        AgentSight()


def test_a_malformed_key_is_caught_locally():
    with pytest.raises(InvalidApiKeyError):
        AgentSight(api_key="not-a-key")


def test_the_key_is_read_from_the_environment(monkeypatch):
    monkeypatch.setenv("AGENTSIGHT_API_KEY", VALID_API_KEY)
    monkeypatch.setenv("AGENTSIGHT_API_ENDPOINT", BASE)

    with AgentSight() as ags:
        assert ags.endpoint == BASE


def test_an_explicit_key_beats_the_environment(monkeypatch):
    monkeypatch.setenv("AGENTSIGHT_API_KEY", "ags_" + "0" * 32 + "_abcdef")

    with AgentSight(api_key=VALID_API_KEY, endpoint=BASE) as ags:
        assert ags._transport._session.headers["Authorization"].endswith(VALID_API_KEY)


def test_two_clients_hold_two_keys():
    other = "ags_" + "b" * 32 + "_abcdef"

    with AgentSight(api_key=VALID_API_KEY, endpoint=BASE) as one, AgentSight(
        api_key=other, endpoint=BASE
    ) as two:
        assert one is not two
        assert (
            one._transport._session.headers["Authorization"]
            != two._transport._session.headers["Authorization"]
        )


def test_repr_does_not_leak_the_key(ags):
    assert VALID_API_KEY not in repr(ags)
