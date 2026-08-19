"""What the SDK refuses to put on the wire, and why.

Ingest validates a payload as a whole and rejects it as a whole. The exporter
treats a 4xx as terminal and rate-limits its own complaint to one line a
minute. Put those together and a single malformed field — a user-agent string
in ``device``, a proxy chain in ``customer_ip_address``, one oversized value
inside ``metadata`` — is not a bad field. It is **every conversation in every
batch, silently, for the life of the process**.

So these are not input-validation niceties. Each one is a total-data-loss
failure caught before it leaves.
"""

import asyncio
import json

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

import agentsight as ags
from agentsight.sdk import core, serialization
from agentsight.sdk.exporter import build_payload
from agentsight.sdk.processors import TurnBufferingProcessor


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


@pytest.fixture(autouse=True)
def fresh_warnings():
    """The warn-once cache is process-wide by design; tests are not."""
    serialization._reset_warnings_for_tests()
    yield
    serialization._reset_warnings_for_tests()


def blocks(spans):
    payload = build_payload(spans.get_finished_spans())
    return {block["conversation_id"]: block for block in payload["conversations"]}


# ---------------------------------------------------------------------------
# Conversation fields: clamped, not passed through
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("field", ["customer_id", "device", "source", "language", "name"])
def test_an_over_length_field_is_clamped_rather_than_rejecting_the_batch(spans, field):
    """255 is the API's limit on every one of these, and it validates the
    whole payload at once — so an unclamped field costs the conversations
    beside it too, not just its own value."""
    with ags.conversation("c-long", **{field: "x" * 300}):
        with ags.turn():
            ags.user_message("hi")

    block = blocks(spans)["c-long"]
    assert len(block[field]) == 255


def test_an_over_length_conversation_id_is_clamped_and_still_groups(spans):
    with ags.conversation("c" * 300):
        with ags.turn():
            ags.user_message("hi")

    (conversation_id,) = blocks(spans)
    assert len(conversation_id) == 255


def test_a_field_at_the_limit_is_untouched(spans):
    with ags.conversation("c-exact", device="d" * 255):
        with ags.turn():
            ags.user_message("hi")

    assert blocks(spans)["c-exact"]["device"] == "d" * 255


@pytest.mark.parametrize(
    "address",
    ["not-an-ip", "203.0.113.1, 198.51.100.7", "unknown", "::/0", ""],
)
def test_an_unparseable_ip_is_dropped_not_sent(spans, address):
    """An IPAddressField rejects the payload. One conversation losing one
    column beats every conversation losing everything."""
    with ags.conversation("c-ip", customer_ip_address=address):
        with ags.turn():
            ags.user_message("hi")

    assert "customer_ip_address" not in blocks(spans)["c-ip"]


@pytest.mark.parametrize("address", ["203.0.113.7", "2001:db8::1", "  203.0.113.7  "])
def test_a_real_address_survives(spans, address):
    with ags.conversation("c-ip-ok", customer_ip_address=address):
        with ags.turn():
            ags.user_message("hi")

    assert blocks(spans)["c-ip-ok"]["customer_ip_address"] == address.strip()


def test_the_clamp_warning_is_emitted_once_not_per_call(caplog):
    """These fire from inside request handling. One warning per request would
    bury the line that mattered under thousands of copies of itself."""
    with caplog.at_level("WARNING", logger="agentsight"):
        for index in range(50):
            ags.conversation("c-%d" % index, device="x" * 300)

    assert sum("clamped" in r.message for r in caplog.records) == 1


# ---------------------------------------------------------------------------
# Environment: only slugs the backend has
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "supplied,expected",
    [
        ("production", "production"),
        ("development", "development"),
        ("prod", "production"),
        ("dev", "development"),
        ("  PROD  ", "production"),
        ("Development", "development"),
    ],
)
def test_known_environments_are_normalized_to_their_canonical_slug(spans, supplied, expected):
    """The backend stores the long form and accepts the shorthand only as a
    query-param convenience. The slug is the published wire value, so that is
    what goes out."""
    with ags.conversation("c-env", environment=supplied):
        with ags.turn():
            ags.user_message("hi")

    assert blocks(spans)["c-env"]["environment"] == expected


@pytest.mark.parametrize("supplied", ["staging", "local", "prd", "Production!"])
def test_an_unknown_environment_is_dropped_so_the_batch_survives(spans, supplied, caplog):
    """Ingest 400s the whole payload over an unknown slug. Dropped, this
    conversation still lands — against the agent's default environment."""
    with caplog.at_level("WARNING", logger="agentsight"):
        with ags.conversation("c-env-bad", environment=supplied):
            with ags.turn():
                ags.user_message("hi")

    assert "environment" not in blocks(spans)["c-env-bad"]
    assert any(
        "is not one the SDK has been able to confirm" in r.message
        for r in caplog.records
    )


