"""Tests for the `agentsight-migration` skill's shipped validator.

The cardinal rule under test is not "it catches bad files" — it is **it never
rejects a file the server would have accepted**. A validator stricter than the
server makes the user drop real rows, which is worse than having no validator
at all. So the interesting half of this suite is `TestFalseRejections`, and the
authority for everything is `TestAgreement`, which replays a corpus generated
by the backend's own `validate_chunk` (see `regenerate_corpus.py`).

Everything runs offline, as the validator itself does: it reads the skill's
shipped `contract/` directory and never touches the network.
"""

import importlib.util
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "skills" / "agentsight-migration" / "scripts" / "validate_import.py"
CONTRACT_DIR = ROOT / "skills" / "agentsight-migration" / "contract"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "import_contract"
REGENERATE = Path(__file__).resolve().parent / "regenerate_corpus.py"
BASE = "2016-06-01T10:00:00Z"

# The contract digest the golden corpus was last regenerated against. When it
# stops matching the shipped snapshot, the contract moved: re-run
# regenerate_corpus.py from an ags_backend checkout and paste the digest it
# prints here, in the same commit as the refreshed snapshot and corpus.
CORPUS_CONTRACT_SHA256 = "701b2baa28afca351de36a6b8a17ed8d3b0caa27dd9ddf3bdab9a75d55f49755"


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


vi = _load("validate_import", SCRIPT)
rc = _load("regenerate_corpus", REGENERATE)
SCHEMA, LIMITS, MANIFEST = vi.load_contract(CONTRACT_DIR)


@pytest.fixture(scope="module")
def ctx():
    return {
        "validator": vi.build_validator(SCHEMA),
        "limits": dict(LIMITS),
        "latest": datetime.now(timezone.utc) + vi.FUTURE_TOLERANCE + vi.UPLOAD_GRACE,
    }


def check(conversations, ctx, seen=None):
    """Run one chunk of conversations; return [(index, code, field), ...]."""
    findings, warnings = [], []
    vi.validate_file(
        "f.json",
        {"schema_version": 1, "conversations": conversations},
        0,
        ctx,
        findings,
        warnings,
        {} if seen is None else seen,
    )
    return [(f.index, f.code, f.field) for f in findings]


def codes(conversations, ctx):
    return [code for _, code, _ in check(conversations, ctx)]


def conversation(cid="c1", **overrides):
    record = {
        "conversation_id": cid,
        "started_at": BASE,
        "messages": [message()],
    }
    record.update(overrides)
    return record


def message(sender="user", content="hello", timestamp=BASE, **extra):
    record = {"sender": sender, "content": content, "timestamp": timestamp}
    record.update(extra)
    return record


def nest_objects(depth):
    node = {"leaf": 1}
    for _ in range(depth - 1):
        node = {"n": node}
    return node


def sized_metadata(target):
    overhead = len(json.dumps({"a": ""}, separators=(",", ":"), ensure_ascii=False))
    return {"a": "x" * (target - overhead)}


# ---------------------------------------------------------------------------
# Agreement with the server
# ---------------------------------------------------------------------------

# The one place the validator deliberately reports a different NAME for the
# same rejection. `refinePattern` (pre-validate.ts:235-239) turns an
# all-whitespace value into `too_short` / "This value is empty."; the server
# reports the raw `pattern` failure as `invalid_format`. Both reject the
# record, the dashboard already shows the refined code for exactly this input,
# and "this value is empty" is the more actionable message for someone fixing
# an exporter. It is recorded here rather than smoothed over so that a NEW
# divergence cannot hide behind it.
EQUIVALENT_CODES = {("too_short", "invalid_format")}


