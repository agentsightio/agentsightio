"""The data-plane upload call.

``upload_attachments()`` is the one AgentSight call allowed to block and to
raise: it moves customer bytes, not telemetry. These tests pin the payload
shape the backend expects (mirroring the backend's own attachment tests), the
conversation get-or-create round trip that precedes every upload, and the
failure contract — caller mistakes are ``ValueError``, refused or unreachable
backends are ``UploadError``, and nothing is ever swallowed.
"""

import base64
import io
import json

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

import agentsight.sdk as ags
from agentsight.exceptions import UploadError
from agentsight.sdk import core
from agentsight.sdk.processors import TurnBufferingProcessor
from agentsight.sdk.semconv import AttachmentAttributes, SpanAttributes, SpanKind

ENDPOINT = "https://test.agentsight.io"
CONVERSATIONS_URL = f"{ENDPOINT}/api/conversations/"
LOOKUP_URL = f"{ENDPOINT}/api/conversations/lookup/"
ATTACHMENTS_URL = f"{ENDPOINT}/api/attachments/"
API_KEY = "ags_1a2b3c4d5e6f7890abcdef1234567890_a1b2c3"

PNG_BYTES = b"png-bytes"


@pytest.fixture
def sdk(monkeypatch):
    """SDK state with credentials and an in-memory span pipeline."""
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(TurnBufferingProcessor(SimpleSpanProcessor(exporter)))

    previous = (
        core._state.enabled,
        core._state.provider,
        core._state.tracer,
        core._state.api_key,
        core._state.endpoint,
    )
    core._state.provider = provider
    core._state.tracer = provider.get_tracer("agentsight-test")
    core._state.enabled = True
    core._state.api_key = API_KEY
    core._state.endpoint = ENDPOINT
    try:
        yield exporter
    finally:
        (
            core._state.enabled,
            core._state.provider,
            core._state.tracer,
            core._state.api_key,
            core._state.endpoint,
        ) = previous


def stub_happy_backend(requests_mock, pk=7):
    requests_mock.post(CONVERSATIONS_URL, json={"id": pk, "conversation_id": "x"})
    requests_mock.post(
        ATTACHMENTS_URL, status_code=201, json={"attachments": [{"id": 1}]}
    )


def sent_to(requests_mock, url):
    return [r for r in requests_mock.request_history if r.url.startswith(url)]


# --- payload shape ----------------------------------------------------------


def test_uploads_a_path(sdk, requests_mock, tmp_path):
    stub_happy_backend(requests_mock)
    path = tmp_path / "f.png"
    path.write_bytes(PNG_BYTES)

    result = ags.upload_attachments(str(path), conversation_id="conv-1")

    upload = sent_to(requests_mock, ATTACHMENTS_URL)[0].json()
    assert upload["conversation"] == "7"
    assert upload["mode"] == "base64"
    assert upload["sender"] == "end_user"
    assert upload["timestamp"]
    [attachment] = upload["attachments"]
    assert attachment["filename"] == "f.png"
    assert attachment["mime_type"] == "image/png"
    assert base64.b64decode(attachment["data"]) == PNG_BYTES
    assert result == {"attachments": [{"id": 1}]}


def test_uploads_a_dict_of_bytes_and_a_file_object(sdk, requests_mock):
    stub_happy_backend(requests_mock)
    handle = io.BytesIO(b"second")
    handle.name = "notes.txt"

    ags.upload_attachments(
        [
            {"filename": "report.pdf", "data": b"first"},
            handle,
        ],
        conversation_id="conv-1",
        sender="agent",
        metadata={"origin": "test"},
    )

    upload = sent_to(requests_mock, ATTACHMENTS_URL)[0].json()
    assert upload["sender"] == "agent"
    assert upload["metadata"] == {"origin": "test"}
    first, second = upload["attachments"]
    assert first["filename"] == "report.pdf"
    assert first["mime_type"] == "application/pdf"
    assert base64.b64decode(first["data"]) == b"first"
    assert second["filename"] == "notes.txt"
    assert second["mime_type"] == "text/plain"
    assert base64.b64decode(second["data"]) == b"second"


def test_base64_string_data_passes_through(sdk, requests_mock):
    stub_happy_backend(requests_mock)
    encoded = base64.b64encode(PNG_BYTES).decode()

    ags.upload_attachments(
        {"filename": "f.png", "data": encoded}, conversation_id="conv-1"
    )

    upload = sent_to(requests_mock, ATTACHMENTS_URL)[0].json()
    assert upload["attachments"][0]["data"] == encoded