def test_a_learned_custom_environment_reaches_the_wire(spans):
    """What the key preflight learns from /api/me/ is what
    conversation(environment=...) may send. Learned directly here — the
    preflight path itself is covered in test_key_preflight.py."""
    from agentsight import _settings

    _settings.learn_environments(["local"])

    with ags.conversation("c-env-custom", environment="local"):
        with ags.turn():
            ags.user_message("hi")

    assert blocks(spans)["c-env-custom"]["environment"] == "local"


def test_init_refuses_an_unknown_environment_loudly(caplog, valid_api_key):
    """At startup, while someone is watching — the alternative is finding out
    an hour later that nothing was ever delivered."""
    from agentsight.sdk.file_exporter import FileSpanExporter  # noqa: F401

    class Nowhere:
        def export(self, spans):
            return None

        def shutdown(self):
            return None

        def force_flush(self, timeout_millis=30_000):
            return True

    try:
        with caplog.at_level("ERROR", logger="agentsight"):
            assert ags.init(environment="staging", span_exporter=Nowhere(),
                            auto_instrument=False) is True
        assert core.default_environment() is None
        assert any("staging" in r.getMessage() for r in caplog.records)
    finally:
        ags.shutdown()


# ---------------------------------------------------------------------------
# Metadata: truncated per value, and always still JSON
# ---------------------------------------------------------------------------


def test_oversized_metadata_stays_parseable_and_keeps_its_small_keys(spans):
    """The failure this replaces: truncating the serialised document left
    invalid JSON, the projector's parse failed, and it stored `{}` — losing
    every small key beside the big one, with no error anywhere."""
    metadata = {"order_id": "A-1", "channel": "web", "transcript": "x" * 40_000}

    with ags.conversation("c-meta", metadata=metadata):
        with ags.turn():
            ags.user_message("hi")

    stored = blocks(spans)["c-meta"]["metadata"]
    assert stored["order_id"] == "A-1"
    assert stored["channel"] == "web"
    assert stored["transcript"].endswith(serialization.TRUNCATION_SUFFIX)


def test_metadata_leaves_as_an_object_not_a_json_string(spans):
    """Span attributes have to be primitives, so metadata is carried as a JSON
    string — but ingest stores conversation metadata in a JSON column without
    parsing it first, and a string handed to that column is stored as a string.
    Metadata filtering and the metadata-key endpoints then see nothing inside
    it. The wire block is ours to shape, so it is parsed back on the way out."""
    with ags.conversation("c-shape", metadata={"tier": "gold", "seats": 4}):
        with ags.turn():
            ags.user_message("hi")

    stored = blocks(spans)["c-shape"]["metadata"]
    assert isinstance(stored, dict)
    assert stored == {"tier": "gold", "seats": 4}


def test_metadata_is_parsed_once_per_distinct_document_not_once_per_span(
    spans, monkeypatch
):
    """Every span carries the same serialised document by design — the
    conversation outlives any single process, so no span can own it. Parsing
    it back once per span cost the export thread about a quarter of its
    payload-build budget; it is memoised per conversation now, keyed on the
    raw string."""
    from agentsight.sdk import exporter

    parsed = []
    real = exporter._as_object

    def counting(value):
        parsed.append(value)
        return real(value)

    monkeypatch.setattr(exporter, "_as_object", counting)

    with ags.conversation("c-parse-once", metadata={"tier": "gold"}):
        for _ in range(10):
            with ags.turn():
                ags.user_message("hi")

    assert blocks(spans)["c-parse-once"]["metadata"] == {"tier": "gold"}
    assert len(parsed) == 1


def test_a_mid_conversation_metadata_change_still_updates_the_block(
    spans, monkeypatch
):
    """The path the parse memo could break. Later spans win — a scope that
    supplies different metadata mid-conversation must still update the block —
    and clearing to `{}` is a real instruction that must still travel, not be
    skipped by a truthiness test. A changed document is a changed string, so
    each distinct document parses exactly once, whatever the span count."""
    from agentsight.sdk import exporter

    parsed = []
    real = exporter._as_object

    def counting(value):
        parsed.append(value)
        return real(value)

    monkeypatch.setattr(exporter, "_as_object", counting)

    with ags.conversation("c-meta-change", metadata={"plan": "trial"}):
        with ags.turn():
            ags.user_message("hi")
        ags.update_metadata({"plan": "enterprise", "escalated": True})
        with ags.turn():
            ags.user_message("hello again")
        ags.update_metadata(remove=["plan", "escalated"])

    assert blocks(spans)["c-meta-change"]["metadata"] == {}
    assert len(parsed) == 3


def test_cutting_values_is_preferred_to_dropping_keys(spans):
    """Forty 4 KB values fit once each is cut, so nothing is lost but length.
    Shedding a key is the last resort, not the first."""
    metadata = {"k%03d" % i: "x" * 4_000 for i in range(40)}

    with ags.conversation("c-meta-many", metadata=metadata):
        with ags.turn():
            ags.user_message("hi")

    stored = blocks(spans)["c-meta-many"]["metadata"]
    assert serialization.TRUNCATION_KEY not in stored
    assert len(stored) == 40


