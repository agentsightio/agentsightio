"""``init(verify_key=True)`` — finding out the key is dead while someone is watching.

Only the *shape* of an API key can be checked without a network call, and
every other way a key fails looks identical from inside the process: revoked,
inactive subscription, read role where write was needed. All three land in the
exporter's terminal-4xx branch, which drops the batch and warns at most once a
minute — so without this check the failure mode is a healthy-looking process
that never delivers anything.

The preflight is tested by calling ``_verify_key`` directly rather than
through ``init()``. The thread ``init()`` starts is deliberately unjoinable
(daemon, fire-and-forget), and a test that raced it would be the flakiest
thing in the suite.
"""

import logging
import threading

import pytest
import requests

import agentsight as ags
from agentsight import _settings
from agentsight.sdk import core
from tests.conftest import VALID_API_KEY

BASE = "https://api.test.agentsight.io"
ME = f"{BASE}/api/me/"


class _Recorder(logging.Handler):
    """The package logger sets ``propagate = False``, so caplog sees nothing."""

    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record):
        self.records.append(record)

    def messages(self, level):
        return [
            record.getMessage()
            for record in self.records
            if record.levelno == level
        ]


@pytest.fixture
def recorded():
    handler = _Recorder()
    core.logger.addHandler(handler)
    core.logger.setLevel(logging.DEBUG)
    yield handler
    core.logger.removeHandler(handler)


# ---------------------------------------------------------------------------
# What the preflight says
# ---------------------------------------------------------------------------


def test_a_revoked_key_is_reported_as_an_error(recorded, requests_mock):
    requests_mock.get(ME, status_code=401, json={"detail": "unknown key"})

    core._verify_key(VALID_API_KEY, BASE)

    assert any("refused" in m for m in recorded.messages(logging.ERROR))


def test_an_inactive_subscription_says_so_rather_than_blaming_the_key(
    recorded, requests_mock
):
    # Rotating the key would not fix this one, so it must not read as "bad key".
    requests_mock.get(ME, status_code=401,
                      json={"detail": "Your subscription is not active."})

    core._verify_key(VALID_API_KEY, BASE)

    errors = recorded.messages(logging.ERROR)
    assert any("subscription" in m for m in errors)


def test_a_read_key_is_caught_before_the_first_batch_is_refused(
    recorded, requests_mock
):
    # The case nothing else catches: live, valid, and the wrong kind. Ingest
    # takes the write role, so every batch would come back 403.
    requests_mock.get(ME, json={"agent_id": 7, "agent_name": "Support bot",
                                "role": "read", "environments": []})

    core._verify_key(VALID_API_KEY, BASE)

    errors = recorded.messages(logging.ERROR)
    assert any("read role" in m and "Support bot" in m for m in errors)


def test_a_write_key_says_nothing_at_error_level(recorded, requests_mock):
    requests_mock.get(ME, json={"agent_id": 7, "agent_name": "Support bot",
                                "role": "write", "environments": []})

    core._verify_key(VALID_API_KEY, BASE)

    assert recorded.messages(logging.ERROR) == []


# ---------------------------------------------------------------------------
# What it deliberately stays quiet about
# ---------------------------------------------------------------------------


def test_a_backend_without_the_route_is_not_an_error(recorded, requests_mock):
    # /api/me/ postdates the ingest endpoint. A 404 says nothing about the key,
    # and an error here would fire on every older deployment.
    requests_mock.get(ME, status_code=404, json={"detail": "not found"})

    core._verify_key(VALID_API_KEY, BASE)

    assert recorded.messages(logging.ERROR) == []


def test_an_unreachable_backend_is_not_an_error(recorded, requests_mock):
    import requests

    requests_mock.get(ME, exc=requests.ConnectionError("no route to host"))

    core._verify_key(VALID_API_KEY, BASE)

    assert recorded.messages(logging.ERROR) == []


def test_an_unreachable_backend_says_nothing_above_debug(recorded, requests_mock):
    """Found live, not in a mock: the shared transport warns before each retry,
    so a preflight against a backend that was merely down announced the outage
    twice at WARNING before concluding "don't know" at DEBUG. A check nobody
    asked for must not be the loudest thing in the log."""
    import requests

    requests_mock.get(ME, exc=requests.ConnectionError("no route to host"))

    core._verify_key(VALID_API_KEY, BASE)

    assert [r.levelname for r in recorded.records if r.levelno > logging.DEBUG] == []


def test_a_failing_preflight_is_tried_once_and_not_retried(recorded, requests_mock):
    # Retrying cannot change the answer, and it kept a daemon thread sleeping
    # through the seconds after init() where a process is most likely to exit.
    import requests

    requests_mock.get(ME, exc=requests.ConnectionError("no route to host"))

    core._verify_key(VALID_API_KEY, BASE)

    assert requests_mock.call_count == 1


