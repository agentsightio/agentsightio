"""The file transport, and what selecting it must not change.

Two things are being defended here. First, that a file on disk is exactly what
the wire would have carried — the moment the two shapes can differ, reading a
trace file stops being evidence about the backend. Second, that the variable
which selects it is inert when unset: every assertion about default behaviour
in the rest of the suite depends on `init()` still building the HTTP transport
when nobody asked for anything else.
"""

import json
import logging
import os

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor, SpanExportResult
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

import agentsight.sdk as ags
from agentsight.sdk import core
from agentsight.sdk.exporter import AgentSightSpanExporter, build_payload
from agentsight.sdk.file_exporter import FileSpanExporter
from agentsight.sdk.processors import TurnBufferingProcessor

VALID_KEY = "ags_1a2b3c4d5e6f7890abcdef1234567890_a1b2c3"


@pytest.fixture
def logger():
    return logging.getLogger("agentsight-test-file-exporter")


class _Recorder(logging.Handler):
    """Collects formatted messages from a logger that does not propagate."""

    def __init__(self):
        super().__init__()
        self.messages = []

    def emit(self, record):
        self.messages.append(record.getMessage())


def make_spans(conversation_id="c-file", text="hello"):
    """Real spans from the real SDK path, captured rather than exported."""
    memory = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(TurnBufferingProcessor(SimpleSpanProcessor(memory)))

    previous = (core._state.enabled, core._state.provider, core._state.tracer)
    core._state.provider = provider
    core._state.tracer = provider.get_tracer("agentsight-test")
    core._state.enabled = True
    try:
        with ags.conversation(conversation_id, device="desktop"):
            with ags.turn("ask"):
                ags.user_message(text)
                ags.agent_message("answered")
    finally:
        core._state.enabled, core._state.provider, core._state.tracer = previous

    return memory.get_finished_spans()


def written(directory):
    return sorted(f for f in os.listdir(directory) if f.endswith(".json"))


# ---------------------------------------------------------------------------
# What lands on disk
# ---------------------------------------------------------------------------


def test_an_export_writes_the_payload_the_wire_would_carry(tmp_path, logger):
    """The file is `build_payload()`'s output and nothing else.

    Both sides are round-tripped through JSON before comparing, because OTel
    represents sequence attributes as tuples and JSON has only arrays — the
    difference is an encoding artefact, not a disagreement about content.
    """
    spans = make_spans()
    exporter = FileSpanExporter(str(tmp_path / "traces"), logger)

    assert exporter.export(spans) is SpanExportResult.SUCCESS

    files = written(exporter.directory)
    assert len(files) == 1

    with open(os.path.join(exporter.directory, files[0]), encoding="utf-8") as handle:
        on_disk = json.load(handle)

    assert on_disk == json.loads(json.dumps(build_payload(spans)))
    assert on_disk["conversations"][0]["conversation_id"] == "c-file"


def test_the_destination_directory_is_created(tmp_path, logger):
    destination = tmp_path / "nested" / "traces"
    assert not destination.exists()

    exporter = FileSpanExporter(str(destination), logger)

    assert destination.is_dir()
    assert exporter.files_written == 0


def test_a_destination_that_is_a_file_is_refused_rather_than_guessed(tmp_path, logger):
    existing = tmp_path / "traces.json"
    existing.write_text("{}")

    with pytest.raises(ValueError, match="existing file"):
        FileSpanExporter(str(existing), logger)


def test_files_sort_in_export_order(tmp_path, logger):
    exporter = FileSpanExporter(str(tmp_path / "traces"), logger)

    order = [f"c-{i}" for i in range(5)]
    for conversation_id in order:
        exporter.export(make_spans(conversation_id))

    seen = []
    for name in written(exporter.directory):
        with open(os.path.join(exporter.directory, name), encoding="utf-8") as handle:
            seen.append(json.load(handle)["conversations"][0]["conversation_id"])

    assert seen == order
    assert exporter.files_written == 5


