"""What the SDK captures, and what it refuses to capture.

The parity contract says every row written by the span path has the same shape
as the row `track_*` writes today. These tests hold the SDK end of that: the
right spans, the right attributes, and — just as important — nothing at all
when there is nothing to record.
"""

import asyncio
import json

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

import agentsight.sdk as ags
from agentsight.sdk import core
from agentsight.sdk.exporter import build_payload, span_to_dict
from agentsight.sdk.instrumentation import from_openai, record_llm_call
from agentsight.sdk.processors import TurnBufferingProcessor
from agentsight.sdk.semconv import (
    AttachmentAttributes,
    ButtonAttributes,
    ConversationAttributes,
    LLMAttributes,
    MessageAttributes,
    SpanAttributes,
    SpanKind,
    ToolAttributes,
    TurnAttributes,
)


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


def by_kind(exporter, kind):
    return [
        s
        for s in exporter.get_finished_spans()
        if (s.attributes or {}).get(SpanAttributes.KIND) == kind
    ]


def messages(span):
    return [
        (
            e.attributes[MessageAttributes.SENDER],
            e.attributes[MessageAttributes.CONTENT],
        )
        for e in span.events
        if e.name == MessageAttributes.EVENT_NAME
    ]


# ---------------------------------------------------------------------------
# Messages have no rules
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "emit,expected",
    [
        (lambda: None, []),
        (lambda: ags.user_message("only the user"), [("end_user", "only the user")]),
        (lambda: ags.agent_message("only the agent"), [("agent", "only the agent")]),
        (
            lambda: [ags.user_message("a"), ags.user_message("b"), ags.user_message("c")],
            [("end_user", "a"), ("end_user", "b"), ("end_user", "c")],
        ),
        (
            lambda: [ags.agent_message("x"), ags.user_message("y")],
            [("agent", "x"), ("end_user", "y")],
        ),
    ],
    ids=["silent", "user-only", "agent-only", "user-burst", "agent-first"],
)
def test_any_combination_of_messages_is_valid(spans, emit, expected):
    """No shape is enforced, because real flows do not have one.

    Bursts, reply-plus-card, silent escalation and proactive nudges are all
    ordinary; a rule that made any of them impossible would be a bug.
    """
    with ags.conversation("c-messages"):
        with ags.turn():
            emit()

    (turn,) = by_kind(spans, SpanKind.TURN)
    assert messages(turn) == expected


def test_messages_keep_their_order_and_metadata(spans):
    with ags.conversation("c-order"):
        with ags.turn():
            ags.agent_message("Here are your recent orders:")
            ags.agent_message("#1, #2, #3", metadata={"card_type": "order_list"})

    (turn,) = by_kind(spans, SpanKind.TURN)
    card = turn.events[1]
    assert json.loads(card.attributes[MessageAttributes.METADATA]) == {
        "card_type": "order_list"
    }
    assert turn.events[0].timestamp <= card.timestamp


def test_a_message_outside_a_turn_gets_one_of_its_own(spans):
    """A proactive nudge is still an exchange, just a one-sided one."""
    with ags.conversation("c-nudge"):
        ags.agent_message("Still there?")

    (turn,) = by_kind(spans, SpanKind.TURN)
    assert messages(turn) == [("agent", "Still there?")]


@pytest.mark.parametrize("open_turn", [
    lambda: ags.turn("ask"),
    lambda: ags.turn(name="ask"),
])
def test_a_turn_can_be_named_positionally_or_by_keyword(spans, open_turn):
    """``turn("ask")`` binds to the decorator's ``func`` parameter, so without
    an explicit string check it fails the callable test and the name is
    discarded in silence — leaving every turn in production named "turn"."""
    with ags.conversation("c-named"):
        with open_turn():
            ags.user_message("hello")

    (turn,) = by_kind(spans, SpanKind.TURN)
    assert turn.name == "ask"
    assert turn.attributes[SpanAttributes.ENTITY_NAME] == "ask"


def test_a_deferred_turn_takes_messages_on_its_scope(spans):
    """A turn kept open past its block is no longer the active one, so the
    module-level call would file the reply under a turn of its own — which is
    silently wrong data, the one thing worse than none."""
    with ags.conversation("c-deferred"):
        with ags.turn("websocket") as deferred:
            ags.user_message("ping")
            deferred.keep_open()

        deferred.agent_message("pong")
        deferred.end(complete=True)

    (turn,) = by_kind(spans, SpanKind.TURN)
    assert messages(turn) == [("end_user", "ping"), ("agent", "pong")]


def test_the_module_level_call_would_have_orphaned_it(spans):
    """The failure the method above exists to prevent, pinned so it stays the
    documented difference rather than something that quietly changes."""
    with ags.conversation("c-orphan"):
        with ags.turn("websocket") as deferred:
            ags.user_message("ping")
            deferred.keep_open()

        ags.agent_message("pong")
        deferred.end(complete=True)

    turns = by_kind(spans, SpanKind.TURN)
    assert len(turns) == 2
    assert [messages(t) for t in turns] == [[("agent", "pong")], [("end_user", "ping")]]


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