def test_it_never_raises_whatever_comes_back(requests_mock):
    # It runs on a thread nobody joins; an exception here would be invisible
    # and would take the thread with it.
    requests_mock.get(ME, status_code=500, text="<html>gateway</html>")

    core._verify_key(VALID_API_KEY, BASE)


def test_a_junk_identity_body_does_not_raise(requests_mock):
    requests_mock.get(ME, json=["not", "a", "dict"])

    core._verify_key(VALID_API_KEY, BASE)


# ---------------------------------------------------------------------------
# What a successful preflight teaches the SDK
# ---------------------------------------------------------------------------


def _me_with_environments(*slugs):
    return {
        "agent_id": 7,
        "agent_name": "Support bot",
        "role": "write",
        "environments": [
            {"id": index, "slug": slug} for index, slug in enumerate(slugs, start=1)
        ],
    }


def test_a_custom_environment_from_the_backend_becomes_acceptable(requests_mock):
    requests_mock.get(
        ME, json=_me_with_environments("production", "development", "local")
    )
    assert _settings.normalize_environment("local") is None  # before it lands

    core._verify_key(VALID_API_KEY, BASE)

    assert _settings.normalize_environment("local") == "local"


def test_an_unlearned_slug_is_still_refused_after_learning(requests_mock):
    # Learning "local" must not open the door to everything else: an unknown
    # slug still 400s the whole batch, so it still has to be dropped locally.
    requests_mock.get(
        ME, json=_me_with_environments("production", "development", "local")
    )

    core._verify_key(VALID_API_KEY, BASE)

    assert _settings.normalize_environment("staging") is None


def test_the_shorthand_still_normalizes_after_learning(requests_mock):
    requests_mock.get(
        ME, json=_me_with_environments("production", "development", "local")
    )

    core._verify_key(VALID_API_KEY, BASE)

    assert _settings.normalize_environment("prod") == "production"
    assert _settings.normalize_environment("dev") == "development"


@pytest.mark.parametrize(
    "identity",
    [
        {"role": "write"},                                # list absent entirely
        {"role": "write", "environments": None},
        {"role": "write", "environments": "production"},  # wrong type
        {"role": "write", "environments": 42},            # not even iterable
        {"role": "write", "environments": [{"id": 1}]},   # rows without slugs
        {"role": "write", "environments": [None, 42, "x"]},
        ["not", "a", "dict"],
    ],
)
def test_a_malformed_environment_list_keeps_the_fallback_pair_quietly(
    recorded, requests_mock, identity
):
    # A backend that shapes /api/me/ differently must not turn a successful
    # preflight into a logged failure, and must not corrupt the allowed set.
    requests_mock.get(ME, json=identity)

    core._verify_key(VALID_API_KEY, BASE)

    assert _settings.allowed_environments() == ("development", "production")
    assert [r for r in recorded.records if r.levelno > logging.DEBUG] == []


def test_an_advertised_capability_is_learned(requests_mock):
    # "gzip-ingest" is what lets the exporter start compressing batches;
    # until the preflight has seen it, it must read as absent.
    identity = _me_with_environments("production", "development")
    identity["capabilities"] = ["gzip-ingest"]
    requests_mock.get(ME, json=identity)
    assert not _settings.has_capability(_settings.GZIP_INGEST)  # before

    core._verify_key(VALID_API_KEY, BASE)

    assert _settings.has_capability(_settings.GZIP_INGEST)


@pytest.mark.parametrize(
    "capabilities",
    [None, 42, {"gzip-ingest": True}, [None, 42, ""], "gzip-ingest"],
)
def test_a_malformed_capability_list_is_tolerated_quietly(
    recorded, requests_mock, capabilities
):
    # Same contract as the environments: an older or differently-shaped
    # backend must not turn a successful preflight into a logged failure —
    # the exporter just keeps sending plain JSON, which always works.
    #
    # The dict and the bare string are the nasty ones: both ARE iterable
    # (keys; characters), so anything but a strict shape check would learn a
    # capability nobody advertised — and that turns into an encoding the
    # backend cannot decode.
    identity = _me_with_environments("production", "development")
    identity["capabilities"] = capabilities
    requests_mock.get(ME, json=identity)

    core._verify_key(VALID_API_KEY, BASE)

    assert not _settings.has_capability(_settings.GZIP_INGEST)
    assert [r for r in recorded.records if r.levelno > logging.DEBUG] == []


@pytest.mark.parametrize(
    "response",
    [
        {"exc": requests.ConnectionError},
        {"status_code": 404, "json": {"detail": "not found"}},
        {"status_code": 500, "text": "<html>gateway</html>"},
        {"status_code": 401, "json": {"detail": "unknown key"}},
    ],
)
def test_a_preflight_that_never_answers_keeps_the_fallback_pair(
    requests_mock, response
):
    requests_mock.get(ME, **response)

    core._verify_key(VALID_API_KEY, BASE)

    assert _settings.allowed_environments() == ("development", "production")


