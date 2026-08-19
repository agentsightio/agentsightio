"""Shared plumbing for the example scripts.

Importing this module puts the repository root on ``sys.path``, so the examples
run against the working tree with nothing installed::

    venv/bin/python examples/01_plain.py

Each script calls :func:`start`, does its work, and calls ``run.finish()``.
``start()`` points ``AGENTSIGHT_FILE_EXPORTER`` at a directory of its own and
empties it first, so what you read after a run is that run and not a pile of
earlier ones. Set ``AGENTSIGHT_FILE_EXPORTER`` yourself to move the whole tree
somewhere else; the per-script subdirectory is still added.

The summary ``finish()`` prints is a convenience for reading at the terminal.
The files are the artefact — they are the exact JSON body the ingest endpoint
would have received, produced by the same function the HTTP transport uses.
"""

import json
import os
import shutil
import sys
from pathlib import Path

EXAMPLES = Path(__file__).resolve().parent
sys.path.insert(0, str(EXAMPLES.parent))

import agentsight as ags  # noqa: E402
from agentsight.sdk.instrumentation import installed_targets  # noqa: E402
from agentsight.sdk.semconv import (  # noqa: E402
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

RULE = "─" * 72


class Run:
    """One example's SDK lifetime plus the report at the end of it.

    ``directory`` is ``None`` in HTTP mode — the spans went to a server, so
    there are no files to read back.
    """

    def __init__(self, name: str, directory):
        self.name = name
        self.directory = directory

    def finish(self) -> None:
        # shutdown() flushes on the way out, so nothing needs flushing here.
        ags.shutdown()
        self.report()

    def report(self) -> None:
        if self.directory is None:
            print()
            print(RULE)
            print(f"{self.name} · spans POSTed to the ingest endpoint")
            print("verify in the dashboard: this run's conversation, its "
                  "transcript and its token spend should now be there")
            print(RULE)
            return
        payloads = _read_payloads(self.directory)
        print()
        print(RULE)
        print(f"{self.name} · {len(payloads)} export file(s) in {_display(self.directory)}")
        active = ", ".join(sorted(installed_targets())) or "none"
        print(f"instrumentation active: {active}")
        print(RULE)

        if not payloads:
            print("(no spans exported)")
            return

        spans = [span for payload in payloads for block in payload["conversations"]
                 for span in block["spans"]]
        for payload in payloads:
            for block in payload["conversations"]:
                _print_conversation(block)

        counts = {}
        for span in spans:
            counts[span["kind"]] = counts.get(span["kind"], 0) + 1
        print()
        print("spans: " + "  ".join(f"{k}={v}" for k, v in sorted(counts.items())))


def start(name: str, **init_kwargs) -> Run:
    """Send this script's spans to a directory of their own and initialise.

    With ``AGENTSIGHT_EXAMPLES_HTTP=1`` the file exporter is skipped entirely
    and spans go over HTTP instead: ``init()`` reads ``AGENTSIGHT_API_KEY``
    and ``AGENTSIGHT_API_ENDPOINT`` from the environment, so pointing an
    example at a local backend is::

        AGENTSIGHT_EXAMPLES_HTTP=1 AGENTSIGHT_API_KEY=ags_... \\
        AGENTSIGHT_API_ENDPOINT=http://localhost:8000 python examples/01_plain.py
    """
    if os.getenv("AGENTSIGHT_EXAMPLES_HTTP"):
        # A file-exporter variable left in the shell would silently reroute
        # the spans back to disk — clear it loudly instead.
        if os.environ.pop("AGENTSIGHT_FILE_EXPORTER", None):
            print("AGENTSIGHT_EXAMPLES_HTTP is set — ignoring AGENTSIGHT_FILE_EXPORTER")
        print(f"{RULE}\n{name}\n{RULE}")
        endpoint = os.getenv("AGENTSIGHT_API_ENDPOINT") or "the default endpoint"
        print(f"HTTP mode: POSTing spans to {endpoint}")
        if not ags.init(**init_kwargs):
            raise SystemExit("agentsight.init() failed; see the log above")
        return Run(name, None)

    root = Path(os.getenv("AGENTSIGHT_FILE_EXPORTER") or (EXAMPLES / "traces"))
    directory = root / name
    if directory.exists():
        shutil.rmtree(directory)
    os.environ["AGENTSIGHT_FILE_EXPORTER"] = str(directory)

    print(f"{RULE}\n{name}\n{RULE}")
    if not ags.init(**init_kwargs):
        raise SystemExit("agentsight.init() failed; see the log above")
    return Run(name, directory)


def live(provider_key: str) -> bool:
    """Whether to call the real provider, announcing it if so.

    Beware: importing ``agentsight`` runs ``load_dotenv()``, so a key sitting
    in the repository's ``.env`` counts as present even though nobody typed it
    this morning. Real calls are billed and slow, hence the banner and the
    escape hatch.
    """
    if os.getenv("AGENTSIGHT_EXAMPLES_OFFLINE"):
        print(f"AGENTSIGHT_EXAMPLES_OFFLINE is set — stubbing {provider_key}")
        return False
    if os.getenv(provider_key):
        print(f"!! {provider_key} is set: making REAL, BILLED calls to the provider.")
        print("!! Set AGENTSIGHT_EXAMPLES_OFFLINE=1 to use the stub instead.")
        return True
    print(f"no {provider_key} — driving the real instrumentation over a stub")
    return False


# ---------------------------------------------------------------------------
# Reading the payloads back
# ---------------------------------------------------------------------------


def _read_payloads(directory: Path):
    if not directory.is_dir():
        return []
    payloads = []
    for path in sorted(directory.glob("*.json")):
        with open(path, encoding="utf-8") as handle:
            payloads.append(json.load(handle))
    return payloads


def _display(path: Path) -> str:
    try:
        return str(path.relative_to(Path.cwd()))
    except ValueError:
        return str(path)


def _print_conversation(block) -> None:
    described = [f"{k}={v}" for k, v in sorted(block.items())
                 if k not in ("conversation_id", "spans")]
    print()
    print(f"conversation {block['conversation_id']}"
          + (f"   [{', '.join(described)}]" if described else ""))

    spans = block["spans"]
    by_parent = {}
    ids = {span["span_id"] for span in spans}
    for span in spans:
        parent = span["parent_span_id"]
        by_parent.setdefault(parent if parent in ids else None, []).append(span)

    for span in by_parent.get(None, []):
        _print_span(span, by_parent, depth=1)


def _print_span(span, by_parent, depth) -> None:
    indent = "  " * depth
    duration = span.get("duration_ms")
    timing = f"{duration:8.1f}ms" if duration is not None else " " * 10
    print(f"{indent}{span['kind']:<12} {span['name']:<28} {timing}  {span['status']}"
          f"{_detail(span)}")

    for event in span.get("events", []):
        if event["name"] == MessageAttributes.EVENT_NAME:
            attributes = event["attributes"]
            sender = attributes.get(MessageAttributes.SENDER)
            content = str(attributes.get(MessageAttributes.CONTENT, ""))
            if len(content) > 60:
                content = content[:57] + "..."
            print(f"{indent}  · {sender:<9} {content!r}")

    for child in by_parent.get(span["span_id"], []):
        _print_span(child, by_parent, depth + 1)


def _detail(span) -> str:
    """The one or two facts that make each span kind worth looking at."""
    a = span["attributes"]
    kind = span["kind"]

    if kind == SpanKind.TURN:
        if a.get(TurnAttributes.COMPLETE) is False:
            return f"   INCOMPLETE({a.get(TurnAttributes.INCOMPLETE_REASON)})"
        return "   complete"

    if kind == SpanKind.LLM:
        bits = [str(a.get(LLMAttributes.REQUEST_MODEL, "?"))]
        tokens = sum(int(a.get(name, 0)) for name in LLMAttributes.BILLABLE)
        bits.append(f"{tokens} tok")
        # No cost here: the SDK sends counts, the backend prices them. Spend
        # shows up on the dashboard and through ags.usage, not in this tree.
        if a.get(LLMAttributes.STREAMING):
            bits.append("streamed")
        if a.get(LLMAttributes.USAGE_REPORTED) is False:
            bits.append("USAGE UNREPORTED")
        if a.get(LLMAttributes.ERROR):
            bits.append(f"ERROR: {a[LLMAttributes.ERROR]}")
        return "   " + "  ".join(bits)

    if kind in (SpanKind.TOOL, SpanKind.TASK):
        error = a.get(ToolAttributes.ERROR)
        return f"   ERROR: {error}" if error else ""

    if kind == SpanKind.BUTTON:
        return f"   {a.get(ButtonAttributes.LABEL)} = {a.get(ButtonAttributes.VALUE)}"

    if kind == SpanKind.ATTACHMENT:
        return f"   {a.get(AttachmentAttributes.COUNT)} file(s)"

    if kind == SpanKind.CONVERSATION:
        return "   visit phase (not yet engaged)"

    return ""


__all__ = [
    "ags",
    "start",
    "live",
    "Run",
    "RULE",
    "ConversationAttributes",
    "SpanAttributes",
]