def test_tool_records_arguments_and_response(spans):
    """Everything track_action() asked users to type is measured instead."""

    @ags.tool
    def database_lookup(user_id: str, table: str = "users"):
        return "User found, email: user***@example.com"

    with ags.conversation("c-tool"):
        with ags.turn():
            database_lookup("user-12345")

    (tool,) = by_kind(spans, SpanKind.TOOL)
    assert tool.attributes[ToolAttributes.NAME] == "database_lookup"
    assert json.loads(tool.attributes[ToolAttributes.ARGUMENTS]) == {
        "user_id": "user-12345",
        "table": "users",
    }
    assert "user***@example.com" in tool.attributes[ToolAttributes.RESPONSE]
    assert tool.end_time > tool.start_time


def test_a_failed_tool_is_still_a_row_and_still_raises(spans):
    @ags.tool
    def flaky():
        raise ValueError("upstream 503")

    with ags.conversation("c-tool-fail"):
        with ags.turn():
            with pytest.raises(ValueError, match="upstream 503"):
                flaky()

    (tool,) = by_kind(spans, SpanKind.TOOL)
    assert "upstream 503" in tool.attributes[ToolAttributes.ERROR]
    assert tool.status.status_code.name == "ERROR"


def test_tool_name_override_matters_for_escalation_metrics(spans):
    """Human Escalation Rate keys off specific action names."""

    @ags.tool(name="fallback_to_human")
    def escalate(reason: str):
        return "escalated"

    with ags.conversation("c-escalate"):
        with ags.turn():
            escalate(reason="explicit user request")

    (tool,) = by_kind(spans, SpanKind.TOOL)
    assert tool.attributes[ToolAttributes.NAME] == "fallback_to_human"


# ---------------------------------------------------------------------------
# Buttons and attachments — things no decorator can observe
# ---------------------------------------------------------------------------


def test_a_button_click_is_not_a_message(spans):
    """It would read as one in a transcript a customer sees, and it isn't."""
    with ags.conversation("c-button"):
        with ags.turn():
            ags.user_message("do you have this in blue?")
            ags.button("size_picker", "Medium", "M", metadata={"variant": "A"})

    (turn,) = by_kind(spans, SpanKind.TURN)
    assert messages(turn) == [("end_user", "do you have this in blue?")]

    (button,) = by_kind(spans, SpanKind.BUTTON)
    assert button.attributes[ButtonAttributes.EVENT] == "size_picker"
    assert button.attributes[ButtonAttributes.LABEL] == "Medium"
    assert button.attributes[ButtonAttributes.VALUE] == "M"
    assert json.loads(button.attributes[SpanAttributes.METADATA]) == {"variant": "A"}
    assert button.attributes[TurnAttributes.ID] == turn.attributes[TurnAttributes.ID]


def test_attachments_record_descriptors_and_never_content(spans):
    class Upload:
        def __init__(self, filename, size, content_type):
            self.filename = filename
            self.size = size
            self.content_type = content_type
            self.content = b"x" * size  # must not travel in the span

    with ags.conversation("c-files"):
        with ags.turn():
            ags.record_attachments(
                [Upload("receipt.pdf", 20_000, "application/pdf")],
                sender="end_user",
            )

    (attachment,) = by_kind(spans, SpanKind.ATTACHMENT)
    assert attachment.attributes[AttachmentAttributes.COUNT] == 1
    assert attachment.attributes[AttachmentAttributes.SENDER] == "end_user"
    files = json.loads(attachment.attributes[AttachmentAttributes.FILES])
    assert files == [
        {"name": "receipt.pdf", "size": 20_000, "mime_type": "application/pdf"}
    ]
    assert "xxxx" not in json.dumps(dict(attachment.attributes))


def test_attachment_descriptors_survive_an_uncooperative_object(spans):
    with ags.conversation("c-files-odd"):
        with ags.turn():
            ags.record_attachments([object(), "invoice.png", {"name": "a.txt", "size": 3}])

    (attachment,) = by_kind(spans, SpanKind.ATTACHMENT)
    assert json.loads(attachment.attributes[AttachmentAttributes.FILES]) == [
        {},
        {"name": "invoice.png"},
        {"name": "a.txt", "size": 3},
    ]


# ---------------------------------------------------------------------------
# Tokens
# ---------------------------------------------------------------------------


class _Detail:
    def __init__(self, **kw):
        self.__dict__.update(kw)


class OpenAIUsage:
    """prompt_tokens INCLUDES cached — the trap this normalizes away."""

    def __init__(self, prompt, completion, cached=0, reasoning=0):
        self.prompt_tokens = prompt
        self.completion_tokens = completion
        self.prompt_tokens_details = _Detail(cached_tokens=cached, audio_tokens=0)
        self.completion_tokens_details = _Detail(
            reasoning_tokens=reasoning, audio_tokens=0
        )