def test_a_custom_default_environment_starts_working_when_the_preflight_lands(
    recorded, requests_mock, monkeypatch
):
    """The race, handled honestly: init(environment="local") resolves before
    the preflight has answered, so init() stores the slug raw and
    default_environment() re-resolves on every read. Early conversations fall
    back to the agent's default; everything after the preflight carries the
    real slug instead of it having been thrown away at startup."""
    requests_mock.get(
        ME, json=_me_with_environments("production", "development", "local")
    )
    core._state.enabled = False
    # The test drives _verify_key itself so there is no thread to race.
    monkeypatch.setattr(core, "_start_key_preflight", lambda *args: None)

    assert ags.init(api_key=VALID_API_KEY, endpoint=BASE, environment="local",
                    auto_instrument=False) is True
    try:
        # Not confirmed yet — and the startup message says what the SDK could
        # confirm, not what the agent has.
        assert core.default_environment() is None
        assert any(
            "confirm" in m and "local" in m
            for m in recorded.messages(logging.ERROR)
        )

        core._verify_key(VALID_API_KEY, BASE)  # the preflight lands

        assert core.default_environment() == "local"
    finally:
        ags.shutdown()


def test_verify_key_false_keeps_the_fallback_pair(monkeypatch):
    # No preflight means no discovery: the documented cost of disabling it.
    core._state.enabled = False

    assert ags.init(api_key=VALID_API_KEY, endpoint=BASE, auto_instrument=False,
                    verify_key=False) is True
    try:
        assert _settings.allowed_environments() == ("development", "production")
    finally:
        ags.shutdown()


def test_normalize_is_safe_while_the_preflight_widens_the_set():
    """No mocks — hammer normalize_environment() from reader threads while
    learn_environments() grows the set. The failure modes are an exception
    ("set changed size during iteration") or the fallback pair transiently
    disappearing mid-update."""
    stop = threading.Event()
    failures = []

    def reader():
        while not stop.is_set():
            try:
                if _settings.normalize_environment("production") != "production":
                    failures.append("production stopped normalizing")
                    return
                _settings.normalize_environment("env-42")
            except Exception as exc:
                failures.append(repr(exc))
                return

    readers = [threading.Thread(target=reader) for _ in range(4)]
    for thread in readers:
        thread.start()
    try:
        for round_number in range(500):
            _settings.learn_environments(["env-%d" % (round_number % 50)])
    finally:
        stop.set()
        for thread in readers:
            thread.join(timeout=5)

    assert failures == []
    assert _settings.normalize_environment("env-42") == "env-42"


# ---------------------------------------------------------------------------
# When init() runs it at all
# ---------------------------------------------------------------------------


def test_tracking_is_not_disabled_by_a_failed_preflight(recorded, requests_mock):
    # Losing the answer is not evidence the key is bad, and a telemetry SDK
    # that switched itself off over a preflight would be worse than one that
    # never checked.
    requests_mock.get(ME, status_code=401, json={"detail": "unknown key"})
    core._state.enabled = False

    assert ags.init(api_key=VALID_API_KEY, endpoint=BASE,
                    auto_instrument=False) is True
    try:
        assert ags.is_enabled() is True
    finally:
        ags.shutdown()


def test_the_file_exporter_path_has_no_key_to_check(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTSIGHT_FILE_EXPORTER", str(tmp_path / "traces"))
    core._state.enabled = False
    started = []
    monkeypatch.setattr(core, "_start_key_preflight",
                        lambda *args: started.append(args))

    assert ags.init(api_key=VALID_API_KEY, auto_instrument=False) is True
    try:
        assert started == []
    finally:
        ags.shutdown()


def test_a_supplied_exporter_has_nothing_to_authenticate(monkeypatch):
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
        InMemorySpanExporter,
    )

    core._state.enabled = False
    started = []
    monkeypatch.setattr(core, "_start_key_preflight",
                        lambda *args: started.append(args))

    assert ags.init(api_key=VALID_API_KEY, span_exporter=InMemorySpanExporter(),
                    auto_instrument=False) is True
    try:
        assert started == []
    finally:
        ags.shutdown()


def test_verify_key_false_skips_it(monkeypatch):
    core._state.enabled = False
    started = []
    monkeypatch.setattr(core, "_start_key_preflight",
                        lambda *args: started.append(args))

    assert ags.init(api_key=VALID_API_KEY, endpoint=BASE, auto_instrument=False,
                    verify_key=False) is True
    try:
        assert started == []
    finally:
        ags.shutdown()


def test_the_http_path_runs_it_with_the_resolved_credentials(monkeypatch):
    core._state.enabled = False
    started = []
    monkeypatch.setattr(core, "_start_key_preflight",
                        lambda *args: started.append(args))

    assert ags.init(api_key=VALID_API_KEY, endpoint=BASE,
                    auto_instrument=False) is True
    try:
        assert started == [(VALID_API_KEY, BASE)]
    finally:
        ags.shutdown()
