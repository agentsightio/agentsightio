#!/usr/bin/env python3
"""Refresh the shipped contract snapshot and the golden agreement corpus.

Two checked-in artifacts derive from the backend and go stale the moment its
import contract moves. This script rewrites both from one `ags_backend`
checkout, so they can only ever move together.

    skills/agentsight-migration/contract/          what the SERVER publishes
        import_v1.schema.json                      copied byte-for-byte
        example_import.json                        copied byte-for-byte
        limits.json                                limits_payload() -- no file in the backend
        MANIFEST.json                              backend commit, export time, digest

    fixtures/import_contract/validator_corpus.json     the hostile inputs
    fixtures/import_contract/validator_expected.json   what the SERVER says

The snapshot is the only contract `validate_import.py` reads -- the migration
skill makes no network request -- so a stale copy is a file the validator
accepts and the server rejects, or the reverse. The corpus guards the
validator's hand-written half: it is a third implementation of rules that
already exist twice (the backend's `data_imports/validation.py`, the
dashboard's `lib/imports/pre-validate.ts`), and nothing at runtime reads two
of them, so the only symptom of drift is a file this script accepts and the
server rejects -- or, far worse, one it rejects and the server would have
taken, which costs the user real rows.

This is the guard, in the shape of `data_imports/tests/test_contract_drift.py`:
checked-in artifacts asserted against the code that produced them.
`test_validate_import.py::TestAgreement` replays the corpus and asserts the
same (index, code, field) triples; `TestSnapshot` pins the snapshot's digest.

HOW TO RUN IT -- from an `ags_backend` checkout, with its virtualenv active:

    DJANGO_SETTINGS_MODULE=AgentSight.settings \
    PYTHONPATH=/path/to/ags_backend \
    python3 /path/to/agentsight/tests/skills/regenerate_corpus.py

It prints the new contract digest; paste it into CORPUS_CONTRACT_SHA256 in
test_validate_import.py and commit everything in one change.

**No database is touched.** `validate_chunk`'s only queries are the two `IN`
lookups in `_duplicate_errors`, and both model managers are stubbed out below,
so the in-chunk duplicate logic still runs while the server-only halves
(`conversation_already_exists`, cross-chunk staging) return empty -- which is
exactly the subset a standalone validator can reproduce.

WHAT IS DELIBERATELY NOT IN THE CORPUS: cases whose only rule is a JSON Schema
keyword on a large value (a 100 000-character `content`, a 2 001-message
conversation). Both implementations compile the *same served schema*, so those
cannot diverge by construction, and carrying them would put 100 KB of filler in
the repo. They are covered as ordinary unit tests instead. What is here is the
hand-written half -- the rules JSON Schema cannot express -- which is where
divergence is actually possible.

Also not here: anything time-dependent. `validate_chunk` computes its future
ceiling as `now() + 5min`, so every timestamp below sits in 2016.
"""

import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "import_contract"
CONTRACT_DIR = Path(__file__).resolve().parents[2] / "skills" / "agentsight-migration" / "contract"
BASE = "2016-06-01T10:00:00Z"


def _conversation(cid, **overrides):
    conversation = {
        "conversation_id": cid,
        "started_at": BASE,
        "messages": [{"sender": "user", "content": "hello", "timestamp": BASE}],
    }
    conversation.update(overrides)
    return conversation


def _message(sender="user", content="hello", timestamp=BASE, **extra):
    message = {"sender": sender, "content": content, "timestamp": timestamp}
    message.update(extra)
    return message


def _nest_objects(depth):
    """`depth` object levels, counting the metadata object itself as one."""
    node = {"leaf": 1}
    for _ in range(depth - 1):
        node = {"n": node}
    return node


def _sized_metadata(target):
    """A metadata object whose COMPACT utf-8 serialization is exactly `target`."""
    metadata = {"a": ""}
    overhead = len(json.dumps(metadata, separators=(",", ":"), ensure_ascii=False))
    return {"a": "x" * (target - overhead)}