def test_cached_openai_tokens_are_not_double_counted(spans):
    with ags.conversation("c-tokens"):
        with ags.turn():
            record_llm_call(
                **from_openai(OpenAIUsage(prompt=1200, completion=95, cached=1000),
                              "gpt-4o")
            )

    (llm,) = by_kind(spans, SpanKind.LLM)
    assert llm.attributes[LLMAttributes.INPUT_TOKENS] == 200
    assert llm.attributes[LLMAttributes.CACHE_READ_TOKENS] == 1000


def test_reasoning_tokens_are_recorded_but_never_added_to_the_total(spans):
    with ags.conversation("c-reasoning"):
        with ags.turn():
            record_llm_call(
                **from_openai(OpenAIUsage(prompt=45, completion=62, reasoning=40),
                              "o3-mini")
            )

    (llm,) = by_kind(spans, SpanKind.LLM)
    assert llm.attributes[LLMAttributes.REASONING_TOKENS] == 40
    assert llm.attributes[LLMAttributes.OUTPUT_TOKENS] == 62, (
        "reasoning is a subset of output, not an addition to it"
    )
    billable = sum(
        llm.attributes.get(name, 0) for name in LLMAttributes.BILLABLE
    )
    assert billable == 107


def test_no_cost_is_computed_locally(spans):
    """
    The SDK sends counts; the backend prices them. Nothing here may carry a
    cost, however well known the model — a client-side figure would be frozen
    at whatever release the caller pinned, would differ between customers on
    different versions, and is forgeable by anyone holding a write key.

    An unknown model is the same case as a known one, which is the point: it
    is no longer a gap the SDK has to have an opinion about.
    """
    with ags.conversation("c-no-local-cost"):
        with ags.turn():
            record_llm_call(system="openai", model="gpt-4o",
                            input_tokens=1200, output_tokens=95)
            record_llm_call(system="openai", model="ft:something-nobody-priced",
                            input_tokens=10, output_tokens=5)

    priced, unpriced = by_kind(spans, SpanKind.LLM)
    for llm in (priced, unpriced):
        assert not any(
            name.endswith("cost_usd") for name in llm.attributes
        ), "cost must be derived by the backend, not sent"
    # The inputs it derives from are all still on the wire.
    assert priced.attributes[LLMAttributes.REQUEST_MODEL] == "gpt-4o"
    assert priced.attributes[LLMAttributes.INPUT_TOKENS] == 1200
    assert priced.attributes[LLMAttributes.OUTPUT_TOKENS] == 95


# ---------------------------------------------------------------------------
# What must NOT be captured
# ---------------------------------------------------------------------------


def test_nothing_is_recorded_outside_a_conversation(spans):
    @ags.tool
    def lookup():
        return "ok"

    assert lookup() == "ok"
    ags.user_message("nobody is listening")
    record_llm_call(system="openai", model="gpt-4o", input_tokens=10)

    assert spans.get_finished_spans() == ()


def test_enabled_false_disables_a_single_conversation(spans):
    """Applications commonly have both a save=False flag and a testing mode."""
    with ags.conversation("c-not-real", enabled=False):
        with ags.turn():
            ags.user_message("this is a test run")

    assert spans.get_finished_spans() == ()


def test_an_unfinished_turn_arrives_marked_with_its_children(spans):
    """A crashed turn is exported as the failure it was, family intact.

    Buffering still matters here — not to retract anything, but so the turn
    and the tool span it explains land in the same payload and ingest can
    keep the whole half-exchange out of the transcript atomically.
    """

    @ags.tool
    def lookup():
        return "found"

    with ags.conversation("c-crash"):
        with pytest.raises(RuntimeError):
            with ags.turn():
                ags.user_message("this turn is going to blow up")
                lookup()
                raise RuntimeError("agent crashed mid-turn")

    kinds = sorted(
        (s.attributes or {}).get(SpanAttributes.KIND)
        for s in spans.get_finished_spans()
    )
    assert kinds == [SpanKind.TOOL, SpanKind.TURN]

    (turn,) = by_kind(spans, SpanKind.TURN)
    assert turn.attributes[TurnAttributes.COMPLETE] is False
    assert (
        turn.attributes[TurnAttributes.INCOMPLETE_REASON]
        == TurnAttributes.REASON_ERROR
    )
    assert turn.status.status_code.name == "ERROR"
    assert any(e.name == "exception" for e in turn.events), (
        "the crash itself must be on the span"
    )
    # The messages ride along — archived for lead recovery, kept out of the
    # transcript by the complete=false marker downstream.
    assert messages(turn) == [("end_user", "this turn is going to blow up")]


def test_a_completed_turn_after_a_failed_one_still_exports(spans):
    with ags.conversation("c-recover"):
        with pytest.raises(RuntimeError):
            with ags.turn():
                raise RuntimeError("first one fails")
        with ags.turn():
            ags.user_message("second one works")

    failed, worked = by_kind(spans, SpanKind.TURN)
    assert failed.attributes[TurnAttributes.COMPLETE] is False
    assert worked.attributes[TurnAttributes.COMPLETE] is True
    assert messages(worked) == [("end_user", "second one works")]


# ---------------------------------------------------------------------------
# Conversation metadata reaches every span
# ---------------------------------------------------------------------------


