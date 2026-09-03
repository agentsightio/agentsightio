#!/usr/bin/env python3
"""Pre-flight check for an AgentSight bulk-import file.

    python3 validate_import.py part-01.json part-02.json ...

This is a PRE-FLIGHT, not a gate. The server (`data_imports/validation.py`) is
the authority and re-validates everything. Nothing here may report a finding
for a record the pipeline would have accepted: where the two can only be made
to agree by being looser, this script is looser. Every rule is a port of one
that exists in the backend's `validation.py` or the dashboard's
`lib/imports/*`; a rule with no home there is a bug in this file.

It makes no network request. The contract it checks against ships with the
skill in `../contract/`: a snapshot of the server's schema, limits and example
taken from an ags_backend checkout by tests/skills/regenerate_corpus.py
(MANIFEST.json names the commit). The server re-validates on upload, so a
contract newer than the snapshot shows up there as a named rejection -- never
as a wrong file here. This script cannot create an import run and cannot
upload: those routes are dashboard-only.

WHAT THIS CANNOT CHECK, ever:

  * conversation_already_exists -- an id already used for the target agent
  * ids held by another open import run (server-side staging)
  * run bookkeeping (declared counts, per-agent open-run cap)
  * the exact chunk byte sizes, which the browser's serializer measures

So a clean report means "nothing in these files is wrong on its own". It never
means the upload will succeed, and it says nothing at all about whether the
timestamps are in the timezone you think they are.

Exit codes: 0 clean | 1 findings | 2 usage | 3 no verdict (jsonschema missing,
or the shipped contract unreadable -- nothing validated).
"""

import argparse
import json
import math
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    from jsonschema import Draft202012Validator
except ImportError:  # pragma: no cover - exercised by hand, not in CI
    Draft202012Validator = None

NUL = "\x00"
MAX_DETAIL = 160
TEXT_FIELDS = ("conversation_id", "name", "customer_id", "language", "device")
FORBIDDEN_KEYS = frozenset({"__proto__", "constructor", "prototype"})

# Mirrors `_SCHEMA_KEYWORD_CODES` (validation.py) and KEYWORD_CODES
# (pre-validate.ts). `anyOf -> wrong_type` because `#/$defs/metadata` is an
# anyOf, so `"metadata": []` would otherwise report as an unexplained violation.
KEYWORD_CODES = {
    "additionalProperties": "unknown_field",
    "required": "missing_field",
    "type": "wrong_type",
    "anyOf": "wrong_type",
    "const": "wrong_value",
    "enum": "wrong_value",
    "pattern": "invalid_format",
    "maxLength": "too_long",
    "minLength": "too_short",
    "maxItems": "too_many_items",
    "minItems": "too_few_items",
}

SENDER_ALIASES = {
    "user": "end_user",
    "human": "end_user",
    "customer": "end_user",
    "end_user": "end_user",
    "assistant": "agent",
    "bot": "agent",
    "ai": "agent",
    "agent": "agent",
}

# Matches an ISO 8601 timestamp carrying an explicit offset or `Z`. Ported from
# HAS_OFFSET in pre-validate.ts; used unanchored, as JS `.test()` is.
HAS_OFFSET = re.compile(r"(?:Z|[+-]\d{2}:?\d{2}|[+-]\d{2})\s*$")

# A verbatim port of django.utils.dateparse.datetime_re, which is what the
# server parses with. NOT datetime.fromisoformat: on Python 3.9 that rejects
# `Z`, one-digit components, `+HH` and `+HHMM`, all of which the contract's own
# timestamp pattern admits -- so using it would make this script stricter than
# the server on the interpreter it happened to run under. The offset group
# stays optional so a naive timestamp reports `missing_offset` rather than a
# parse failure, which is what the server does.
DATETIME_RE = re.compile(
    r"(?P<year>\d{4})-(?P<month>\d{1,2})-(?P<day>\d{1,2})"
    r"[T ](?P<hour>\d{1,2}):(?P<minute>\d{1,2})"
    r"(?::(?P<second>\d{1,2})(?:[.,](?P<microsecond>\d{1,6})\d{0,6})?)?"
    r"\s*(?P<tzinfo>Z|[+-]\d{2}(?::?\d{2})?)?$"
)