class TestAgreement:
    """The same hostile fixture through this script and through validate_chunk."""

    corpus = json.loads((FIXTURES / "validator_corpus.json").read_text(encoding="utf-8"))
    expected = json.loads((FIXTURES / "validator_expected.json").read_text(encoding="utf-8"))

    @pytest.mark.parametrize("case", corpus, ids=lambda c: c["name"])
    def test_case_matches_the_server(self, case, ctx):
        got = check(case["conversations"], ctx)
        want = [tuple(entry) for entry in self.expected[case["name"]]]
        assert len(got) == len(want), f"{got!r} != {want!r}"
        for (gi, gc, gf), (wi, wc, wf) in zip(got, want):
            assert (gi, gf) == (wi, wf)
            if gc != wc:
                assert (gc, wc) in EQUIVALENT_CODES, f"undocumented divergence {gc} != {wc}"

    def test_the_corpus_covers_every_hand_written_rule(self):
        """A rule with no corpus case is a rule with no agreement guard."""
        seen = {entry[1] for case in self.expected.values() for entry in case}
        for code in (
            "nul_byte",
            "invalid_number",
            "metadata_too_deep",
            "metadata_too_large",
            "too_many_metadata_keys",
            "metadata_key_too_long",
            "forbidden_metadata_key",
            "unknown_sender",
            "missing_offset",
            "invalid_timestamp",
            "timestamp_out_of_range",
            "before_started_at",
            "duplicate_conversation_id",
        ):
            assert code in seen, f"{code} has no corpus case"

    def test_the_shipped_example_is_clean(self, ctx):
        """If the canonical example fails this validator, the validator is wrong."""
        example = json.loads((CONTRACT_DIR / "example_import.json").read_text(encoding="utf-8"))
        assert check(example["conversations"], ctx) == []


# ---------------------------------------------------------------------------
# False rejections — the half that matters
# ---------------------------------------------------------------------------