def test_conversation_metadata_is_stamped_on_every_span(spans):
    @ags.tool
    def lookup():
        return "ok"

    with ags.conversation(
        "c-meta",
        customer_id="user-12345",
        customer_ip_address="203.0.113.42",
        device="desktop",
        source="web",
        language="en",
        metadata={"session_id": "sess_abc123"},
    ):
        with ags.turn():
            lookup()

    for span in spans.get_finished_spans():
        assert span.attributes[ConversationAttributes.ID] == "c-meta"
        assert span.attributes[ConversationAttributes.CUSTOMER_ID] == "user-12345"
        assert span.attributes[ConversationAttributes.DEVICE] == "desktop"


def test_a_missing_conversation_id_is_generated_not_rejected(spans):
    with ags.conversation() as scope:
        with ags.turn():
            ags.user_message("hi")

    assert scope.conversation_id.startswith("conv_")
    (turn,) = by_kind(spans, SpanKind.TURN)
    assert turn.attributes[ConversationAttributes.ID] == scope.conversation_id


# ---------------------------------------------------------------------------
# The ingest payload
# ---------------------------------------------------------------------------


def test_payload_groups_by_conversation_and_orders_spans(spans):
    for cid in ("c-one", "c-two"):
        with ags.conversation(cid, device="mobile"):
            with ags.turn():
                ags.user_message("hello")

    payload = build_payload(spans.get_finished_spans())
    assert [c["conversation_id"] for c in payload["conversations"]] == ["c-one", "c-two"]
    for block in payload["conversations"]:
        assert block["device"] == "mobile"
        started = [s["started_at"] for s in block["spans"]]
        assert started == sorted(started), (
            "ingest projects in this order, so export order must not matter"
        )


def test_open_conversation_is_an_ordinary_span(spans):
    """The visit phase rides the span pipeline like everything else.

    It used to bypass it — a hand-built payload POSTed through the concrete
    exporter's private method, the one call nothing OTLP-shaped could ever
    satisfy. Now it is a ``conversation`` span: the kind carries the "widget
    loaded, nobody typed" semantics, and ingest derives engagement from the
    span kinds present instead of reading a side-channel flag.
    """
    ags.open_conversation("c-visit", device="mobile", source="web")

    (visit,) = spans.get_finished_spans()
    assert visit.attributes[SpanAttributes.KIND] == SpanKind.CONVERSATION
    assert visit.attributes[ConversationAttributes.ID] == "c-visit"

    payload = build_payload(spans.get_finished_spans())
    (block,) = payload["conversations"]
    assert block["conversation_id"] == "c-visit"
    assert block["device"] == "mobile"
    assert block["source"] == "web"
    assert [s["kind"] for s in block["spans"]] == [SpanKind.CONVERSATION]


def test_record_llm_call_error_keeps_billed_tokens(spans):
    """A stream that died halfway still spent its tokens — both facts go out."""
    with ags.conversation("c-billed-failure"):
        record_llm_call(
            system="openai",
            model="gpt-4o",
            input_tokens=10,
            output_tokens=3,
            error=RuntimeError("connection reset mid-stream"),
        )

    (llm,) = by_kind(spans, SpanKind.LLM)
    assert llm.attributes[LLMAttributes.INPUT_TOKENS] == 10
    assert llm.attributes[LLMAttributes.OUTPUT_TOKENS] == 3
    assert llm.attributes[LLMAttributes.ERROR] == "connection reset mid-stream"
    assert llm.status.status_code.name == "ERROR"
    assert any(e.name == "exception" for e in llm.events)


def test_every_span_is_serialized_whole(spans):
    """Decision 9: nothing is thrown away from this point on."""
    with ags.conversation("c-archive"):
        with ags.turn():
            ags.user_message("keep all of this")

    (turn,) = by_kind(spans, SpanKind.TURN)
    payload = span_to_dict(turn)

    assert payload["kind"] == SpanKind.TURN
    assert payload["attributes"][TurnAttributes.COMPLETE] is True
    assert payload["events"][0]["name"] == MessageAttributes.EVENT_NAME
    otel = payload["otel"]
    assert otel["span_kind"] == "INTERNAL"
    assert otel["scope"]["name"] == "agentsight-test"
    assert otel["dropped"] == {"attributes": 0, "events": 0, "links": 0}
    assert "resource" in otel


# ---------------------------------------------------------------------------
# Failure isolation
# ---------------------------------------------------------------------------


def test_init_with_a_bad_key_disables_rather_than_raises(monkeypatch):
    monkeypatch.delenv("AGENTSIGHT_API_KEY", raising=False)
    monkeypatch.setattr(core._state, "enabled", False)

    assert ags.init(api_key="not-a-key") is False
    assert ags.is_enabled() is False