# Neither of these is in limits.json -- the server enforces them but does not
# publish them -- so they are the only two numbers in this file that cannot be
# read from the contract. Worth raising with the backend: every third-party
# validator will hardcode them.
EARLIEST_TIMESTAMP = datetime(2000, 1, 1, tzinfo=timezone.utc)
FUTURE_TOLERANCE = timedelta(minutes=5)
# The server evaluates now()+5min at UPLOAD time, hours after this runs. A
# faithful mirror would reject timestamps the server will accept, so the
# ceiling is deliberately looser. A broken export is off by years, not by an
# hour.
UPLOAD_GRACE = timedelta(hours=1)


class Finding:
    """One report line. `level` is "file" or "record"."""

    def __init__(self, level, code, path, index, cid, field, detail):
        self.level = level
        self.code = code
        self.path = path
        self.index = index
        self.cid = cid
        self.field = field
        self.detail = detail[:MAX_DETAIL]


# --------------------------------------------------------------------------
# Contract
# --------------------------------------------------------------------------


# The contract ships with the skill: a snapshot of the server's schema, limits
# and example, taken from an ags_backend checkout by
# tests/skills/regenerate_corpus.py. MANIFEST.json names the backend commit.
CONTRACT_DIR = Path(__file__).resolve().parent.parent / "contract"
SCHEMA_FILE = "import_v1.schema.json"
LIMITS_FILE = "limits.json"
MANIFEST_FILE = "MANIFEST.json"

# Every key this script indexes off the limits document. A snapshot missing
# one is exit 3 up front, not a KeyError halfway through the second file.
REQUIRED_LIMIT_KEYS = (
    "schema_version",
    "max_conversations_per_run",
    "max_chunk_request_bytes",
    "max_import_file_bytes",
    "max_metadata_bytes",
    "max_metadata_depth",
)


def load_contract(contract_dir):
    """Return (schema, limits, manifest) from the shipped snapshot.

    Raises RuntimeError naming what is wrong. The manifest is optional: a
    hand-assembled copy still validates, it just cannot say which backend
    commit it came from.
    """
    contract_dir = Path(contract_dir)
    schema = _read_json(contract_dir / SCHEMA_FILE)
    limits = _read_json(contract_dir / LIMITS_FILE)
    manifest_path = contract_dir / MANIFEST_FILE
    manifest = _read_json(manifest_path) if manifest_path.exists() else {}

    if not isinstance(limits, dict):
        raise RuntimeError(f"{LIMITS_FILE} is not a JSON object")
    missing = [key for key in REQUIRED_LIMIT_KEYS if key not in limits]
    if missing:
        raise RuntimeError(f"{LIMITS_FILE} lacks {', '.join(missing)}")

    # Two caps the server enforces in Python but publishes only through the
    # schema (data_imports/tests/test_contract_drift.py::test_metadata_key_rules
    # pins them to limits.py). Read them off the schema rather than restating
    # them here.
    try:
        metadata_object = schema["$defs"]["metadataObject"]
        limits = dict(limits)
        limits["max_metadata_keys_per_level"] = metadata_object["maxProperties"]
        limits["max_metadata_key_length"] = metadata_object["propertyNames"]["maxLength"]
    except (KeyError, TypeError) as exc:
        raise RuntimeError(f"{SCHEMA_FILE} carries no metadataObject caps ({exc!r})") from exc
    return schema, limits, manifest


def _read_json(path):
    try:
        return json.loads(path.read_bytes())
    except OSError as exc:
        raise RuntimeError(f"cannot read {path.name}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{path.name} is not valid JSON: {exc}") from exc


def describe_contract(manifest, limits):
    """The report's header line: which snapshot this run checked against."""
    version = limits.get("schema_version")
    commit = str(manifest.get("commit") or "")[:12]
    exported = str(manifest.get("exported_at") or "")[:10]
    if commit and exported:
        return (
            f"shipped snapshot -- ags_backend@{commit} exported {exported}, "
            f"schema_version {version}"
        )
    return f"unversioned snapshot, schema_version {version}"


def build_validator(schema):
    """Mirrors schema/loader.py::conversation_validator().

    Compiles `#/$defs/conversation`, not the file root -- that is the subschema
    the upload path applies per record. NO format_checker: `format: date-time`
    is annotation-only and the `pattern` does the work. Never tighten `sender`
    into an enum; it is a case-insensitive pattern precisely so that a client
    cannot end up stricter than the server.
    """
    return Draft202012Validator(
        {"$schema": schema.get("$schema"), "$defs": schema["$defs"], "$ref": "#/$defs/conversation"}
    )


