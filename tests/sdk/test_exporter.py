"""The HTTP span exporter's retry policy and its rejection diagnostics.

The exporter keeps its own loop rather than sharing ``Transport``'s, because it
runs on the batch processor's background thread and must return ``FAILURE``
instead of raising. That means its retry rules have to be pinned here
separately — nothing in ``tests/api/`` covers them.
"""

import email.utils
import logging
from datetime import datetime, timedelta, timezone

import pytest
import requests_mock as requests_mock_module
from opentelemetry.sdk.trace.export import SpanExportResult

from agentsight.sdk.exporter import AgentSightSpanExporter

ENDPOINT = "https://api.test.agentsight.io"
INGEST = f"{ENDPOINT}/api/ingest/"

VALID_KEY = "ags_1a2b3c4d5e6f7890abcdef1234567890_a1b2c3"

PAYLOAD = {"sdk": {"name": "agentsight-python", "version": "0.1.0"},
           "conversations": [{"conversation_id": "wa-1", "spans": []}]}


@pytest.fixture
def exporter():
    made = AgentSightSpanExporter(ENDPOINT, VALID_KEY, logging.getLogger("test"))
    yield made
    made.shutdown()


@pytest.fixture
def no_sleep(monkeypatch):
    """Waits are asserted on, not served."""
    slept = []
    monkeypatch.setattr("agentsight.sdk.exporter.time.sleep", slept.append)
    return slept


@pytest.fixture
def mock():
    with requests_mock_module.Mocker() as m:
        yield m


# -- 429 --------------------------------------------------------------------


def test_a_throttled_batch_is_retried_not_dropped(exporter, mock, no_sleep):
    # The bug this test exists for: 429 fell inside `400 <= status < 500` and
    # was treated as terminal, so a batch nothing was wrong with was lost.
    mock.post(INGEST, [{"status_code": 429}, {"status_code": 201, "json": {}}])

    assert exporter._post(PAYLOAD) is SpanExportResult.SUCCESS
    assert mock.call_count == 2


def test_retry_after_beats_the_fixed_curve(exporter, mock, no_sleep):
    mock.post(
        INGEST,
        [{"status_code": 429, "headers": {"Retry-After": "7"}},
         {"status_code": 201, "json": {}}],
    )

    exporter._post(PAYLOAD)

    assert no_sleep == [7.0]


def test_retry_after_accepts_the_http_date_form(exporter, mock, no_sleep):
    when = email.utils.format_datetime(
        datetime.now(timezone.utc) + timedelta(seconds=6)
    )
    mock.post(
        INGEST,
        [{"status_code": 429, "headers": {"Retry-After": when}},
         {"status_code": 201, "json": {}}],
    )

    exporter._post(PAYLOAD)

    assert no_sleep and 4.0 <= no_sleep[0] <= 6.0


def test_an_absurd_retry_after_is_capped(exporter, mock, no_sleep):
    # One header must not be able to park the only export thread, which every
    # later batch is queued behind.
    mock.post(INGEST, [{"status_code": 429, "headers": {"Retry-After": "86400"}},
                       {"status_code": 201, "json": {}}])

    exporter._post(PAYLOAD)

    assert no_sleep == [exporter._MAX_RETRY_AFTER]


def test_a_malformed_retry_after_falls_back_to_the_curve(exporter, mock, no_sleep):
    mock.post(INGEST, [{"status_code": 429, "headers": {"Retry-After": "whenever"}},
                       {"status_code": 201, "json": {}}])

    exporter._post(PAYLOAD)

    assert no_sleep == [exporter._BACKOFF[0]]


def test_a_batch_still_throttled_after_every_attempt_is_dropped(
    exporter, mock, no_sleep, caplog
):
    mock.post(INGEST, status_code=429)

    with caplog.at_level(logging.WARNING, logger="test"):
        assert exporter._post(PAYLOAD) is SpanExportResult.FAILURE

    assert mock.call_count == exporter._MAX_RETRIES
    assert "throttled" in caplog.text


# -- other 4xx stay terminal ------------------------------------------------


@pytest.mark.parametrize("status", [400, 401, 403, 404, 413])
def test_other_client_errors_are_not_retried(exporter, mock, no_sleep, status):
    # Retrying cannot help, and a stuck batch blocks every later one.
    mock.post(INGEST, status_code=status, json={"detail": "no"})

    assert exporter._post(PAYLOAD) is SpanExportResult.FAILURE
    assert mock.call_count == 1


def test_server_errors_are_retried(exporter, mock, no_sleep):
    mock.post(INGEST, [{"status_code": 502}, {"status_code": 201, "json": {}}])

    assert exporter._post(PAYLOAD) is SpanExportResult.SUCCESS
    assert mock.call_count == 2


# -- block-level 400 diagnostics --------------------------------------------


REJECTION = {
    "detail": "1 of 2 conversation blocks failed validation. Nothing was "
              "written; resend without the blocks listed here.",
    "conversations": [
        {"index": 1, "conversation_id": "wa-bad",
         "errors": {"environment": ["Unknown environment: 'staging'."]}}
    ],
}


def test_a_rejection_names_the_offending_conversation(exporter, mock, caplog):
    mock.post(INGEST, status_code=400, json=REJECTION)

    with caplog.at_level(logging.WARNING, logger="test"):
        exporter._post(PAYLOAD)

    assert "wa-bad" in caplog.text
    assert "Unknown environment" in caplog.text


def test_a_block_with_no_conversation_id_is_named_by_index(exporter, mock, caplog):
    # conversation_id is read back from the raw request server-side, but it can
    # still be missing entirely — the block is identified either way.
    mock.post(INGEST, status_code=400, json={
        "detail": "nope",
        "conversations": [{"index": 3, "errors": {"name": ["Too long."]}}],
    })

    with caplog.at_level(logging.WARNING, logger="test"):
        exporter._post(PAYLOAD)

    assert "index 3" in caplog.text


def test_a_long_block_list_is_summarised(exporter, mock, caplog):
    blocks = [
        {"index": i, "conversation_id": f"wa-{i}", "errors": {"device": ["Too long."]}}
        for i in range(12)
    ]
    mock.post(INGEST, status_code=400,
              json={"detail": "12 failed", "conversations": blocks, "truncated": True})

    with caplog.at_level(logging.WARNING, logger="test"):
        exporter._post(PAYLOAD)

    assert "wa-0" in caplog.text
    assert "and 7 more" in caplog.text          # 12 listed, 5 named
    assert "server truncated" in caplog.text


def test_a_top_level_error_falls_back_to_the_raw_body(exporter, mock, caplog):
    # Errors that are not per-block carry no `conversations` key, because there
    # is no block to point at.
    mock.post(INGEST, status_code=400,
              json={"conversations": "This field is required."})

    with caplog.at_level(logging.WARNING, logger="test"):
        exporter._post(PAYLOAD)

    assert "This field is required." in caplog.text


def test_a_non_json_rejection_does_not_raise(exporter, mock, caplog):
    mock.post(INGEST, status_code=400, text="<html>502 Bad Gateway</html>")

    with caplog.at_level(logging.WARNING, logger="test"):
        assert exporter._post(PAYLOAD) is SpanExportResult.FAILURE

    assert "Bad Gateway" in caplog.text