def test_init_accepts_a_custom_exporter_without_a_key(monkeypatch):
    """The transport seam: any OTel SpanExporter slots in behind the same
    buffering and batching, and the API key — which exists only to
    authenticate the default transport — stops being required with one."""
    monkeypatch.delenv("AGENTSIGHT_API_KEY", raising=False)
    monkeypatch.setattr(core._state, "enabled", False)

    exporter = InMemorySpanExporter()
    assert ags.init(span_exporter=exporter, auto_instrument=False) is True
    try:
        with ags.conversation("c-custom-transport"):
            with ags.turn():
                ags.user_message("through a custom transport")
        ags.flush()
        kinds = [
            (s.attributes or {}).get(SpanAttributes.KIND)
            for s in exporter.get_finished_spans()
        ]
        assert SpanKind.TURN in kinds
    finally:
        ags.shutdown()


def test_everything_is_a_pass_through_when_disabled():
    """The invariant: the wrapped function behaves identically either way."""

    @ags.tool
    def lookup(user_id):
        return f"found {user_id}"

    @ags.turn(infer=True)
    def handle(text):
        return "answered"

    assert ags.is_enabled() is False
    assert lookup("u-1") == "found u-1"
    assert handle("hello") == "answered"
    ags.user_message("nobody home")
    ags.flush()


def test_a_broken_tracer_cannot_break_the_users_agent(spans, monkeypatch):
    def explode(*args, **kwargs):
        raise RuntimeError("tracer is on fire")

    @ags.tool
    def lookup():
        return "still works"

    monkeypatch.setattr(core._state.tracer, "start_as_current_span", explode)
    monkeypatch.setattr(core._state.tracer, "start_span", explode)

    with ags.conversation("c-broken"):
        with ags.turn():
            assert lookup() == "still works"
            ags.user_message("and this does not raise")


def test_a_cancelled_call_is_not_an_error(spans):
    """CancelledError is the async caller walking away — the same event
    GeneratorExit is for sync streams. Recording it as an error would make an
    error-rate metric measure user behaviour instead of provider health. The
    tokens billed before the cancel still count."""
    import asyncio

    with ags.conversation("c-cancelled"):
        record_llm_call(
            system="openai",
            model="gpt-4o",
            input_tokens=10,
            output_tokens=2,
            error=asyncio.CancelledError(),
        )

    (llm,) = by_kind(spans, SpanKind.LLM)
    assert LLMAttributes.ERROR not in llm.attributes
    assert llm.status.status_code.name != "ERROR"
    assert llm.attributes[LLMAttributes.INPUT_TOKENS] == 10


def test_a_bare_exception_never_yields_a_falsy_error_marker(spans):
    """str(RuntimeError()) is "" — an ERROR span whose marker is falsy would
    slip past any truthiness filter downstream."""
    with ags.conversation("c-bare"):
        record_llm_call(system="openai", model="gpt-4o", error=RuntimeError())

    (llm,) = by_kind(spans, SpanKind.LLM)
    assert llm.attributes[LLMAttributes.ERROR] == "RuntimeError"
    assert llm.status.status_code.name == "ERROR"


def test_init_environment_is_inherited_by_conversations(spans, monkeypatch):
    """init(environment=...) is the deployment-wide default; a conversation
    that names its own environment overrides it."""
    monkeypatch.setattr(core._state, "environment", "development")

    with ags.conversation("c-inherit"):
        with ags.turn():
            ags.user_message("hi")
    with ags.conversation("c-explicit", environment="production"):
        with ags.turn():
            ags.user_message("hi")

    payload = build_payload(spans.get_finished_spans())
    by_id = {c["conversation_id"]: c for c in payload["conversations"]}
    assert by_id["c-inherit"]["environment"] == "development"
    assert by_id["c-explicit"]["environment"] == "production"


# ---------------------------------------------------------------------------
# Data entities: one key, on everything the conversation records
# ---------------------------------------------------------------------------


def test_a_data_entity_reaches_every_span_and_the_block(spans):
    """Every kind, because each is created by a different path and a key missing
    from one of them is a span the row could be rebuilt without."""

    @ags.tool
    def look_up(city):
        return city

    @ags.task
    def plan():
        return "ok"

    with ags.conversation("c-entity", data_entity="hotel-paris"):
        with ags.turn("ask"):
            ags.user_message("hi")
            look_up("paris")
            plan()
            record_llm_call(**from_openai(OpenAIUsage(prompt=10, completion=5), "gpt-4o"))
            ags.agent_message("hello")
        ags.button("feedback", "Helpful?", "yes")
        ags.record_attachments([{"name": "a.pdf"}])
        ags.update_metadata({"seen": True})

    finished = spans.get_finished_spans()
    kinds = {s.attributes[SpanAttributes.KIND] for s in finished}
    assert kinds == {
        SpanKind.TURN,
        SpanKind.TOOL,
        SpanKind.TASK,
        SpanKind.LLM,
        SpanKind.BUTTON,
        SpanKind.ATTACHMENT,
        SpanKind.CONVERSATION,
    }
    for span in finished:
        assert span.attributes[ConversationAttributes.DATA_ENTITY] == "hotel-paris"

    (block,) = build_payload(finished)["conversations"]
    assert block["data_entity"] == "hotel-paris"


def test_no_data_entity_sends_nothing_at_all(spans):
    """Absent is the default for every existing integration, and it has to stay
    byte-identical to what they send today."""
    with ags.conversation("c-none"):
        with ags.turn():
            ags.user_message("hi")

    finished = spans.get_finished_spans()
    assert ConversationAttributes.DATA_ENTITY not in finished[0].attributes
    assert "data_entity" not in build_payload(finished)["conversations"][0]