def test_api_key_authenticates_both_requests(sdk, requests_mock):
    stub_happy_backend(requests_mock)

    ags.upload_attachments(
        {"filename": "f.png", "data": PNG_BYTES}, conversation_id="conv-1"
    )

    for request in requests_mock.request_history:
        assert request.headers["Authorization"] == f"Api-Key {API_KEY}"


# --- conversation resolution ------------------------------------------------


def test_resolves_conversation_and_environment_from_the_active_scope(
    sdk, requests_mock
):
    stub_happy_backend(requests_mock)

    with ags.conversation("conv-9", environment="production"):
        ags.upload_attachments({"filename": "f.png", "data": PNG_BYTES})

    upsert = sent_to(requests_mock, CONVERSATIONS_URL)[0].json()
    assert upsert == {"conversation_id": "conv-9", "environment": "production"}


# --- the data entity on the early row -----------------------------------------
#
# A conversation keeps the first key that reaches it, and this request usually
# gets there before the spans do. So a key sent here has to be the one the spans
# will carry, and when that cannot be known nothing is sent: a write without a
# key leaves the entity open, and a wrong one is permanent.


def test_the_owning_scope_sends_its_data_entity(sdk, requests_mock):
    stub_happy_backend(requests_mock)

    with ags.conversation("conv-9", data_entity="hotel-paris"):
        ags.upload_attachments({"filename": "f.png", "data": PNG_BYTES})

    upsert = sent_to(requests_mock, CONVERSATIONS_URL)[0].json()
    assert upsert["data_entity"] == "hotel-paris"


def test_naming_the_scopes_own_conversation_still_sends_it(sdk, requests_mock):
    stub_happy_backend(requests_mock)

    with ags.conversation("conv-9", data_entity="hotel-paris"):
        ags.upload_attachments(
            {"filename": "f.png", "data": PNG_BYTES}, conversation_id="conv-9"
        )

    assert sent_to(requests_mock, CONVERSATIONS_URL)[0].json()["data_entity"] == "hotel-paris"


def test_a_default_reaches_the_early_row_through_the_scope(sdk, requests_mock, monkeypatch):
    monkeypatch.setattr(core._state, "data_entity", "hotel-rome")
    stub_happy_backend(requests_mock)

    with ags.conversation("conv-9"):
        ags.upload_attachments({"filename": "f.png", "data": PNG_BYTES})

    assert sent_to(requests_mock, CONVERSATIONS_URL)[0].json()["data_entity"] == "hotel-rome"


def test_another_conversations_scope_does_not_lend_its_data_entity(sdk, requests_mock):
    """The one that would file a hotel's upload under a different hotel."""
    stub_happy_backend(requests_mock)

    with ags.conversation("conv-paris", data_entity="hotel-paris"):
        ags.upload_attachments(
            {"filename": "f.png", "data": PNG_BYTES}, conversation_id="conv-rome"
        )

    upsert = sent_to(requests_mock, CONVERSATIONS_URL)[0].json()
    assert upsert["conversation_id"] == "conv-rome"
    assert "data_entity" not in upsert


def test_the_default_alone_does_not_stamp_a_conversation_outside_any_scope(
    sdk, requests_mock, monkeypatch
):
    """The conversation may be tracked under its own key with the spans still
    queued, and this request would then win over them."""
    monkeypatch.setattr(core._state, "data_entity", "hotel-rome")
    stub_happy_backend(requests_mock)

    ags.upload_attachments(
        {"filename": "f.png", "data": PNG_BYTES}, conversation_id="conv-9"
    )

    assert "data_entity" not in sent_to(requests_mock, CONVERSATIONS_URL)[0].json()


def test_an_upload_counts_as_recorded_for_the_default(sdk, requests_mock, monkeypatch):
    """The upsert has carried the default to the backend, which keeps the first
    key. A turn naming another one afterwards must not switch the spans."""
    monkeypatch.setattr(core._state, "data_entity", "the-default")
    stub_happy_backend(requests_mock)

    with ags.conversation("conv-9") as scope:
        ags.upload_attachments({"filename": "f.png", "data": PNG_BYTES})
        with ags.turn(data_entity="hotel-paris"):
            ags.user_message("hi")

    assert sent_to(requests_mock, CONVERSATIONS_URL)[0].json()["data_entity"] == "the-default"
    assert scope.attributes["agentsight.conversation.data_entity"] == "the-default"