# --------------------------------------------------------------------------
# Schema-error helpers (ports of validation.py:214-268 and pre-validate.ts:202)
# --------------------------------------------------------------------------


def field_path(segments):
    parts = []
    for segment in segments:
        if isinstance(segment, int):
            if parts:
                parts[-1] = f"{parts[-1]}[{segment}]"
            else:
                parts.append(f"[{segment}]")
        else:
            parts.append(str(segment))
    return ".".join(parts) or None


def unexpected_keys(error):
    if not isinstance(error.instance, dict) or not isinstance(error.schema, dict):
        return []
    return sorted(set(error.instance) - set(error.schema.get("properties", {})))


def error_field(error):
    path = field_path(error.absolute_path)
    if error.validator == "additionalProperties":
        extras = unexpected_keys(error)
        if extras:
            named = ", ".join(extras)
            return f"{path}.{named}" if path else named
    if error.validator == "required":
        missing = getattr(error, "message", "").split("'")
        if len(missing) > 1:
            return f"{path}.{missing[1]}" if path else missing[1]
    return path


def refine_pattern(field, value):
    """A pattern failure, named the way the server's value pass names it."""
    text = value if isinstance(value, str) else ""
    leaf = field.split(".")[-1] if field else ""

    if NUL in text:
        return "nul_byte", "This value contains a NUL character, which cannot be stored."
    if leaf == "sender":
        return "unknown_sender", f'"{text}" is not an importable sender.'
    if leaf in ("started_at", "timestamp"):
        if HAS_OFFSET.search(text):
            return "invalid_timestamp", f'"{text}" is not a readable ISO 8601 timestamp.'
        return "missing_offset", f'"{text}" has no time zone offset.'
    if text.strip() == "":
        return "too_short", "This value is empty."
    return "invalid_format", "This value does not match the format this field requires."


def value_at(conversation, segments):
    node = conversation
    for segment in segments:
        try:
            node = node[segment]
        except (KeyError, IndexError, TypeError):
            return None
    return node


# --------------------------------------------------------------------------
# Timestamps
# --------------------------------------------------------------------------


def parse_datetime(raw):
    """django.utils.dateparse.parse_datetime, ported. None when unparseable."""
    match = DATETIME_RE.match(raw)
    if not match:
        return None
    parts = match.groupdict()
    if parts["microsecond"]:
        parts["microsecond"] = parts["microsecond"].ljust(6, "0")
    tz = parts.pop("tzinfo")
    tzinfo = None
    try:
        if tz == "Z":
            tzinfo = timezone.utc
        elif tz is not None:
            minutes = int(tz[-2:]) if len(tz) > 3 else 0
            offset = 60 * int(tz[1:3]) + minutes
            if tz[0] == "-":
                offset = -offset
            tzinfo = timezone(timedelta(minutes=offset))
        # `+99:99` is admitted by the contract's own pattern and refused by
        # timezone(); the server catches the same ValueError into
        # invalid_timestamp rather than crashing, so this must too.
        fields = {key: int(value) for key, value in parts.items() if value is not None}
        return datetime(**fields, tzinfo=tzinfo)
    except (ValueError, OverflowError):
        return None


def check_timestamp(raw, field, emit, latest):
    parsed = parse_datetime(raw)
    if parsed is None:
        emit("invalid_timestamp", f"{raw!r} is not a valid ISO 8601 timestamp.", field)
        return None
    if parsed.utcoffset() is None:
        emit("missing_offset", f"{raw!r} has no UTC offset.", field)
        return None
    if parsed < EARLIEST_TIMESTAMP or parsed > latest:
        emit("timestamp_out_of_range", f"{raw!r} is outside the plausible range.", field)
        return None
    return parsed


# --------------------------------------------------------------------------
# The value pass (mirrors _scan_metadata / _check_values)
# --------------------------------------------------------------------------


