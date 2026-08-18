"""Writing ingest payloads to disk instead of POSTing them.

The point is visibility: an integration can be run and the exact bytes the
backend would receive can then be read out of a directory, with no backend, no
API key and no network. That makes "what does LlamaIndex actually emit" a
question you answer by opening a file rather than by reading the handler.

It exists for development, not for production delivery — nothing here retries,
batches by size or bounds how much disk it uses. It is reached by setting
``AGENTSIGHT_FILE_EXPORTER`` to a directory, or by passing an instance as
``init(span_exporter=...)``. It is deliberately absent from
``agentsight.sdk.__all__``: importable, not part of the promised 1.0 surface.

Payloads come from :func:`agentsight.sdk.exporter.build_payload` — the same
function the HTTP transport uses. Sharing it is the whole design: a file that
disagrees with what the wire carries would be worse than no file at all.
"""

import json
import os
import threading
from datetime import datetime, timezone
from typing import Any, Optional, Sequence

from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult

from agentsight.sdk.exporter import build_payload


class FileSpanExporter(SpanExporter):
    """Writes one JSON file per export batch into ``directory``.

    Files are named ``<utc-timestamp>-<counter>.json``, so a plain directory
    listing is in export order — within a run *and* across runs, which a
    counter-first name would not give. The counter only breaks ties between two
    exports landing in the same millisecond.
    """

    def __init__(self, directory: str, logger: Any):
        self._directory = os.path.abspath(os.path.expanduser(directory))
        self._logger = logger
        self._lock = threading.Lock()
        self._counter = 0

        #: For tests and for the examples' end-of-run summary. A count and the
        #: most recent path rather than every path, so a long-running process
        #: does not accumulate a list it never reads.
        self.files_written = 0
        self.last_path: Optional[str] = None

        if os.path.exists(self._directory) and not os.path.isdir(self._directory):
            raise ValueError(
                "AGENTSIGHT_FILE_EXPORTER must name a directory; "
                f"{self._directory} is an existing file"
            )
        # Eagerly, so a bad path fails at init() where someone is watching,
        # rather than silently on a background thread an export interval later.
        os.makedirs(self._directory, exist_ok=True)

    @property
    def directory(self) -> str:
        return self._directory

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        try:
            payload = build_payload(spans)
            if not payload["conversations"]:
                return SpanExportResult.SUCCESS
            return self._write(payload)
        except Exception as exc:
            # Same contract as the HTTP transport: an exporter runs on the
            # batch processor's thread and must never raise there.
            self._logger.error("span export to file failed: %s", exc)
            return SpanExportResult.FAILURE

    def _write(self, payload: dict) -> SpanExportResult:
        with self._lock:
            self._counter += 1
            path = os.path.join(self._directory, self._filename(self._counter))

        try:
            with open(path, "w", encoding="utf-8") as handle:
                # No ``default=`` fallback: anything the standard encoder
                # refuses would also fail on the wire, and a file that quietly
                # stringifies it would misrepresent what the backend receives.
                # ``ensure_ascii=False`` only affects escaping, so the text a
                # user typed reads as itself.
                json.dump(payload, handle, indent=2, ensure_ascii=False)
                handle.write("\n")
        except Exception as exc:
            self._logger.error("could not write %s: %s", path, exc)
            return SpanExportResult.FAILURE

        with self._lock:
            self.files_written += 1
            self.last_path = path

        self._logger.debug(
            "wrote %d conversation(s) to %s", len(payload["conversations"]), path
        )
        return SpanExportResult.SUCCESS

    @staticmethod
    def _filename(counter: int) -> str:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%f")[:-3]
        return f"{stamp}Z-{counter:04d}.json"

    def shutdown(self) -> None:
        """Nothing to release — every write is closed as it is made."""

    def force_flush(self, timeout_millis: int = 30_000) -> bool:
        return True