class TestFalseRejections:
    def test_metadata_pretty_over_but_compact_under_the_cap(self, ctx):
        """Guards `separators=(",", ":")`. Pretty-printing must not count."""
        metadata = {"trace": [f"value_{i:04d}" for i in range(1100)]}
        cap = LIMITS["max_metadata_bytes"]
        assert len(json.dumps(metadata, indent=4).encode()) > cap
        assert len(json.dumps(metadata, separators=(",", ":")).encode()) <= cap
        assert codes([conversation(metadata=metadata)], ctx) == []

    def test_non_ascii_metadata_is_measured_with_ensure_ascii_false(self, ctx):
        """Guards `ensure_ascii=False`. \\uXXXX escaping would inflate this 6x."""
        metadata = {"note": "こんにちは" * 900}
        cap = LIMITS["max_metadata_bytes"]
        assert len(json.dumps(metadata, separators=(",", ":")).encode()) > cap
        assert codes([conversation(metadata=metadata)], ctx) == []

    def test_metadata_exactly_at_the_byte_cap(self, ctx):
        cap = LIMITS["max_metadata_bytes"]
        assert codes([conversation(metadata=sized_metadata(cap))], ctx) == []
        assert codes([conversation(metadata=sized_metadata(cap + 1))], ctx) == [
            "metadata_too_large"
        ]

    def test_eleven_nested_arrays_are_legal(self, ctx):
        """Arrays are NOT nesting levels. This is where a rewrite goes wrong."""
        value = "deep"
        for _ in range(11):
            value = [value]
        assert codes([conversation(metadata={"a": value})], ctx) == []

    def test_arrays_interleaved_at_every_object_level_are_legal(self, ctx):
        node = {"leaf": 1}
        for _ in range(9):
            node = {"n": [node]}
        assert codes([conversation(metadata=node)], ctx) == []

    def test_object_depth_boundary(self, ctx):
        assert codes([conversation(metadata=nest_objects(10))], ctx) == []
        assert codes([conversation(metadata=nest_objects(11))], ctx) == ["metadata_too_deep"]

    def test_the_depth_walker_reports_once_and_stops(self, ctx):
        """A 15-deep object is one finding, not five."""
        assert codes([conversation(metadata=nest_objects(15))], ctx) == ["metadata_too_deep"]

    def test_timestamp_equal_to_started_at_is_legal(self, ctx):
        assert codes([conversation(messages=[message(timestamp=BASE)])], ctx) == []

    def test_one_microsecond_before_started_at_is_not(self, ctx):
        record = conversation(
            started_at="2016-06-01T10:00:00Z",
            messages=[message(timestamp="2016-06-01T09:59:59.999999Z")],
        )
        assert codes([record], ctx) == ["before_started_at"]

    def test_the_comparison_is_of_instants_not_wall_clocks(self, ctx):
        record = conversation(
            started_at="2016-06-01T10:00:00Z",
            messages=[message(timestamp="2016-06-01T12:00:00+02:00")],
        )
        assert codes([record], ctx) == []

    def test_an_unparseable_started_at_skips_the_ordering_check(self, ctx):
        record = conversation(
            started_at="whenever", messages=[message(timestamp="2016-01-01T00:00:00Z")]
        )
        assert codes([record], ctx) == ["invalid_timestamp"]

    @pytest.mark.parametrize(
        "sender", ["user", "User", "  ASSISTANT  ", "BOT", "\tai\n", "End_User", "customer"]
    )
    def test_sender_aliases_are_case_and_whitespace_insensitive(self, sender, ctx):
        assert codes([conversation(messages=[message(sender=sender)])], ctx) == []

    @pytest.mark.parametrize(
        "value",
        [
            "2016-1-2T3:4Z",
            "2016-01-02 03:04:05Z",
            "2016-01-02T03:04:05.5+01",
            "2016-01-02T03:04:05+0100",
            "2016-01-02T03:04:05 +01:00",
            "2016-01-02T03:04:05.123456-05:30",
            "2016-01-02T03:04-08",
            "2016-12-31T23:59:59.000001+14:00",
            "2000-01-01T00:00:00Z",
        ],
    )
    def test_every_shape_the_contract_admits_parses(self, value, ctx):
        """The formal 'not stricter than the server' statement.

        Each of these matches the schema's `#/$defs/timestamp` pattern, so the
        server parses it. `datetime.fromisoformat` on 3.9 would reject most of
        them, which is why the parser is a port of Django's regex instead.
        """
        assert vi.parse_datetime(value) is not None
        record = conversation(started_at="2000-01-01T00:00:00Z",
                              messages=[message(timestamp=value)])
        assert codes([record], ctx) == []

    def test_the_pattern_space_is_closed(self):
        """Every string the schema's timestamp pattern admits must parse."""
        import re

        pattern = re.compile(SCHEMA["$defs"]["timestamp"]["pattern"])
        built = 0
        for sep in ("T", " "):
            for date in ("2016-06-01", "2016-6-1"):
                for clock in ("10:00", "1:2"):
                    for seconds in ("", ":05", ":05.1", ":05.123456"):
                        for gap in ("", " ", "  "):
                            for offset in ("Z", "+02:00", "-0530", "+02"):
                                value = f"{date}{sep}{clock}{seconds}{gap}{offset}"
                                if not pattern.match(value):
                                    continue
                                built += 1
                                assert vi.parse_datetime(value) is not None, value
        assert built > 200

    def test_boundary_lengths_are_legal(self, ctx):
        assert codes([conversation("x" * 255)], ctx) == []
        assert codes([conversation("x" * 256)], ctx) == ["too_long"]
        assert codes([conversation(messages=[message(content="c" * 100_000)])], ctx) == []
        assert codes([conversation(messages=[message(content="c" * 100_001)])], ctx) == [
            "too_long"
        ]
        assert codes([conversation(messages=[message()] * 2000)], ctx) == []
        assert codes([conversation(messages=[message()] * 2001)], ctx) == ["too_many_items"]

    def test_metadata_key_boundaries(self, ctx):
        assert codes([conversation(metadata={str(i): i for i in range(50)})], ctx) == []
        assert codes([conversation(metadata={str(i): i for i in range(51)})], ctx) == [
            "too_many_metadata_keys"
        ]
        assert codes([conversation(metadata={"k" * 200: 1})], ctx) == []
        assert codes([conversation(metadata={"k" * 201: 1})], ctx) == ["metadata_key_too_long"]

    def test_optional_fields_may_be_null_or_absent(self, ctx):
        record = conversation(name=None, customer_id=None, language=None, device=None,
                              metadata=None)
        assert codes([record], ctx) == []
        assert codes([conversation()], ctx) == []