def scan_metadata(metadata, base_path, emit, limits):
    serialized = json.dumps(metadata, separators=(",", ":"), ensure_ascii=False)
    size = len(serialized.encode("utf-8"))
    max_bytes = limits["max_metadata_bytes"]
    if size > max_bytes:
        emit(
            "metadata_too_large",
            f"metadata serialises to {size} bytes, past the {max_bytes}-byte limit.",
            base_path,
        )

    max_depth = limits["max_metadata_depth"]
    max_keys = limits["max_metadata_keys_per_level"]
    max_key_len = limits["max_metadata_key_length"]

    def walk(value, path, depth):
        if isinstance(value, dict):
            if depth > max_depth:
                emit("metadata_too_deep", f"metadata nests deeper than {max_depth} levels.", path)
                return
            if len(value) > max_keys:
                emit(
                    "too_many_metadata_keys",
                    f"{len(value)} keys at this level, past the limit of {max_keys}.",
                    path,
                )
            for key, child in value.items():
                if not isinstance(key, str):
                    continue
                key_path = f"{path}.{key}"
                if NUL in key:
                    emit("nul_byte", nul_detail(key), key_path)
                if len(key) > max_key_len:
                    emit(
                        "metadata_key_too_long",
                        f"metadata key is {len(key)} characters, past the limit "
                        f"of {max_key_len}.",
                        key_path,
                    )
                if key in FORBIDDEN_KEYS:
                    emit(
                        "forbidden_metadata_key",
                        f"{key!r} is a reserved key name and cannot be used in metadata.",
                        key_path,
                    )
                walk(child, key_path, depth + 1)
        elif isinstance(value, list):
            # A list is NOT a nesting level -- depth counts objects. Counting
            # arrays here would reject legal files.
            for index, item in enumerate(value):
                walk(item, f"{path}[{index}]", depth)
        elif isinstance(value, str):
            if NUL in value:
                emit("nul_byte", nul_detail(value), path)
        elif isinstance(value, float) and not math.isfinite(value):
            emit(
                "invalid_number",
                f"{value} is not a value JSON can represent. NaN and Infinity are "
                f"extensions your exporter should be emitting as null.",
                path,
            )

    walk(metadata, base_path, depth=1)


def nul_detail(value):
    return (
        f"Contains a NUL character (U+0000) at position {value.index(NUL)}. "
        f"Postgres cannot store NUL in text or JSON; strip it from the export."
    )


def check_values(conversation, emit, latest, limits):
    """Every rule about what a value *is*. Type errors are left to the schema."""
    for field in TEXT_FIELDS:
        value = conversation.get(field)
        if isinstance(value, str) and NUL in value:
            emit("nul_byte", nul_detail(value), field)

    metadata = conversation.get("metadata")
    if isinstance(metadata, dict):
        scan_metadata(metadata, "metadata", emit, limits)

    raw_started_at = conversation.get("started_at")
    started_at = None
    if isinstance(raw_started_at, str):
        started_at = check_timestamp(raw_started_at, "started_at", emit, latest)

    messages = conversation.get("messages")
    if not isinstance(messages, list):
        return

    for index, message in enumerate(messages):
        if not isinstance(message, dict):
            continue
        prefix = f"messages[{index}]"

        raw_sender = message.get("sender")
        if isinstance(raw_sender, str):
            if NUL in raw_sender:
                emit("nul_byte", nul_detail(raw_sender), f"{prefix}.sender")
            elif raw_sender.strip().lower() not in SENDER_ALIASES:
                emit(
                    "unknown_sender",
                    f"{raw_sender!r} is not a recognised sender. Map it to the customer "
                    f"side (user / human / customer / end_user) or the assistant side "
                    f"(assistant / bot / ai / agent); 'system' and 'tool' rows have "
                    f"nowhere to go and must be stripped before upload.",
                    f"{prefix}.sender",
                )

        content = message.get("content")
        if isinstance(content, str) and NUL in content:
            emit("nul_byte", nul_detail(content), f"{prefix}.content")

        raw_timestamp = message.get("timestamp")
        if isinstance(raw_timestamp, str):
            stamp = check_timestamp(raw_timestamp, f"{prefix}.timestamp", emit, latest)
            if stamp is not None and started_at is not None and stamp < started_at:
                emit(
                    "before_started_at",
                    f"{raw_timestamp} is before started_at {raw_started_at}.",
                    f"{prefix}.timestamp",
                )

        message_metadata = message.get("metadata")
        if isinstance(message_metadata, dict):
            scan_metadata(message_metadata, f"{prefix}.metadata", emit, limits)