def test_open_conversation_carries_a_data_entity(spans):
    ags.open_conversation("c-visit", data_entity="hotel-paris")

    (block,) = build_payload(spans.get_finished_spans())["conversations"]
    assert block["data_entity"] == "hotel-paris"


def test_the_conversation_decorator_keeps_a_data_entity_on_every_call(spans):
    """The decorator rebuilds its scope per call from the stored kwargs, so a
    field missing from those is lost with no error."""

    @ags.conversation(data_entity="hotel-paris")
    def handle():
        with ags.turn():
            ags.user_message("hi")

    handle()
    handle()

    blocks = build_payload(spans.get_finished_spans())["conversations"]
    assert [b["data_entity"] for b in blocks] == ["hotel-paris", "hotel-paris"]


def test_the_turn_decorator_forwards_a_data_entity(spans):
    @ags.turn(id_from="session", data_entity="hotel-paris")
    def handle(session):
        ags.user_message("hi")

    handle("c-turn")

    (block,) = build_payload(spans.get_finished_spans())["conversations"]
    assert block["conversation_id"] == "c-turn"
    assert block["data_entity"] == "hotel-paris"


def test_a_default_data_entity_is_inherited_and_can_be_overridden(spans, monkeypatch):
    monkeypatch.setattr(core._state, "data_entity", "hotel-rome")

    with ags.conversation("c-inherit"):
        with ags.turn():
            ags.user_message("hi")
    with ags.conversation("c-explicit", data_entity="hotel-paris"):
        with ags.turn():
            ags.user_message("hi")
    with ags.conversation("c-blank", data_entity="   "):
        with ags.turn():
            ags.user_message("hi")

    payload = build_payload(spans.get_finished_spans())
    by_id = {c["conversation_id"]: c for c in payload["conversations"]}
    assert by_id["c-inherit"]["data_entity"] == "hotel-rome"
    assert by_id["c-explicit"]["data_entity"] == "hotel-paris"
    assert by_id["c-blank"]["data_entity"] == "hotel-rome"


def test_a_decorated_handler_picks_up_a_default_set_after_decoration(spans, monkeypatch):
    """Decoration happens at import, which is before init()."""

    @ags.conversation()
    def handle():
        with ags.turn():
            ags.user_message("hi")

    monkeypatch.setattr(core._state, "data_entity", "hotel-rome")
    handle()

    (block,) = build_payload(spans.get_finished_spans())["conversations"]
    assert block["data_entity"] == "hotel-rome"


# -- a turn joins the conversation it runs in --------------------------------
#
# turn() takes the conversation's fields too. A turn that runs inside an open
# conversation hands them to it: they fill what the conversation has not said
# and replace nothing, so a decorator's constants cannot undo, call after call,
# what the conversation learned in between.


def _block(spans, conversation_id):
    payload = build_payload(spans.get_finished_spans())
    return {c["conversation_id"]: c for c in payload["conversations"]}[conversation_id]


def test_the_with_form_of_turn_gives_its_fields_to_the_conversation(spans):
    with ags.conversation("c-with"):
        with ags.turn(data_entity="hotel-paris", device="mobile"):
            ags.user_message("hi")

    block = _block(spans, "c-with")
    assert block["data_entity"] == "hotel-paris"
    assert block["device"] == "mobile"
    # Applied before the turn starts, so the turn's own span carries them.
    (turn,) = by_kind(spans, SpanKind.TURN)
    assert turn.attributes[ConversationAttributes.DATA_ENTITY] == "hotel-paris"


def test_a_decorated_turn_gives_its_fields_to_the_conversation_it_runs_in(spans):
    @ags.turn(data_entity="hotel-paris", language="fr")
    def handle():
        ags.user_message("hi")

    with ags.conversation("c-nested"):
        handle()

    block = _block(spans, "c-nested")
    assert block["data_entity"] == "hotel-paris"
    assert block["language"] == "fr"


def test_an_async_decorated_turn_does_the_same(spans):
    @ags.turn(data_entity="hotel-paris")
    async def handle():
        ags.user_message("hi")

    async def main():
        async with ags.conversation("c-async"):
            await handle()

    asyncio.run(main())

    assert _block(spans, "c-async")["data_entity"] == "hotel-paris"


def test_fields_on_a_turn_outside_any_conversation_still_record_nothing(spans):
    with ags.turn(data_entity="hotel-paris"):
        ags.user_message("hi")

    assert spans.get_finished_spans() == ()


def test_a_turn_that_names_the_open_conversation_joins_it(spans):
    """A second scope for the same id hid the first for the length of the call:
    the conversation's own fields went missing from the turn's spans, and a
    metadata update made inside was lost when the call returned."""

    @ags.turn(id_from="session")
    def handle(session):
        ags.user_message("hi")
        ags.update_metadata({"seen": True})

    with ags.conversation("c-same", data_entity="hotel-paris", customer_id="u-1") as scope:
        handle("c-same")

    (turn,) = by_kind(spans, SpanKind.TURN)
    assert turn.attributes[ConversationAttributes.DATA_ENTITY] == "hotel-paris"
    assert turn.attributes[ConversationAttributes.CUSTOMER_ID] == "u-1"
    assert scope.metadata == {"seen": True}
    assert _block(spans, "c-same")["metadata"] == {"seen": True}