def build_corpus():
    cases = []

    def case(name, conversations):
        cases.append({"name": name, "conversations": conversations})

    # ---- legal: must produce nothing ------------------------------------
    case("clean", [_conversation("clean-1")])
    case(
        "sender_aliases",
        [
            _conversation(
                "aliases",
                messages=[
                    _message(sender=alias)
                    for alias in ("user", "HUMAN", "  Customer  ", "end_user")
                ]
                + [_message(sender=alias) for alias in ("assistant", "BOT", "\tai\n", "Agent")],
            )
        ],
    )
    case(
        "metadata_arrays_11_deep",
        # Arrays are NOT nesting levels. This case must stay clean; an
        # implementation that counts them rejects legal files.
        [_conversation("arrays", metadata={"a": [[[[[[[[[[["deep"]]]]]]]]]]]})],
    )
    case("metadata_objects_10_deep", [_conversation("obj10", metadata=_nest_objects(10))])
    case("metadata_size_at_cap", [_conversation("size-ok", metadata=_sized_metadata(16 * 1024))])
    case(
        "metadata_pretty_over_compact_under",
        # json.dumps(indent=2) of this is well past 16 KB; compact is not.
        [_conversation("pretty", metadata={str(i): i for i in range(45)})],
    )
    case(
        "metadata_non_ascii",
        # ensure_ascii=True would inflate these past the cap; ensure_ascii=False
        # is what the server measures with, so this must pass.
        [_conversation("cjk", metadata={"note": "こんにちは" * 900})],
    )
    case("metadata_null", [_conversation("meta-null", metadata=None)])
    case(
        "timestamp_equals_started_at",
        [_conversation("eq", messages=[_message(timestamp=BASE)])],
    )
    case(
        "same_instant_other_offset",
        [
            _conversation(
                "offsets",
                started_at="2016-06-01T10:00:00Z",
                messages=[_message(timestamp="2016-06-01T12:00:00+02:00")],
            )
        ],
    )
    case(
        "timestamp_shapes",
        [
            _conversation(
                "shapes",
                # Deliberately early: this case is about the parser accepting
                # every shape the contract's pattern admits, not about ordering.
                started_at="2016-1-1T0:0Z",
                messages=[
                    _message(timestamp="2016-01-02 03:04:05Z"),
                    _message(timestamp="2016-01-02T03:04:05.5+01"),
                    _message(timestamp="2016-01-02T03:04:05+0100"),
                    _message(timestamp="2016-01-02T03:04:05.123456-05:30"),
                    _message(timestamp="2016-01-02T03:04-08"),
                ],
            )
        ],
    )
    case("earliest_timestamp", [_conversation("early", started_at="2000-01-01T00:00:00Z",
                                              messages=[_message(timestamp="2000-01-01T00:00:00Z")])])

    # ---- metadata rules --------------------------------------------------
    case("metadata_objects_11_deep", [_conversation("obj11", metadata=_nest_objects(11))])
    case("metadata_size_over_cap", [_conversation("size-bad",
                                                  metadata=_sized_metadata(16 * 1024 + 1))])
    case("metadata_keys_51", [_conversation("keys", metadata={str(i): i for i in range(51)})])
    case("metadata_key_too_long", [_conversation("keylen", metadata={"k" * 201: 1})])
    case(
        "metadata_forbidden_keys",
        [_conversation("forbidden", metadata={"__proto__": 1, "constructor": 2, "prototype": 3})],
    )
    case(
        "metadata_non_finite",
        [_conversation("nan", metadata={"a": float("nan"), "b": float("inf"),
                                        "c": float("-inf")})],
    )
    case(
        "metadata_nul",
        [
            _conversation(
                "meta-nul",
                metadata={"ke\x00y": "fine", "value": "ba\x00d", "list": ["ba\x00d"]},
            )
        ],
    )

    # ---- NUL, all five sites --------------------------------------------
    case(
        "nul_text_fields",
        [
            _conversation(
                "id\x00bad",
                name="na\x00me",
                customer_id="cu\x00st",
                language="e\x00n",
                device="io\x00s",
            )
        ],
    )
    case(
        "nul_in_message",
        [_conversation("nul-msg", messages=[_message(content="he\x00llo")])],
    )
    # A NUL-bearing sender must report nul_byte and NEVER unknown_sender.
    case("nul_in_sender", [_conversation("nul-send", messages=[_message(sender="us\x00er")])])

    # ---- senders ---------------------------------------------------------
    case(
        "unknown_senders",
        [
            _conversation(
                "senders",
                messages=[
                    _message(sender="system"),
                    _message(sender="tool"),
                    _message(sender="function"),
                    _message(sender="user2"),
                ],
            )
        ],
    )

    # ---- timestamps ------------------------------------------------------
    case(
        "missing_offset",
        [
            _conversation(
                "naive",
                started_at="2016-06-01T10:00:00",
                messages=[_message(timestamp="2016-06-01T10:00:01")],
            )
        ],
    )
    case(
        "invalid_timestamp",
        [
            _conversation(
                "bad-ts",
                started_at="2016-02-30T00:00:00Z",
                messages=[_message(timestamp="2016-06-01T10:00:00+99:99")],
            )
        ],
    )
    case("out_of_range_past", [_conversation("old", started_at="1999-12-31T23:59:59Z",
                                             messages=[_message(timestamp="1999-12-31T23:59:59Z")])])
    case(
        "before_started_at",
        [
            _conversation(
                "before",
                started_at="2016-06-01T10:00:00Z",
                messages=[_message(timestamp="2016-06-01T09:59:59.999999Z")],
            )
        ],
    )
    case(
        "unparseable_started_at_skips_ordering",
        # started_at did not parse, so before_started_at is not evaluated at all.
        [
            _conversation(
                "skip",
                started_at="not a timestamp",
                messages=[_message(timestamp="2016-06-01T09:00:00Z")],
            )
        ],
    )

    # ---- duplicates and the short-circuit --------------------------------
    case("duplicate_ids", [_conversation("dup"), _conversation("dup"), _conversation("dup")])
    case(
        "short_circuit_same_record",
        # A value-pass failure suppresses the schema pass for THAT record, so
        # the `converstaion_id` typo is not reported here.
        [
            {
                "conversation_id": "sc",
                "converstaion_id": "typo",
                "started_at": BASE,
                "messages": [_message(sender="system")],
            }
        ],
    )
    case(
        "short_circuit_is_per_record",
        [
            {
                "conversation_id": "sc-a",
                "converstaion_id": "typo",
                "started_at": BASE,
                "messages": [_message()],
            },
            _conversation("sc-b", messages=[_message(sender="system")]),
        ],
    )

    # ---- schema pass -----------------------------------------------------
    case(
        "unknown_field",
        [_conversation("extra", **{"nope": 1})],
    )
    case("missing_field", [{"conversation_id": "nomsg", "started_at": BASE}])
    case("metadata_wrong_type", [_conversation("meta-list", metadata=[])])
    case("empty_content", [_conversation("empty", messages=[_message(content="   ")])])
    case("not_an_object", ["a string, not a conversation"])

    return cases