def check_schema(conversation, validator, emit):
    for error in sorted(validator.iter_errors(conversation), key=str):
        field = error_field(error)
        code = KEYWORD_CODES.get(error.validator, "schema_violation")
        detail = error.message
        if error.validator == "pattern":
            code, detail = refine_pattern(field, value_at(conversation, error.absolute_path))
        emit(code, detail, field)


# --------------------------------------------------------------------------
# Files
# --------------------------------------------------------------------------


def check_envelope(data, size, limits, findings, path):
    """The checks the dashboard makes before a byte is uploaded."""
    def add(code, detail, field):
        findings.append(Finding("file", code, path, None, None, field, detail))

    cap = limits.get("max_import_file_bytes")
    if cap and size > cap:
        add("file_too_large", f"file is {size} bytes, past the {cap}-byte browser cap.", None)

    if not isinstance(data, dict):
        add("not_an_object", "The file's top level must be a JSON object.", None)
        return None

    # Strict, and strict about the type: `"1"` is a rejection, and so is `True`,
    # which would otherwise pass `== 1`. Mirrors checkSchemaVersion().
    expected = limits.get("schema_version", 1)
    found = data.get("schema_version")
    if isinstance(found, bool) or not isinstance(found, int) or found != expected:
        add(
            "wrong_value",
            f"declares schema_version as {found!r}; this dashboard imports version "
            f"{expected}.",
            "schema_version",
        )

    if "conversations" not in data:
        add("missing_field", "The file has no `conversations` key.", "conversations")
        return None
    conversations = data["conversations"]
    if not isinstance(conversations, list):
        add("wrong_type", "`conversations` must be an array.", "conversations")
        return None
    if not conversations:
        add("too_few_items", "`conversations` is empty.", "conversations")
        return None
    run_cap = limits.get("max_conversations_per_run")
    if run_cap and len(conversations) > run_cap:
        add(
            "too_many_conversations",
            f"{len(conversations)} conversations, past the {run_cap} an import accepts; "
            f"split this file.",
            "conversations",
        )
    return conversations


def validate_file(path, data, size, ctx, findings, warnings, seen_ids):
    conversations = check_envelope(data, size, ctx["limits"], findings, path)
    if conversations is None:
        return 0, 0

    extras = sorted(set(data) - {"schema_version", "conversations"})
    if extras:
        warnings.append(
            f"{path} carries unknown top-level keys ({', '.join(extras)}). Nothing in "
            f"the pipeline reads or rejects them, but the schema forbids them."
        )

    messages = 0
    chunk_cap = ctx["limits"].get("max_chunk_request_bytes")
    for index, conversation in enumerate(conversations):
        cid = conversation.get("conversation_id") if isinstance(conversation, dict) else None
        cid = cid if isinstance(cid, str) else None
        record = []

        def emit(code, detail, field, _record=record):
            _record.append(Finding("record", code, path, index, cid, field, detail))

        if not isinstance(conversation, dict):
            emit("not_an_object", "Every entry in `conversations` must be a JSON object.", None)
            findings.extend(record)
            continue

        if isinstance(conversation.get("messages"), list):
            messages += len(conversation["messages"])

        check_values(conversation, emit, ctx["latest"], ctx["limits"])
        # Mirrors validation.py:783-786: a record that failed the value pass is
        # never handed to the schema. Running both would report codes for a
        # record the server describes differently.
        if not record and ctx["validator"] is not None:
            check_schema(conversation, ctx["validator"], emit)

        if cid and NUL not in cid:
            if cid in seen_ids:
                emit(
                    "duplicate_conversation_id",
                    f"conversation_id {cid!r} already appears at {seen_ids[cid]}. Ids must "
                    f"be unique across the whole import.",
                    "conversation_id",
                )
            else:
                seen_ids[cid] = f"{path}#{index}"

        if chunk_cap:
            body = len(json.dumps(conversation, separators=(",", ":")).encode("utf-8"))
            if body > chunk_cap:
                warnings.append(
                    f"{path} #{index} serialises to {body} bytes, past the "
                    f"{chunk_cap}-byte chunk budget; the dashboard cannot pack it."
                )
        findings.extend(record)

    return len(conversations), messages


