"""Changing conversation metadata after the scope was opened.

The scope takes metadata once, at the top of a handler — before most of what
is worth recording has happened. These cover the call that changes it
afterwards, and the two things that make it non-trivial: the merge must not
eat falsy values, and the merged document must actually reach a span.
"""

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

import agentsight as ags
from agentsight import _metadata
from agentsight.exceptions import ValidationError
from agentsight.sdk import core, serialization
from agentsight.sdk.exporter import build_payload
from agentsight.sdk.processors import TurnBufferingProcessor
from agentsight.sdk.semconv import SpanAttributes, SpanKind


@pytest.fixture
def spans():
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(TurnBufferingProcessor(SimpleSpanProcessor(exporter)))

    previous = (core._state.enabled, core._state.provider, core._state.tracer)
    core._state.provider = provider
    core._state.tracer = provider.get_tracer("agentsight-test")
    core._state.enabled = True
    try:
        yield exporter
    finally:
        core._state.enabled, core._state.provider, core._state.tracer = previous


def blocks(spans):
    payload = build_payload(spans.get_finished_spans())
    return {block["conversation_id"]: block for block in payload["conversations"]}


# ---------------------------------------------------------------------------
# The merge rule
# ---------------------------------------------------------------------------


def test_new_keys_arrive_without_losing_the_old_ones(spans):
    with ags.conversation("c-1", metadata={"order_id": "A-1", "channel": "web"}):
        with ags.turn():
            ags.user_message("hi")
        ags.update_metadata({"plan": "enterprise"})

    assert blocks(spans)["c-1"]["metadata"] == {
        "order_id": "A-1",
        "channel": "web",
        "plan": "enterprise",
    }


def test_an_existing_key_is_overwritten(spans):
    with ags.conversation("c-2", metadata={"plan": "trial"}):
        ags.update_metadata({"plan": "enterprise"})

    assert blocks(spans)["c-2"]["metadata"] == {"plan": "enterprise"}


def test_remove_drops_keys_and_keeps_the_rest(spans):
    with ags.conversation("c-3", metadata={"plan": "trial", "trial_ends": "friday"}):
        ags.update_metadata(remove=["trial_ends"])

    assert blocks(spans)["c-3"]["metadata"] == {"plan": "trial"}


def test_setting_and_removing_in_one_call(spans):
    with ags.conversation("c-4", metadata={"a": 1, "b": 2}):
        ags.update_metadata({"c": 3}, remove=["a"])

    assert blocks(spans)["c-4"]["metadata"] == {"b": 2, "c": 3}


def test_removing_a_key_that_is_not_there_is_a_no_op(spans):
    with ags.conversation("c-5", metadata={"a": 1}):
        ags.update_metadata(remove=["nope"])

    assert blocks(spans)["c-5"]["metadata"] == {"a": 1}


def test_it_works_on_a_scope_opened_without_metadata(spans):
    with ags.conversation("c-6"):
        ags.update_metadata({"plan": "enterprise"})

    assert blocks(spans)["c-6"]["metadata"] == {"plan": "enterprise"}


def test_removing_everything_sends_an_empty_document_not_nothing(spans):
    """`{}` means "clear it". Dropping the key instead would read as "no
    opinion" and leave whatever the row already holds in place."""
    with ags.conversation("c-7", metadata={"a": 1}):
        ags.update_metadata(remove=["a"])

    assert blocks(spans)["c-7"]["metadata"] == {}


def test_a_nested_dict_is_replaced_whole_not_merged_into(spans):
    """Shallow by design — it is what keeps "replace this sub-object" sayable."""
    with ags.conversation("c-8", metadata={"user": {"tier": "gold", "id": 7}}):
        ags.update_metadata({"user": {"tier": "platinum"}})

    assert blocks(spans)["c-8"]["metadata"] == {"user": {"tier": "platinum"}}


# ---------------------------------------------------------------------------
# Falsy values are data
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("value", [None, False, 0, "", [], {}])
def test_a_falsy_value_is_stored_not_swallowed(spans, value):
    """`if value:` and `if value is not None:` guards are used all over this
    package, and every one of them would silently eat these. Removing a key is
    said with `remove=`, never by passing a falsy value."""
    with ags.conversation("c-falsy", metadata={"keep": 1}):
        ags.update_metadata({"flag": value})

    stored = blocks(spans)["c-falsy"]["metadata"]
    assert stored == {"keep": 1, "flag": value}
    assert "flag" in stored


# ---------------------------------------------------------------------------
# Delivery — the merged document has to reach a span
# ---------------------------------------------------------------------------


def test_the_update_lands_even_with_no_turn_after_it(spans):
    """The most natural moment to call this is as a conversation closes, when
    there is no further span to ride. So it emits one of its own."""
    with ags.conversation("c-late"):
        ags.update_metadata({"outcome": "resolved"})

    assert blocks(spans)["c-late"]["metadata"] == {"outcome": "resolved"}