def test_an_id_that_is_not_a_string_still_names_the_open_conversation(spans):
    @ags.turn(id_from=lambda arguments: arguments["session"])
    def handle(session):
        ags.user_message("hi")

    with ags.conversation("42", data_entity="hotel-paris"):
        handle(42)

    assert _block(spans, "42")["data_entity"] == "hotel-paris"


def test_a_turn_for_another_conversation_still_opens_its_own(spans):
    @ags.turn(id_from="session", data_entity="hotel-rome")
    def handle(session):
        ags.user_message("hi")

    with ags.conversation("c-outer", data_entity="hotel-paris"):
        handle("c-other")
        with ags.turn():
            ags.user_message("outer")

    assert _block(spans, "c-other")["data_entity"] == "hotel-rome"
    assert _block(spans, "c-outer")["data_entity"] == "hotel-paris"


def test_a_streaming_turn_that_joins_keeps_the_conversation_while_it_drains(spans):
    @ags.turn(id_from="session")
    def handler(session):
        def body():
            yield "chunk"
            ags.agent_message("answered")

        return body()

    with ags.conversation("c-stream", data_entity="hotel-paris"):
        stream = handler("c-stream")
    list(stream)  # drained after the conversation's block has exited

    (turn,) = by_kind(spans, SpanKind.TURN)
    assert messages(turn) == [("agent", "answered")]
    assert turn.attributes[ConversationAttributes.DATA_ENTITY] == "hotel-paris"


def test_a_turn_never_replaces_what_the_conversation_already_says(spans):
    with ags.conversation("c-keep", device="mobile", metadata={"plan": "pro"}):
        with ags.turn(
            device="desktop",
            language="en",
            metadata={"plan": "free", "channel": "web"},
        ):
            ags.user_message("hi")

    block = _block(spans, "c-keep")
    assert block["device"] == "mobile"
    assert block["language"] == "en"
    assert block["metadata"] == {"plan": "pro", "channel": "web"}


def test_a_decorators_constants_do_not_undo_what_the_conversation_learned(spans):
    """The decorator's fields are the same on every call. Replacing instead of
    filling would reset, on each one, whatever happened since the last."""

    @ags.turn(metadata={"escalated": False}, name="New chat")
    def handle():
        ags.user_message("hi")

    with ags.conversation("c-learn") as scope:
        handle()
        ags.update_metadata({"escalated": True})
        scope.set_fields({"name": "Refund"})
        handle()

        assert scope.metadata == {"escalated": True}

    assert _block(spans, "c-learn")["name"] == "Refund"


def test_a_fill_does_not_follow_a_decorated_conversation_into_its_next_call(spans):
    @ags.conversation()
    def handle(key):
        with ags.turn(data_entity=key):
            ags.user_message("hi")

    handle("hotel-paris")
    handle(None)

    first, second = build_payload(spans.get_finished_spans())["conversations"]
    assert first["data_entity"] == "hotel-paris"
    assert "data_entity" not in second


class _Unprintable:
    def __str__(self):
        raise RuntimeError("no string form")


@pytest.mark.parametrize(
    "fields",
    [
        {"metadata": "abc"},
        {"no_such_field": 1},
        {"customer_ip_address": "not-an-ip"},
        {"device": _Unprintable()},
    ],
    ids=["metadata-not-a-dict", "unknown-keyword", "bad-ip", "value-that-raises"],
)
def test_bad_fields_on_a_turn_never_raise(spans, fields):
    """This runs on the way into the caller's own block."""

    @ags.turn(**fields)
    def handle():
        ags.user_message("decorated")

    with ags.conversation("c-bad"):
        with ags.turn(**fields):
            ags.user_message("with")
        handle()

    assert len(by_kind(spans, SpanKind.TURN)) == 2


def test_a_turn_naming_a_disabled_conversation_records_nothing(spans):
    """It used to open an enabled scope of its own and record anyway."""

    @ags.turn(id_from="session")
    def handle(session):
        ags.user_message("hi")

    with ags.conversation("c-off", enabled=False):
        handle("c-off")

    assert spans.get_finished_spans() == ()


def test_a_turn_can_still_switch_itself_off_by_naming_the_conversation(spans):
    @ags.turn(id_from="session", enabled=False)
    def handle(session):
        ags.user_message("not recorded")

    with ags.conversation("c-on"):
        handle("c-on")
        with ags.turn():
            ags.user_message("recorded")

    (turn,) = by_kind(spans, SpanKind.TURN)
    assert messages(turn) == [("end_user", "recorded")]


# -- which data entity a conversation ends up with ----------------------------


def _kept_warnings(caplog):
    return [r for r in caplog.records if "keeps the first data entity" in r.getMessage()]