def test_an_upload_refused_after_the_row_exists_still_counts(sdk, requests_mock, monkeypatch):
    """The row was created with the default before the bytes were refused, and
    no span followed to say so. The backend has the key all the same."""
    monkeypatch.setattr(core._state, "data_entity", "the-default")
    requests_mock.post(CONVERSATIONS_URL, json={"id": 7})
    requests_mock.post(ATTACHMENTS_URL, status_code=503, json={"detail": "no storage"})

    with ags.conversation("conv-9") as scope:
        with pytest.raises(UploadError):
            ags.upload_attachments({"filename": "f.png", "data": PNG_BYTES})
        with ags.turn(data_entity="hotel-paris"):
            ags.user_message("hi")

    assert sent_to(requests_mock, CONVERSATIONS_URL)[0].json()["data_entity"] == "the-default"
    assert scope.attributes["agentsight.conversation.data_entity"] == "the-default"


def test_no_conversation_anywhere_is_a_caller_error(sdk, requests_mock):
    with pytest.raises(ValueError, match="conversation"):
        ags.upload_attachments({"filename": "f.png", "data": PNG_BYTES})
    assert requests_mock.request_history == []


def test_refused_upsert_falls_back_to_lookup(sdk, requests_mock):
    requests_mock.post(
        CONVERSATIONS_URL, status_code=400, json={"environment": ["Unknown"]}
    )
    requests_mock.get(LOOKUP_URL, json={"id": 3, "conversation_id": "conv-1"})
    requests_mock.post(ATTACHMENTS_URL, status_code=201, json={})

    ags.upload_attachments(
        {"filename": "f.png", "data": PNG_BYTES}, conversation_id="conv-1"
    )

    upload = sent_to(requests_mock, ATTACHMENTS_URL)[0].json()
    assert upload["conversation"] == "3"


def test_unresolvable_conversation_raises_with_the_upsert_error(sdk, requests_mock):
    requests_mock.post(
        CONVERSATIONS_URL, status_code=403, json={"detail": "forbidden"}
    )
    requests_mock.get(LOOKUP_URL, status_code=404, json={"detail": "not found"})

    with pytest.raises(UploadError) as excinfo:
        ags.upload_attachments(
            {"filename": "f.png", "data": PNG_BYTES}, conversation_id="conv-1"
        )
    assert excinfo.value.status_code == 403
    assert sent_to(requests_mock, ATTACHMENTS_URL) == []


# --- failure contract -------------------------------------------------------


def test_backend_rejection_raises_and_records_no_span(sdk, requests_mock):
    requests_mock.post(CONVERSATIONS_URL, json={"id": 7})
    requests_mock.post(
        ATTACHMENTS_URL, status_code=403, json={"detail": "read key"}
    )

    with ags.conversation("conv-1"):
        with pytest.raises(UploadError) as excinfo:
            ags.upload_attachments({"filename": "f.png", "data": PNG_BYTES})

    assert excinfo.value.status_code == 403
    assert excinfo.value.response == {"detail": "read key"}
    assert sdk.get_finished_spans() == ()


def test_without_credentials_the_error_says_to_init(sdk):
    core._state.api_key = None
    with pytest.raises(UploadError, match="init"):
        ags.upload_attachments(
            {"filename": "f.png", "data": PNG_BYTES}, conversation_id="conv-1"
        )


def test_caller_mistakes_are_value_errors(sdk):
    with pytest.raises(ValueError, match="filename"):
        ags.upload_attachments(b"raw", conversation_id="conv-1")
    with pytest.raises(ValueError, match="filename"):
        ags.upload_attachments({"data": b"x"}, conversation_id="conv-1")
    with pytest.raises(ValueError, match="data"):
        ags.upload_attachments({"filename": "f.png"}, conversation_id="conv-1")
    with pytest.raises(ValueError, match="base64"):
        ags.upload_attachments(
            {"filename": "f.png", "data": "not base64!!"}, conversation_id="conv-1"
        )
    with pytest.raises(ValueError, match="no such file"):
        ags.upload_attachments("/nope/missing.png", conversation_id="conv-1")
    with pytest.raises(ValueError, match="no files"):
        ags.upload_attachments([], conversation_id="conv-1")


# --- linking to an existing message -----------------------------------------


def test_message_id_is_sent_as_the_message_field(sdk, requests_mock):
    stub_happy_backend(requests_mock)

    ags.upload_attachments(
        {"filename": "f.png", "data": PNG_BYTES},
        conversation_id="conv-1",
        message_id=10325,
    )

    upload = sent_to(requests_mock, ATTACHMENTS_URL)[0].json()
    assert upload["message"] == "10325"