def test_the_span_it_emits_does_not_count_as_engagement(spans):
    """Ingest reads any kind other than `conversation` as "someone engaged".
    Recording metadata is not engagement."""
    with ags.conversation("c-kind"):
        ags.update_metadata({"a": 1})

    kinds = [s.attributes[SpanAttributes.KIND] for s in spans.get_finished_spans()]
    assert kinds == [SpanKind.CONVERSATION]


def test_spans_after_the_update_carry_the_merged_document(spans):
    with ags.conversation("c-after", metadata={"a": 1}):
        ags.update_metadata({"b": 2})
        with ags.turn():
            ags.user_message("hi")

    for span in spans.get_finished_spans():
        stored = span.attributes.get("agentsight.conversation.metadata")
        assert stored is not None
        assert '"b"' in stored


# ---------------------------------------------------------------------------
# Isolation
# ---------------------------------------------------------------------------


def test_it_does_not_mutate_the_dict_the_caller_passed(spans):
    original = {"a": 1}

    with ags.conversation("c-caller", metadata=original):
        ags.update_metadata({"b": 2})

    assert original == {"a": 1}


def test_an_update_does_not_leak_into_the_next_decorated_call(spans):
    """The decorator rebuilds a scope per invocation from the kwargs it was
    given. Mutating those in place would put one request's metadata on every
    later request through the same handler."""

    @ags.conversation(metadata={"tier": "gold"})
    def handle(secret):
        ags.update_metadata({"secret": secret})

    handle("first")
    handle("second")

    documents = [block["metadata"] for block in blocks(spans).values()]
    assert {"tier": "gold", "secret": "first"} in documents
    assert {"tier": "gold", "secret": "second"} in documents
    assert len(documents) == 2


def test_no_active_conversation_is_a_silent_no_op(spans):
    ags.update_metadata({"a": 1})

    assert spans.get_finished_spans() == ()


def test_a_disabled_scope_records_nothing(spans):
    with ags.conversation("c-off", enabled=False):
        ags.update_metadata({"a": 1})

    assert spans.get_finished_spans() == ()


def test_bad_arguments_never_reach_the_caller(spans):
    """Tracking calls swallow — a wrong argument must not take down a handler.
    `_metadata.check` is where the same mistake is loud, on the API client."""
    with ags.conversation("c-bad", metadata={"a": 1}):
        ags.update_metadata("not a dict")
        ags.update_metadata(remove="tier")
        ags.update_metadata()

    # Nothing raised, and nothing was recorded either — a rejected update is
    # not a half-applied one.
    assert spans.get_finished_spans() == ()

    with ags.conversation("c-bad", metadata={"a": 1}):
        ags.update_metadata({"b": 2})

    assert blocks(spans)["c-bad"]["metadata"] == {"a": 1, "b": 2}


# ---------------------------------------------------------------------------
# Truncation must not compound
# ---------------------------------------------------------------------------


def test_repeated_updates_do_not_re_truncate_what_was_already_cut(spans):
    """The raw document is kept beside the serialised attribute for exactly
    this: merging out of the truncated string would trim the same value again
    on every update, and the keys shed the first time could never come back."""
    big = "x" * 40_000

    with ags.conversation("c-trunc", metadata={"transcript": big, "order_id": "A-1"}):
        for i in range(5):
            ags.update_metadata({"step": i})

    stored = blocks(spans)["c-trunc"]["metadata"]
    assert stored["order_id"] == "A-1"
    assert stored["step"] == 4
    assert stored["transcript"].endswith(serialization.TRUNCATION_SUFFIX)
    # Cut once, to the same length as a single-shot truncation — not five times.
    assert len(stored["transcript"]) > serialization.MAX_ATTRIBUTE_LENGTH // 2


# ---------------------------------------------------------------------------
# The shared helper, on its own
# ---------------------------------------------------------------------------


def test_merge_returns_a_new_dict():
    current = {"a": 1}
    merged = _metadata.merge(current, {"b": 2})

    assert merged == {"a": 1, "b": 2}
    assert current == {"a": 1}


def test_check_rejects_a_bare_string_for_remove():
    """`remove="tier"` iterates to 't', 'i', 'e', 'r' — a mistake that is
    invisible until someone notices data missing."""
    with pytest.raises(ValidationError) as excinfo:
        _metadata.check(None, "tier")

    assert "remove=['tier']" in str(excinfo.value)


def test_check_rejects_a_call_that_would_do_nothing():
    with pytest.raises(ValidationError):
        _metadata.check(None, None)
    with pytest.raises(ValidationError):
        _metadata.check({}, [])


def test_check_rejects_non_dict_metadata():
    with pytest.raises(ValidationError):
        _metadata.check("tier=gold", None)


def test_coerce_reads_a_document_stored_as_a_json_string():
    """Rows written by older builds hold the document as a JSON string.
    Treating one of those as "no metadata" would wipe every key in it."""
    assert _metadata.coerce('{"a": 1}') == {"a": 1}
    assert _metadata.coerce(None) == {}
    assert _metadata.coerce("") == {}


@pytest.mark.parametrize("value", ["not json", '"a string"', "[1, 2]", 7])
def test_coerce_refuses_to_guess(value):
    with pytest.raises(ValidationError):
        _metadata.coerce(value)