def test_a_batch_with_nothing_of_ours_in_it_writes_no_file(tmp_path, logger):
    """A span with no conversation id is not ours; an empty payload is not a
    file full of nothing."""
    provider = TracerProvider()
    tracer = provider.get_tracer("someone-else")
    memory = InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(memory))
    tracer.start_span("unrelated").end()

    exporter = FileSpanExporter(str(tmp_path / "traces"), logger)

    assert exporter.export(memory.get_finished_spans()) is SpanExportResult.SUCCESS
    assert written(exporter.directory) == []


def test_a_destination_that_vanishes_fails_without_raising(tmp_path, logger):
    """Exporters run on the batch processor's thread, where an exception has
    nowhere to go. Someone clearing the trace directory mid-run must cost a
    batch, not the process."""
    exporter = FileSpanExporter(str(tmp_path / "traces"), logger)
    os.rmdir(exporter.directory)

    assert exporter.export(make_spans()) is SpanExportResult.FAILURE
    assert exporter.files_written == 0


# ---------------------------------------------------------------------------
# Which transport init() picks
# ---------------------------------------------------------------------------


def test_the_variable_selects_the_file_transport_without_an_api_key(
    tmp_path, monkeypatch
):
    destination = tmp_path / "traces"
    monkeypatch.setenv("AGENTSIGHT_FILE_EXPORTER", str(destination))
    monkeypatch.setattr(core._state, "enabled", False)

    assert ags.init(auto_instrument=False) is True
    try:
        assert isinstance(core.get_exporter(), FileSpanExporter)
        with ags.conversation("c-via-env"):
            with ags.turn():
                ags.user_message("through the file transport")
        ags.flush()
    finally:
        ags.shutdown()

    assert written(str(destination))


def test_an_explicit_exporter_beats_the_variable(tmp_path, monkeypatch):
    """Code says what this run is for; an environment variable says what some
    earlier shell was for."""
    monkeypatch.setenv("AGENTSIGHT_FILE_EXPORTER", str(tmp_path / "traces"))
    monkeypatch.setattr(core._state, "enabled", False)

    memory = InMemorySpanExporter()
    assert ags.init(span_exporter=memory, auto_instrument=False) is True
    try:
        assert core.get_exporter() is memory
    finally:
        ags.shutdown()

    # Not merely empty — never created, because nothing ever constructed it.
    assert not (tmp_path / "traces").exists()


def test_a_variable_pointing_at_a_file_disables_loudly(tmp_path, monkeypatch):
    """Better than exporting nothing into a directory nobody will look in."""
    existing = tmp_path / "traces.json"
    existing.write_text("{}")
    monkeypatch.setenv("AGENTSIGHT_FILE_EXPORTER", str(existing))
    monkeypatch.setattr(core._state, "enabled", False)

    # caplog cannot see this: the package logger sets propagate = False, so
    # nothing reaches the root logger caplog attaches to.
    recorded = _Recorder()
    core.logger.addHandler(recorded)
    try:
        assert ags.init(auto_instrument=False) is False
    finally:
        core.logger.removeHandler(recorded)

    assert ags.is_enabled() is False
    assert any("existing file" in message for message in recorded.messages)


def test_without_the_variable_init_still_builds_the_http_transport(monkeypatch):
    """The boundary the whole feature is held to: unset means unchanged."""
    monkeypatch.delenv("AGENTSIGHT_FILE_EXPORTER", raising=False)
    monkeypatch.setattr(core._state, "enabled", False)

    # verify_key=False keeps the suite off the network: the HTTP transport is
    # the one path that has a key worth preflighting.
    assert ags.init(api_key=VALID_KEY, auto_instrument=False,
                    verify_key=False) is True
    try:
        assert isinstance(core.get_exporter(), AgentSightSpanExporter)
    finally:
        ags.shutdown()