def read_file(path):
    raw = Path(path).read_bytes()
    # The browser's File.text() strips a BOM and substitutes U+FFFD for invalid
    # UTF-8. Strict decoding here would reject a file the dashboard opens.
    return json.loads(raw.decode("utf-8-sig", errors="replace")), len(raw)


# --------------------------------------------------------------------------
# Report
# --------------------------------------------------------------------------

CANNOT_CHECK = """
NOT CHECKED HERE -- the server checks these when the file is uploaded:
  conversation_already_exists    an id that already exists for the target agent
  staging collisions             an id held by another open import run
  run bookkeeping                declared counts and the per-agent open-run cap
  exact chunk byte sizes         measured by the browser's serializer, not this one
A clean report means "nothing in these files is wrong on its own". It never
means the upload will succeed, and it cannot see a wrong timezone at all.
""".rstrip()


def render(findings, warnings, stats, contract, max_examples):
    out = [
        f"AgentSight import pre-flight -- {stats['files']} file(s), "
        f"{stats['conversations']:,} conversations, {stats['messages']:,} messages",
        f"Contract: {contract['source']}",
        "",
    ]

    if not findings:
        out.append("PASSED -- no findings.")
    else:
        by_code = {}
        for finding in findings:
            by_code.setdefault(finding.code, []).append(finding)
        ordered = sorted(by_code.items(), key=lambda kv: (-len(kv[1]), kv[0]))
        out.append(
            f"FAILED -- {len(findings):,} finding(s), {len(by_code)} distinct code(s)."
        )
        for code, group in ordered:
            out.append("")
            out.append(f"  {code} {'.' * max(3, 58 - len(code))} {len(group):,}")
            for finding in group[:max_examples]:
                where = finding.path
                if finding.index is not None:
                    where += f"  #{finding.index}"
                if finding.cid:
                    where += f"  {finding.cid}"
                out.append(f"    {where}  [{finding.field or '-'}]")
                out.append(f"      {finding.detail}")
            hidden = len(group) - max_examples
            if hidden > 0:
                out.append(f"    ... {hidden:,} more not shown (--max-examples)")

    if warnings:
        out.append("")
        out.append("WARNINGS (these do not affect the exit code)")
        for warning in warnings:
            out.append(f"  {warning}")

    out.append("")
    out.append(CANNOT_CHECK)
    return "\n".join(out)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Validate AgentSight import part files against the shipped contract snapshot."
    )
    parser.add_argument("files", nargs="+", metavar="FILE", help="import part files, in order")
    parser.add_argument(
        "--contract",
        default=str(CONTRACT_DIR),
        metavar="DIR",
        help="another copy of the contract directory; only for testing a refreshed snapshot",
    )
    parser.add_argument("--max-examples", type=int, default=10, help="findings shown per code")
    args = parser.parse_args(argv)

    if Draft202012Validator is None:
        print(
            "validate_import.py: this script needs `jsonschema` to check the file's shape.\n"
            "    python3 -m pip install 'jsonschema>=4.23'\n"
            "Nothing was validated. Re-run after installing.",
            file=sys.stderr,
        )
        return 3

    try:
        schema, limits, manifest = load_contract(args.contract)
    except Exception as exc:
        print(
            f"validate_import.py: could not read the shipped contract at {args.contract}.\n"
            f"    {exc}\n"
            f"The skill install is incomplete: reinstall it, or pass --contract DIR pointing "
            f"at a complete copy. Nothing was validated.",
            file=sys.stderr,
        )
        return 3

    ctx = {
        "validator": build_validator(schema),
        "limits": limits,
        "latest": datetime.now(timezone.utc) + FUTURE_TOLERANCE + UPLOAD_GRACE,
    }
    contract = {"source": describe_contract(manifest, limits)}

    findings, warnings, seen_ids = [], [], {}
    stats = {"files": len(args.files), "conversations": 0, "messages": 0}
    for path in args.files:
        try:
            data, size = read_file(path)
        except OSError as exc:
            print(f"validate_import.py: cannot read {path}: {exc}", file=sys.stderr)
            return 2
        except json.JSONDecodeError as exc:
            findings.append(Finding("file", "invalid_json", path, None, None, None, str(exc)))
            continue
        conversations, messages = validate_file(
            path, data, size, ctx, findings, warnings, seen_ids
        )
        stats["conversations"] += conversations
        stats["messages"] += messages

    print(render(findings, warnings, stats, contract, args.max_examples))
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