# ---------------------------------------------------------------------------
# Per-rule units
# ---------------------------------------------------------------------------


class TestValueRules:
    @pytest.mark.parametrize(
        "field", ["conversation_id", "name", "customer_id", "language", "device"]
    )
    def test_nul_in_every_conversation_text_field(self, field, ctx):
        assert check([conversation(**{field: "a\x00b"})], ctx)[0][1:] == ("nul_byte", field)

    def test_nul_in_message_content_and_metadata(self, ctx):
        record = conversation(
            metadata={"ke\x00y": "ok", "v": "ba\x00d", "list": ["ba\x00d"]},
            messages=[message(content="he\x00llo")],
        )
        found = check([record], ctx)
        assert [c for _, c, _ in found] == ["nul_byte"] * 4
        assert [f for _, _, f in found] == [
            "metadata.ke\x00y",
            "metadata.v",
            "metadata.list[0]",
            "messages[0].content",
        ]

    def test_a_nul_sender_is_never_reported_as_an_unknown_sender(self, ctx):
        record = conversation(messages=[message(sender="us\x00er")])
        assert codes([record], ctx) == ["nul_byte"]

    @pytest.mark.parametrize("sender", ["system", "tool", "function", "user2"])
    def test_unimportable_senders(self, sender, ctx):
        found = check([conversation(messages=[message(sender=sender)])], ctx)
        assert found == [(0, "unknown_sender", "messages[0].sender")]

    @pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
    def test_non_finite_numbers_in_metadata(self, value, ctx):
        assert codes([conversation(metadata={"a": value})], ctx) == ["invalid_number"]

    def test_reserved_metadata_keys(self, ctx):
        record = conversation(metadata={"__proto__": 1, "constructor": 2, "prototype": 3})
        assert codes([record], ctx) == ["forbidden_metadata_key"] * 3

    def test_missing_offset_versus_invalid_timestamp(self, ctx):
        naive = conversation(started_at="2016-06-01T10:00:00", messages=[message()])
        assert codes([naive], ctx)[0] == "missing_offset"
        bad = conversation(started_at="2016-02-30T00:00:00Z", messages=[message()])
        assert codes([bad], ctx)[0] == "invalid_timestamp"

    def test_an_impossible_offset_does_not_crash(self, ctx):
        assert vi.parse_datetime("2016-06-01T10:00:00+99:99") is None

    def test_plausibility_window(self, ctx):
        old = conversation(started_at="1999-12-31T23:59:59Z",
                           messages=[message(timestamp="1999-12-31T23:59:59Z")])
        assert set(codes([old], ctx)) == {"timestamp_out_of_range"}
        future = conversation(started_at="2999-01-01T00:00:00Z",
                              messages=[message(timestamp="2999-01-01T00:00:00Z")])
        assert set(codes([future], ctx)) == {"timestamp_out_of_range"}