def test_truncation_says_so_when_it_has_to_drop_whole_keys(spans):
    """Three thousand short keys cannot be saved by cutting values — there is
    no value to cut. Keys go, and the document records which."""
    metadata = {"key-%04d" % i: i for i in range(3_000)}

    with ags.conversation("c-meta-wide", metadata=metadata):
        with ags.turn():
            ags.user_message("hi")

    stored = blocks(spans)["c-meta-wide"]["metadata"]
    assert serialization.TRUNCATION_KEY in stored
    assert stored[serialization.TRUNCATION_KEY]["dropped_keys"]
    # What survived is real data, not a stub.
    assert len(stored) > 100


@pytest.mark.parametrize(
    "value",
    [
        {"a": "x" * 40_000},
        ["x" * 40_000 for _ in range(10)],
        {"nested": {"deep": {"deeper": "x" * 40_000}}},
        "x" * 40_000,
        {"mixed": ["x" * 20_000, {"and": "x" * 20_000}]},
    ],
    ids=["one-big-value", "big-list", "nested", "bare-string", "mixed"],
)
def test_to_json_always_returns_something_that_parses(value):
    document = serialization.to_json(value)
    assert len(document) <= serialization.MAX_ATTRIBUTE_LENGTH
    json.loads(document)  # the whole point: it must not raise


def test_small_metadata_is_untouched():
    """No behaviour change for the 99.9% case — same bytes as a plain dumps."""
    value = {"order_id": "A-1", "items": [1, 2, 3], "nested": {"ok": True}}
    assert serialization.to_json(value) == json.dumps(value, ensure_ascii=False)


# ---------------------------------------------------------------------------
# The conversation decorator
# ---------------------------------------------------------------------------


def test_the_decorator_gives_every_call_its_own_conversation(spans):
    """The id used to be resolved at *decoration* time and reused forever, so
    every user who ever hit a decorated handler landed in one conversation
    for the life of the process."""

    @ags.conversation()
    def handle(text):
        with ags.turn():
            ags.user_message(text)

    for text in ("a", "b", "c"):
        handle(text)

    assert len(blocks(spans)) == 3


def test_the_async_decorator_gives_every_call_its_own_conversation(spans):
    @ags.conversation()
    async def handle(text):
        with ags.turn():
            ags.user_message(text)

    async def drive():
        for text in ("a", "b", "c"):
            await handle(text)

    asyncio.run(drive())
    assert len(blocks(spans)) == 3


def test_an_explicit_id_still_pins_every_call_to_one_conversation(spans):
    """The other half of the contract: naming the conversation means naming
    it, however many times the handler runs."""

    @ags.conversation("wa-3859")
    def handle(text):
        with ags.turn():
            ags.user_message(text)

    handle("a")
    handle("b")

    assert list(blocks(spans)) == ["wa-3859"]


def test_the_decorator_carries_the_metadata_it_was_configured_with(spans):
    @ags.conversation(device="mobile", source="web", metadata={"tier": "gold"})
    def handle():
        with ags.turn():
            ags.user_message("hi")

    handle()
    handle()

    for block in blocks(spans).values():
        assert block["device"] == "mobile"
        assert block["source"] == "web"
        assert block["metadata"] == {"tier": "gold"}


def test_the_decorator_picks_up_an_environment_set_after_decoration(spans, monkeypatch):
    """Decoration happens at import; init() runs in main. A template built at
    decoration time had no environment on it at all, so every decorated
    conversation silently lost the deployment-wide default."""

    @ags.conversation()
    def handle():
        with ags.turn():
            ags.user_message("hi")

    monkeypatch.setattr(core._state, "environment", "production")
    handle()

    (block,) = blocks(spans).values()
    assert block["environment"] == "production"


# ---------------------------------------------------------------------------
# turn(...) bound to a name
# ---------------------------------------------------------------------------


def test_a_turn_factory_can_be_reused_and_nested(spans):
    """Every documented call shape builds a fresh factory, so this only bites
    someone who binds one to a name first — at which point the second `with`
    overwrote the first scope and left its turn open forever."""
    ask = ags.turn("ask")

    with ags.conversation("c-reuse"):
        with ask:
            ags.user_message("one")
        with ask:
            ags.user_message("two")
        with ask:
            with ask:
                ags.user_message("nested")

    turns = [
        s for s in spans.get_finished_spans()
        if (s.attributes or {}).get("agentsight.span.kind") == "turn"
    ]
    assert len(turns) == 4
    assert all(t.end_time is not None for t in turns)


def test_exiting_a_turn_factory_that_never_entered_does_not_raise():
    """Tracking must never raise into user code, least of all out of a
    `with` statement's own teardown."""
    assert ags.turn("ask").__exit__(None, None, None) is False