def _stub_managers():
    """Neutralise the two ORM lookups in `_duplicate_errors`. No DB, no writes."""

    class _Empty:
        def filter(self, *args, **kwargs):
            return self

        def values_list(self, *args, **kwargs):
            return ()

    from conversations.models import Conversation
    from data_imports.models import ImportStagedConversation

    Conversation.objects = _Empty()
    ImportStagedConversation.objects = _Empty()


def contract_digest(schema_bytes, example_bytes, limits):
    """sha256 over the three documents: the two files as bytes, limits canonical.

    `test_validate_import.py::TestSnapshot` recomputes this from the shipped
    files and compares it to both MANIFEST.json and its own pinned constant,
    so keep the arithmetic here and there identical.
    """
    canonical = json.dumps(limits, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(schema_bytes + b"\n" + example_bytes + b"\n" + canonical).hexdigest()


def _backend_commit(backend_dir):
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=backend_dir,
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        )
        return result.stdout.strip() or "unknown"
    except Exception:  # not a checkout, or git is missing -- the manifest says so
        return "unknown"


def _write_contract_snapshot():
    """Copy the three contract documents out of the configured backend.

    The schema and the example are files there and are copied byte-for-byte.
    The limits document is not: the server builds it per request from the
    constants in `data_imports/limits.py`, so it is called here and dumped.
    """
    import data_imports
    from data_imports.schema.loader import EXAMPLE_PATH, SCHEMA_PATH
    from data_imports.serializers import limits_payload

    schema_bytes = Path(SCHEMA_PATH).read_bytes()
    example_bytes = Path(EXAMPLE_PATH).read_bytes()
    limits = limits_payload()
    backend_dir = Path(data_imports.__file__).resolve().parent.parent

    manifest = {
        "source": "ags_backend",
        "commit": _backend_commit(backend_dir),
        "exported_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "contract_sha256": contract_digest(schema_bytes, example_bytes, limits),
    }

    CONTRACT_DIR.mkdir(parents=True, exist_ok=True)
    (CONTRACT_DIR / "import_v1.schema.json").write_bytes(schema_bytes)
    (CONTRACT_DIR / "example_import.json").write_bytes(example_bytes)
    (CONTRACT_DIR / "limits.json").write_text(
        json.dumps(limits, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (CONTRACT_DIR / "MANIFEST.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    return manifest


def main():
    corpus = build_corpus()
    FIXTURES.mkdir(parents=True, exist_ok=True)
    (FIXTURES / "validator_corpus.json").write_text(
        json.dumps(corpus, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "AgentSight.settings")
    try:
        import django

        django.setup()
        from data_imports.models import ImportRun
        from data_imports.validation import validate_chunk
    except Exception as exc:
        print(
            f"corpus written; expected NOT regenerated ({exc}).\n"
            f"Run this from an ags_backend checkout -- see the module docstring.",
            file=sys.stderr,
        )
        return 1

    _stub_managers()
    manifest = _write_contract_snapshot()

    # Unsaved, pk pinned: the stubs above mean it is never queried with.
    run = ImportRun(id=0, agent_id=0, staged_conversations=0, declared_conversations=10**6)

    expected = {}
    for entry in corpus:
        _, errors = validate_chunk(run, 0, entry["conversations"])
        expected[entry["name"]] = [
            [error["conversation_index"], str(error["code"]), error["field"]] for error in errors
        ]

    (FIXTURES / "validator_expected.json").write_text(
        json.dumps(expected, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"wrote {len(corpus)} cases to {FIXTURES}")
    print(f"wrote the contract snapshot to {CONTRACT_DIR} (ags_backend@{manifest['commit'][:12]})")
    print(f"contract_sha256 = {manifest['contract_sha256']}")
    print("  -> set CORPUS_CONTRACT_SHA256 in tests/skills/test_validate_import.py to this value")
    return 0


if __name__ == "__main__":
    sys.exit(main())