class TestSchemaRules:
    def test_an_unknown_field_names_the_offending_key(self, ctx):
        record = conversation()
        record["converstaion_id"] = "typo"
        assert check([record], ctx) == [(0, "unknown_field", "converstaion_id")]

    def test_a_missing_field_names_the_field(self, ctx):
        assert check([{"conversation_id": "c", "started_at": BASE}], ctx) == [
            (0, "missing_field", "messages")
        ]

    def test_metadata_as_a_list_is_a_wrong_type_not_a_schema_violation(self, ctx):
        assert codes([conversation(metadata=[])], ctx) == ["wrong_type"]

    def test_a_non_object_conversation(self, ctx):
        assert check(["nope"], ctx) == [(0, "not_an_object", None)]

    def test_the_value_pass_short_circuits_the_schema_pass(self, ctx):
        """Mirrors validation.py:783-786 — one record, one pass."""
        record = conversation(messages=[message(sender="system")])
        record["converstaion_id"] = "typo"
        assert codes([record], ctx) == ["unknown_sender"]

    def test_the_short_circuit_is_per_record_not_per_file(self, ctx):
        typo = conversation("a")
        typo["converstaion_id"] = "typo"
        bad_sender = conversation("b", messages=[message(sender="system")])
        assert codes([typo, bad_sender], ctx) == ["unknown_field", "unknown_sender"]

    def test_the_sender_pattern_is_never_tightened_into_an_enum(self):
        sender = SCHEMA["$defs"]["message"]["properties"]["sender"]
        assert "enum" not in sender and "pattern" in sender


class TestDuplicates:
    def test_only_the_second_and_later_occurrences_are_flagged(self, ctx):
        found = check([conversation("d"), conversation("d"), conversation("d")], ctx)
        assert [(i, c) for i, c, _ in found] == [
            (1, "duplicate_conversation_id"),
            (2, "duplicate_conversation_id"),
        ]

    def test_duplicates_are_detected_across_part_files(self, ctx):
        seen = {}
        assert check([conversation("shared")], ctx, seen) == []
        found = check([conversation("shared")], ctx, seen)
        assert found[0][1] == "duplicate_conversation_id"

    def test_a_nul_bearing_id_is_excluded_from_the_dedupe_map(self, ctx):
        """The server drops these before querying; a NUL id is already rejected."""
        found = check([conversation("a\x00b"), conversation("a\x00b")], ctx)
        assert [c for _, c, _ in found] == ["nul_byte", "nul_byte"]


# ---------------------------------------------------------------------------
# Envelope, decoding and the CLI
# ---------------------------------------------------------------------------


def write(tmp_path, payload, name="part.json"):
    path = tmp_path / name
    if isinstance(payload, (bytes, bytearray)):
        path.write_bytes(payload)
    else:
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return str(path)


def run_cli(argv):
    """The default path: no flags, the shipped snapshot."""
    return vi.main(argv)


class TestEnvelope:
    def test_a_clean_file_exits_zero(self, tmp_path, capsys):
        path = write(tmp_path, {"schema_version": 1, "conversations": [conversation()]})
        assert run_cli([path]) == 0
        assert "PASSED" in capsys.readouterr().out

    @pytest.mark.parametrize("version", ["1", 2, None, True])
    def test_the_schema_version_gate_is_strict_about_type(self, version, tmp_path, capsys):
        payload = {"conversations": [conversation()]}
        if version is not None:
            payload["schema_version"] = version
        path = write(tmp_path, payload)
        assert run_cli([path]) == 1
        assert "wrong_value" in capsys.readouterr().out

    @pytest.mark.parametrize(
        "conversations,code",
        [(None, "missing_field"), ({}, "wrong_type"), ([], "too_few_items")],
    )
    def test_the_conversations_key(self, conversations, code, tmp_path, capsys):
        payload = {"schema_version": 1}
        if conversations is not None:
            payload["conversations"] = conversations
        path = write(tmp_path, payload)
        assert run_cli([path]) == 1
        assert code in capsys.readouterr().out

    def test_unknown_top_level_keys_warn_but_do_not_fail(self, tmp_path, capsys):
        path = write(
            tmp_path,
            {"schema_version": 1, "conversations": [conversation()], "exported_at": "x"},
        )
        assert run_cli([path]) == 0
        out = capsys.readouterr().out
        assert "WARNINGS" in out and "exported_at" in out

    def test_a_bom_is_tolerated(self, tmp_path, capsys):
        body = json.dumps({"schema_version": 1, "conversations": [conversation()]})
        path = write(tmp_path, b"\xef\xbb\xbf" + body.encode("utf-8"))
        assert run_cli([path]) == 0

    def test_malformed_json_is_a_finding_not_a_crash(self, tmp_path, capsys):
        path = write(tmp_path, b"{not json")
        assert run_cli([path]) == 1
        assert "invalid_json" in capsys.readouterr().out

    def test_a_missing_file_is_a_usage_error(self, tmp_path):
        assert run_cli([str(tmp_path / "nope.json")]) == 2


