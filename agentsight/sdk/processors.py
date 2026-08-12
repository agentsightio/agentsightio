"""Span processing between the tracer and the batch exporter."""

from threading import Lock
from typing import Dict, List, Optional

from opentelemetry.context import Context
from opentelemetry.sdk.trace import ReadableSpan, Span, SpanProcessor

from agentsight.sdk import context as ags_context
from agentsight.sdk.semconv import (
    SpanAttributes,
    SpanKind,
    TurnAttributes,
    string_attribute,
)


class TurnBufferingProcessor(SpanProcessor):
    """Holds a turn's spans until the turn ends, then releases them together.

    Exists because of an ordering fact: a child span ends *before* its parent.
    Without buffering, a tool span would reach ingest at t=0 and its turn —
    the thing that says whether the exchange completed — up to a batch
    interval later, possibly in a different payload. Holding the family until
    the turn's outcome is known lets ingest see turn and children in one
    payload and decide archive-vs-project atomically, inside its
    one-transaction-per-conversation (design §7.2).

    Nothing is discarded here. An incomplete turn goes downstream like any
    other, marked ``agentsight.turn.complete=false`` plus a reason; keeping
    half-exchanges out of the transcript is ingest's job (design §4.3), and
    dropping the spans instead would erase token spend that was really spent.

    Grouping uses an explicit ``agentsight.turn.id`` attribute rather than the
    parent chain, because a ReadableSpan exposes only its immediate parent —
    there is no way to walk up to the enclosing turn at export time.

    Spans with no enclosing turn pass straight through.
    """

    #: Cap on spans held for one turn. Past this the buffer is released early
    #: and the turn's family may be split across payloads — bounded memory
    #: beats perfect same-payload delivery, because an agent that makes
    #: thousands of tool calls in a single turn would otherwise hold them all
    #: until the turn ends and then flood the export queue in one burst.
    #: Ingest already sorts spans and tolerates a late parent, so a split
    #: family degrades ordering, not correctness.
    MAX_BUFFERED_SPANS = 2048

    def __init__(self, downstream: SpanProcessor, max_buffered_spans: int = MAX_BUFFERED_SPANS):
        self._downstream = downstream
        self._max_buffered = max_buffered_spans
        #: turn_id -> buffered spans, or None once the turn has overflowed and
        #: its spans have already gone downstream.
        self._open: Dict[str, Optional[List[ReadableSpan]]] = {}
        self._lock = Lock()

    def on_start(self, span: Span, parent_context: Optional[Context] = None) -> None:
        try:
            turn = ags_context.current_turn()
            if turn is not None and turn.turn_id and turn.span is not span:
                span.set_attribute(TurnAttributes.ID, turn.turn_id)

            if (span.attributes or {}).get(SpanAttributes.KIND) == SpanKind.TURN:
                turn_id = format(span.get_span_context().span_id, "016x")
                with self._lock:
                    self._open[turn_id] = []
        except Exception:
            pass  # never break span creation
        self._downstream.on_start(span, parent_context)

    def on_end(self, span: ReadableSpan) -> None:
        try:
            attributes = span.attributes or {}

            if attributes.get(SpanAttributes.KIND) == SpanKind.TURN:
                ctx = span.get_span_context()
                # Optional only for bare-built spans; a failure here lands in
                # the except below and the span still goes downstream.
                assert ctx is not None
                own_id = format(ctx.span_id, "016x")
                with self._lock:
                    buffered = self._open.pop(own_id, None)

                # Complete or not, everything goes: children first, then the
                # turn that explains them. A None slot means the buffer
                # overflowed earlier and the children are already downstream.
                for buffered_span in buffered or ():
                    self._downstream.on_end(buffered_span)
                self._downstream.on_end(span)
                return

            turn_id = string_attribute(attributes, TurnAttributes.ID)
            if turn_id:
                overflow: Optional[List[ReadableSpan]] = None
                with self._lock:
                    if turn_id in self._open:
                        pending = self._open[turn_id]
                        if pending is None:
                            pass  # already overflowed — fall through, export now
                        elif len(pending) < self._max_buffered:
                            pending.append(span)
                            return
                        else:
                            # Release everything and stop buffering this turn.
                            pending.append(span)
                            overflow = pending
                            self._open[turn_id] = None

                if overflow is not None:
                    for buffered_span in overflow:
                        self._downstream.on_end(buffered_span)
                    return
        except Exception:
            pass  # fall through and export rather than lose the span

        self._downstream.on_end(span)

    def shutdown(self) -> None:
        # Anything still buffered belongs to a turn that never ended — by the
        # time we get here the watchdog has already fired every *deferred*
        # turn, so what remains is a plain `with` block open in some live
        # thread. Its turn span cannot be exported (it never ended), but the
        # children are real spans for real work: release them rather than
        # discard the spend. They arrive carrying a turn id whose turn never
        # shows up, which ingest archives rather than rejects (design §7.2).
        with self._lock:
            orphans = [s for buf in self._open.values() if buf for s in buf]
            self._open.clear()
        for orphan in orphans:
            try:
                self._downstream.on_end(orphan)
            except Exception:
                pass
        self._downstream.shutdown()

    def force_flush(self, timeout_millis: int = 30_000) -> bool:
        # Deliberately does NOT release buffered spans of still-open turns: a
        # turn's children wait for their turn so both land in one payload,
        # and the open turn span itself could not be exported anyway — OTel
        # only exports ended spans. flush() therefore delivers everything
        # whose turn has ended, and nothing that is still mid-exchange.
        return self._downstream.force_flush(timeout_millis)