def test_no_message_id_omits_the_field(sdk, requests_mock):
    """The 0.1.1 payload, byte for byte — the backend's create branch."""
    stub_happy_backend(requests_mock)

    ags.upload_attachments(
        {"filename": "f.png", "data": PNG_BYTES}, conversation_id="conv-1"
    )
    ags.upload_attachments(
        {"filename": "f.png", "data": PNG_BYTES},
        conversation_id="conv-1",
        message_id="  ",
    )

    for request in sent_to(requests_mock, ATTACHMENTS_URL):
        assert "message" not in request.json()


def test_stale_message_id_surfaces_the_backend_404(sdk, requests_mock):
    requests_mock.post(CONVERSATIONS_URL, json={"id": 7})
    requests_mock.post(
        ATTACHMENTS_URL, status_code=404, json={"detail": "Message 1 not found"}
    )

    with pytest.raises(UploadError) as excinfo:
        ags.upload_attachments(
            {"filename": "f.png", "data": PNG_BYTES},
            conversation_id="conv-1",
            message_id=1,
        )
    assert excinfo.value.status_code == 404


# --- the internal timestamp -------------------------------------------------
#
# `_timestamp` is private on purpose: it is the only writable timestamp the
# backend exposes, and a transcript's order is what the SDK observed, not what
# a caller asserts. These tests pin the behaviour our own integrations use —
# and that the public name stays unavailable.


def test_public_timestamp_argument_does_not_exist(sdk, requests_mock):
    import pytest

    stub_happy_backend(requests_mock)

    with pytest.raises(TypeError):
        ags.upload_attachments(
            {"filename": "f.png", "data": PNG_BYTES},
            conversation_id="conv-1",
            timestamp="2026-08-24T10:00:00+00:00",
        )


def test_internal_timestamp_is_keyword_only(sdk, requests_mock):
    import inspect

    parameter = inspect.signature(ags.upload_attachments).parameters["_timestamp"]
    assert parameter.kind is inspect.Parameter.KEYWORD_ONLY


def test_aware_timestamp_is_sent_verbatim(sdk, requests_mock):
    from datetime import datetime, timezone

    stub_happy_backend(requests_mock)
    instant = datetime(2026, 8, 24, 10, 0, tzinfo=timezone.utc)

    ags.upload_attachments(
        {"filename": "f.png", "data": PNG_BYTES},
        conversation_id="conv-1",
        _timestamp=instant,
    )

    upload = sent_to(requests_mock, ATTACHMENTS_URL)[0].json()
    assert upload["timestamp"] == instant.isoformat()


def test_naive_timestamp_is_read_as_utc_not_local(sdk, requests_mock):
    from datetime import datetime, timezone

    stub_happy_backend(requests_mock)

    ags.upload_attachments(
        {"filename": "f.png", "data": PNG_BYTES},
        conversation_id="conv-1",
        _timestamp=datetime(2026, 8, 24, 10, 0),
    )

    upload = sent_to(requests_mock, ATTACHMENTS_URL)[0].json()
    assert upload["timestamp"] == datetime(
        2026, 8, 24, 10, 0, tzinfo=timezone.utc
    ).isoformat()


def test_string_timestamp_passes_through(sdk, requests_mock):
    stub_happy_backend(requests_mock)

    ags.upload_attachments(
        {"filename": "f.png", "data": PNG_BYTES},
        conversation_id="conv-1",
        _timestamp="2026-08-24T10:00:00+00:00",
    )

    upload = sent_to(requests_mock, ATTACHMENTS_URL)[0].json()
    assert upload["timestamp"] == "2026-08-24T10:00:00+00:00"


def test_default_timestamp_is_still_now(sdk, requests_mock):
    from datetime import datetime

    stub_happy_backend(requests_mock)

    ags.upload_attachments(
        {"filename": "f.png", "data": PNG_BYTES}, conversation_id="conv-1"
    )

    upload = sent_to(requests_mock, ATTACHMENTS_URL)[0].json()
    # A required serializer field on the backend — must be present and parse.
    assert datetime.fromisoformat(upload["timestamp"]).tzinfo is not None


# --- the descriptor span ----------------------------------------------------


def test_successful_upload_records_a_descriptor_span(sdk, requests_mock):
    stub_happy_backend(requests_mock)

    with ags.conversation("conv-1"):
        ags.upload_attachments({"filename": "f.png", "data": PNG_BYTES})

    spans = [
        s
        for s in sdk.get_finished_spans()
        if (s.attributes or {}).get(SpanAttributes.KIND) == SpanKind.ATTACHMENT
    ]
    assert len(spans) == 1
    files = json.loads(spans[0].attributes[AttachmentAttributes.FILES])
    assert files == [
        {"filename": "f.png", "mime_type": "image/png", "size": len(PNG_BYTES)}
    ]