class TestCli:
    def test_bare_invocation_validates_against_the_shipped_snapshot(self, tmp_path, capsys):
        path = write(tmp_path, {"schema_version": 1, "conversations": [conversation()]})
        assert vi.main([path]) == 0
        assert "shipped snapshot" in capsys.readouterr().out

    def test_contract_flag_reads_another_directory(self, tmp_path, capsys):
        copy = tmp_path / "contract"
        shutil.copytree(CONTRACT_DIR, copy)
        path = write(tmp_path, {"schema_version": 1, "conversations": [conversation()]})
        assert vi.main(["--contract", str(copy), path]) == 0
        assert "PASSED" in capsys.readouterr().out

    def test_an_unreadable_snapshot_is_no_verdict(self, tmp_path, capsys):
        empty = tmp_path / "empty"
        empty.mkdir()
        path = write(tmp_path, {"schema_version": 1, "conversations": [conversation()]})
        assert vi.main(["--contract", str(empty), path]) == 3
        err = capsys.readouterr().err
        assert "Nothing was validated" in err and "reinstall" in err

    def test_a_partial_snapshot_names_the_missing_cap(self, tmp_path, capsys):
        copy = tmp_path / "contract"
        shutil.copytree(CONTRACT_DIR, copy)
        limits = json.loads((copy / "limits.json").read_text(encoding="utf-8"))
        del limits["max_metadata_bytes"]
        (copy / "limits.json").write_text(json.dumps(limits), encoding="utf-8")
        path = write(tmp_path, {"schema_version": 1, "conversations": [conversation()]})
        assert vi.main(["--contract", str(copy), path]) == 3
        assert "max_metadata_bytes" in capsys.readouterr().err

    def test_missing_jsonschema_is_no_verdict(self, tmp_path, monkeypatch, capsys):
        path = write(tmp_path, {"schema_version": 1, "conversations": [conversation()]})
        monkeypatch.setattr(vi, "Draft202012Validator", None)
        assert run_cli([path]) == 3
        assert "pip install" in capsys.readouterr().err

    def test_the_report_never_prints_a_whole_message_body(self, tmp_path, capsys):
        path = write(
            tmp_path,
            {
                "schema_version": 1,
                "conversations": [conversation(messages=[message(content="c" * 100_001)])],
            },
        )
        assert run_cli([path]) == 1
        out = capsys.readouterr().out
        assert "too_long" in out
        # jsonschema's maxLength message embeds the whole instance. Truncating
        # it is what keeps a 100 000-character message out of the agent's
        # context window.
        assert "c" * 200 not in out

    def test_findings_are_capped_per_code(self, tmp_path, capsys):
        record = conversation(messages=[message(sender="system") for _ in range(30)])
        path = write(tmp_path, {"schema_version": 1, "conversations": [record]})
        assert run_cli(["--max-examples", "3", path]) == 1
        out = capsys.readouterr().out
        assert "27 more not shown" in out

    def test_the_report_always_names_what_it_cannot_check(self, tmp_path, capsys):
        path = write(tmp_path, {"schema_version": 1, "conversations": [conversation()]})
        run_cli([path])
        assert "conversation_already_exists" in capsys.readouterr().out

    def test_the_banner_names_the_snapshot_commit_and_version(self, tmp_path, capsys):
        path = write(tmp_path, {"schema_version": 1, "conversations": [conversation()]})
        run_cli([path])
        out = capsys.readouterr().out
        assert MANIFEST["commit"][:12] in out
        assert f"schema_version {LIMITS['schema_version']}" in out

    def test_a_conversation_past_the_chunk_budget_warns(self, tmp_path, capsys):
        """`max_chunk_request_bytes` is a warning, never a finding: the dashboard
        cannot pack such a conversation, but the server would accept it."""
        count = LIMITS["max_chunk_request_bytes"] // 100_000 + 2
        record = conversation(messages=[message(content="c" * 100_000) for _ in range(count)])
        path = write(tmp_path, {"schema_version": 1, "conversations": [record]})
        assert run_cli([path]) == 0
        out = capsys.readouterr().out
        assert "WARNINGS" in out and "chunk budget" in out

    def test_the_script_imports_no_network_module(self):
        """The skill's promise, stated as a test: the validator never goes online."""
        import re

        source = SCRIPT.read_text(encoding="utf-8")
        imported = re.findall(r"^\s*(?:import|from)\s+([\w.]+)", source, re.MULTILINE)
        for module in imported:
            assert not module.startswith(("urllib", "http", "socket", "requests")), module
        for needle in ("AGENTSIGHT_API", "api.agentsight.io"):
            assert needle not in source, needle


