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


# -- 429 under backpressure -------------------------------------------------
#
# Waiting out a throttle blocks the batch processor's ONE export thread. That
# is free while the queue behind it has room and ruinous when it does not: the
# batch in hand is at most one export batch, while the queue drops everything
# that arrives meanwhile — silently, from OpenTelemetry's logger rather than
# ours. Past half full the trade inverts and the batch is dropped instead.


class _Queue:
    """Enough of a BatchSpanProcessor for the pressure read."""

    def __init__(self, depth, capacity=2048, nested=True):
        inner = type("BatchProcessor", (), {})()
        inner._queue = [None] * depth
        inner._max_queue_size = capacity
        if nested:
            self._batch_processor = inner
        else:  # the older layout, where these sat on the processor itself
            self._queue = inner._queue
            self._max_queue_size = capacity


def test_a_full_queue_makes_the_batch_the_cheaper_thing_to_drop(
    exporter, mock, no_sleep, caplog
):
    mock.post(INGEST, status_code=429)
    exporter.watch_queue(_Queue(depth=1600))  # 78%

    with caplog.at_level(logging.WARNING, logger="test"):
        assert exporter._post(PAYLOAD) is SpanExportResult.FAILURE

    # Dropped on the first answer: no retries, and nothing slept.
    assert mock.call_count == 1
    assert no_sleep == []
    assert "78% full" in caplog.text


def test_an_empty_queue_still_waits_the_throttle_out(exporter, mock, no_sleep):
    mock.post(INGEST, [{"status_code": 429, "headers": {"Retry-After": "7"}},
                       {"status_code": 201, "json": {}}])
    exporter.watch_queue(_Queue(depth=10))  # 0.5%

    assert exporter._post(PAYLOAD) is SpanExportResult.SUCCESS
    assert no_sleep == [7.0]


def test_the_older_processor_layout_is_read_too(exporter, mock, no_sleep):
    mock.post(INGEST, status_code=429)
    exporter.watch_queue(_Queue(depth=1600, nested=False))

    assert exporter._post(PAYLOAD) is SpanExportResult.FAILURE
    assert mock.call_count == 1


def test_an_unreadable_queue_behaves_exactly_as_before(exporter, mock, no_sleep):
    """These are OpenTelemetry internals and have moved between releases. If
    they move again, the exporter must fall back to waiting — not to guessing
    the queue is empty, and not to dropping everything."""
    mock.post(INGEST, [{"status_code": 429}, {"status_code": 201, "json": {}}])
    exporter.watch_queue(object())

    assert exporter._queue_pressure() is None
    assert exporter._post(PAYLOAD) is SpanExportResult.SUCCESS
    assert no_sleep == [exporter._BACKOFF[0]]


def test_no_queue_at_all_behaves_exactly_as_before(exporter, mock, no_sleep):
    # watch_queue is never called for a custom transport or in tests.
    mock.post(INGEST, [{"status_code": 429}, {"status_code": 201, "json": {}}])

    assert exporter._queue_pressure() is None
    assert exporter._post(PAYLOAD) is SpanExportResult.SUCCESS


# -- backpressure, whatever its cause ---------------------------------------
#
# OpenTelemetry drops from a full queue and logs once PER SPAN on its own
# logger. An application that configured only `agentsight` hears nothing while
# data is lost; one that configured root logging gets a line per span at the
# volume that caused the overflow. Neither is usable, so the exporter says it
# itself, once a minute, before the queue is full.


def test_a_filling_queue_is_reported_on_our_own_logger(exporter, mock, caplog):
    mock.post(INGEST, status_code=201, json={})
    exporter.watch_queue(_Queue(depth=1800))  # 88%

    with caplog.at_level(logging.WARNING, logger="test"):
        assert exporter.export([]) is SpanExportResult.SUCCESS

    assert "88% full" in caplog.text
    assert "max_queue_size" in caplog.text


def test_a_full_queue_says_data_is_already_being_lost(exporter, mock, caplog):
    mock.post(INGEST, status_code=201, json={})
    exporter.watch_queue(_Queue(depth=2048))

    with caplog.at_level(logging.WARNING, logger="test"):
        exporter.export([])

    assert "queue is full" in caplog.text
    assert "being dropped" in caplog.text


def test_a_healthy_queue_says_nothing(exporter, mock, caplog):
    mock.post(INGEST, status_code=201, json={})
    exporter.watch_queue(_Queue(depth=1200))  # 58% — over the 429 line, not this one

    with caplog.at_level(logging.WARNING, logger="test"):
        exporter.export([])

    assert caplog.text == ""


def test_backpressure_is_reported_once_a_minute_not_once_a_batch(
    exporter, mock, caplog
):
    # The whole point: replacing a per-span flood with a per-minute signal.
    mock.post(INGEST, status_code=201, json={})
    exporter.watch_queue(_Queue(depth=2048))

    with caplog.at_level(logging.WARNING, logger="test"):
        for _ in range(50):
            exporter.export([])

    assert len(caplog.records) == 1


def test_a_drop_warning_does_not_suppress_the_pressure_warning(
    exporter, mock, no_sleep, caplog
):
    """An outage causes both at once, and they say different things: one that
    the backend is refusing us, one that we cannot keep up. Sharing a timer
    would let whichever fired first hide the other for a minute."""
    mock.post(INGEST, status_code=429)
    exporter.watch_queue(_Queue(depth=2048))

    with caplog.at_level(logging.WARNING, logger="test"):
        exporter.export([_span_carrying_a_conversation()])

    assert "queue is full" in caplog.text          # falling behind
    assert "throttled (429)" in caplog.text        # and being refused


def test_an_unreadable_queue_reports_nothing(exporter, mock, caplog):
    mock.post(INGEST, status_code=201, json={})
    exporter.watch_queue(object())

    with caplog.at_level(logging.WARNING, logger="test"):
        exporter.export([])

    assert caplog.text == ""


def _span_carrying_a_conversation():
    """One real finished span, so build_payload has a block to send.

    Built through the real SDK rather than faked: span_to_dict reads context
    ids, resource and scope off it, and a stand-in that satisfies today's
    reads would quietly start failing the moment it reads one more.
    """
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
        InMemorySpanExporter,
    )

    from agentsight.sdk.semconv import ConversationAttributes

    memory = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(memory))
    with provider.get_tracer("test").start_as_current_span("chat") as span:
        span.set_attribute(ConversationAttributes.ID, "wa-1")
    return memory.get_finished_spans()[0]


def test_init_wires_the_real_processor_to_the_exporter(monkeypatch):
    """The wiring, not the arithmetic: an exporter that cannot see the queue
    makes the pressure check dead code, and nothing else would notice."""
    import agentsight as ags
    from agentsight.sdk import core

    monkeypatch.delenv("AGENTSIGHT_FILE_EXPORTER", raising=False)
    core._state.enabled = False

    assert ags.init(api_key=VALID_KEY, endpoint=ENDPOINT, auto_instrument=False,
                    verify_key=False) is True
    try:
        assert core.get_exporter()._queue_pressure() == 0.0
    finally:
        ags.shutdown()


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