def test_a_different_key_on_a_turn_is_kept_out_and_reported_once(spans, caplog):
    """The backend keeps the first key a conversation receives. Saying so here
    is the only place the developer would see it."""
    with caplog.at_level("WARNING", logger="agentsight"):
        with ags.conversation("c-first", data_entity="hotel-paris"):
            with ags.turn(data_entity="hotel-rome"):
                ags.user_message("one")
            with ags.turn(data_entity="hotel-oslo"):
                ags.user_message("two")

    for span in spans.get_finished_spans():
        assert span.attributes[ConversationAttributes.DATA_ENTITY] == "hotel-paris"
    assert len(_kept_warnings(caplog)) == 1


def test_the_same_key_in_another_casing_is_not_a_conflict(spans, caplog):
    with caplog.at_level("WARNING", logger="agentsight"):
        with ags.conversation("c-case", data_entity="Hotel-Paris"):
            with ags.turn(data_entity="hotel-paris"):
                ags.user_message("hi")

    assert _block(spans, "c-case")["data_entity"] == "Hotel-Paris"
    assert _kept_warnings(caplog) == []


def test_a_key_named_on_the_first_turn_beats_the_deployment_default(spans, monkeypatch):
    """A per-conversation key wins over the default, and before the first span
    nothing has reached the backend to contradict it."""
    monkeypatch.setattr(core._state, "data_entity", "the-default")

    with ags.conversation("c-default"):
        with ags.turn(data_entity="hotel-paris"):
            ags.user_message("hi")
        with ags.turn():
            ags.user_message("again")

    for span in spans.get_finished_spans():
        assert span.attributes[ConversationAttributes.DATA_ENTITY] == "hotel-paris"


def test_once_something_is_recorded_under_the_default_it_stays(spans, monkeypatch, caplog):
    """By then the backend has the default, and it keeps the first key. Spans
    that switched would disagree with the row for the rest of the conversation."""
    monkeypatch.setattr(core._state, "data_entity", "the-default")

    with caplog.at_level("WARNING", logger="agentsight"):
        with ags.conversation("c-late"):
            with ags.turn():
                ags.user_message("first")
            with ags.turn(data_entity="hotel-paris"):
                ags.user_message("second")

    for span in spans.get_finished_spans():
        assert span.attributes[ConversationAttributes.DATA_ENTITY] == "the-default"
    (warning,) = _kept_warnings(caplog)
    assert "deployment default" in warning.getMessage()


def test_a_key_set_by_a_turn_is_then_the_conversations_own(spans, monkeypatch, caplog):
    monkeypatch.setattr(core._state, "data_entity", "the-default")

    with caplog.at_level("WARNING", logger="agentsight"):
        with ags.conversation("c-own") as scope:
            scope.fill({"data_entity": "hotel-paris"})  # nothing recorded yet
            scope.fill({"data_entity": "hotel-rome"})  # the first one stays

    assert scope.attributes[ConversationAttributes.DATA_ENTITY] == "hotel-paris"
    assert len(_kept_warnings(caplog)) == 1


def test_what_still_records_the_default_is_a_scope_opened_without_the_key(spans, monkeypatch):
    """Why the docs say to choose a default or per-conversation keys. The visit
    phase has no turn to name the key on, so it records the default, and the
    backend keeps the first key it receives."""
    monkeypatch.setattr(core._state, "data_entity", "the-default")

    ags.open_conversation("c-visit")

    assert _block(spans, "c-visit")["data_entity"] == "the-default"


def test_the_first_data_entity_in_a_batch_wins(spans):
    """The backend keeps the first key a conversation receives, so the block
    must carry that one, or the outcome would turn on where a batch boundary
    fell. Every other field is last-wins and has to stay that way."""
    with ags.conversation("c-twice", data_entity="hotel-paris", device="mobile"):
        with ags.turn():
            ags.user_message("first")
    with ags.conversation("c-twice", data_entity="hotel-rome", device="desktop"):
        with ags.turn():
            ags.user_message("second")

    (block,) = build_payload(spans.get_finished_spans())["conversations"]
    assert block["data_entity"] == "hotel-paris"
    assert block["device"] == "desktop"


def test_export_failure_warnings_are_rate_limited():
    """A down backend warns once a minute, not once a second."""

    class CountingLogger:
        def __init__(self):
            self.warnings = []

        def warning(self, message, *args):
            self.warnings.append(message % args if args else message)

        def debug(self, *args, **kwargs):
            pass

        def error(self, *args, **kwargs):
            pass

    from agentsight.sdk.exporter import AgentSightSpanExporter

    logger = CountingLogger()
    exporter = AgentSightSpanExporter("http://127.0.0.1:9", "ags_key", logger)

    for _ in range(5):
        exporter._warn_dropped("batch dropped")
    assert len(logger.warnings) == 1, "four drops inside the window stay quiet"

    exporter._last_drop_warning = 0.0  # step past the window
    exporter._warn_dropped("batch dropped")
    assert len(logger.warnings) == 2
    assert "4 earlier drop(s) suppressed" in logger.warnings[1]