# ---------------------------------------------------------------------------
# The shipped snapshot
# ---------------------------------------------------------------------------


class TestSnapshot:
    """`contract/` is the only contract the validator ever reads."""

    # The eleven keys `limits_payload()` publishes -- the same literal set
    # data_imports/tests/test_limits_drift.py::LimitsPayloadKeyTests pins.
    LIMIT_KEYS = {
        "schema_version",
        "max_conversations_per_run",
        "max_conversations_per_chunk",
        "max_chunks_per_run",
        "max_chunk_request_bytes",
        "max_messages_per_conversation",
        "max_content_length",
        "max_metadata_bytes",
        "max_metadata_depth",
        "max_open_runs_per_agent",
        "max_import_file_bytes",
    }

    raw_limits = json.loads((CONTRACT_DIR / "limits.json").read_text(encoding="utf-8"))

    def test_limits_json_publishes_exactly_the_served_keys(self):
        assert set(self.raw_limits) == self.LIMIT_KEYS
        for key, value in self.raw_limits.items():
            assert isinstance(value, int) and not isinstance(value, bool) and value > 0, key

    def test_the_limits_agree_with_the_schema(self):
        assert LIMITS["schema_version"] == SCHEMA["properties"]["schema_version"]["const"]
        assert (
            LIMITS["max_conversations_per_run"]
            == SCHEMA["properties"]["conversations"]["maxItems"]
        )
        metadata_object = SCHEMA["$defs"]["metadataObject"]
        assert LIMITS["max_metadata_keys_per_level"] == metadata_object["maxProperties"]
        assert LIMITS["max_metadata_key_length"] == metadata_object["propertyNames"]["maxLength"]

    def test_the_example_validates_at_the_file_root(self):
        from jsonschema import Draft202012Validator

        example = json.loads((CONTRACT_DIR / "example_import.json").read_text(encoding="utf-8"))
        assert list(Draft202012Validator(SCHEMA).iter_errors(example)) == []

    def test_the_manifest_names_its_origin(self):
        assert set(MANIFEST) >= {"source", "commit", "exported_at", "contract_sha256"}
        assert MANIFEST["source"] == "ags_backend"

    def test_the_snapshot_digest_matches_the_corpus_pin(self):
        """If this fails, the contract moved: re-run regenerate_corpus.py from an
        ags_backend checkout and update CORPUS_CONTRACT_SHA256."""
        digest = rc.contract_digest(
            (CONTRACT_DIR / "import_v1.schema.json").read_bytes(),
            (CONTRACT_DIR / "example_import.json").read_bytes(),
            self.raw_limits,
        )
        assert digest == MANIFEST["contract_sha256"], "MANIFEST.json does not describe these files"
        assert digest == CORPUS_CONTRACT_SHA256, (
            "the snapshot moved: re-run tests/skills/regenerate_corpus.py from an "
            "ags_backend checkout and update CORPUS_CONTRACT_SHA256"
        )
