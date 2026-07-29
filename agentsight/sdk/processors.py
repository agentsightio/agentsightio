"""Span processing between the tracer and the batch exporter."""

from threading import Lock
from typing import Dict, List, Optional

from opentelemetry.context import Context
from opentelemetry.sdk.trace import ReadableSpan, Span, SpanProcessor

from agentsight.sdk import context as ags_context
from agentsight.sdk.semconv import SpanAttributes, SpanKind, TurnAttributes


class TurnBufferingProcessor(SpanProcessor):
    """Holds a turn's spans until the turn ends, then releases or discards them.

    Exists because of an ordering fact: a child span ends *before* its parent.
    By the time we learn a turn was abandoned mid-stream, its tool and LLM
    spans would already have been handed to the batch processor and exported.
    Buffering is the only way "an unfinished turn is not sent" (design §4.3)
    can mean anything.

    Grouping uses an explicit ``agentsight.turn.id`` attribute rather than the
    parent chain, because a ReadableSpan exposes only its immediate parent —
    there is no way to walk up to the enclosing turn at export time.

    Spans with no enclosing turn pass straight through.
    """

    #: Cap on spans held for one turn. Past this the buffer is released early
    #: and the turn stops being retractable — bounded memory beats a perfect
    #: discard guarantee, because an agent that makes thousands of tool calls
    #: in a single turn would otherwise hold them all until the turn ends and
    #: then flood the export queue in one burst.
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
                own_id = format(span.get_span_context().span_id, "016x")
                with self._lock:
                    buffered = self._open.pop(own_id, [])

                complete = attributes.get(TurnAttributes.COMPLETE, False)

                if buffered is None:
                    # Overflowed earlier: children are already downstream and
                    # cannot be retracted. Emit the turn regardless so the
                    # exported children have a parent, and let ingest decide.
                    self._downstream.on_end(span)
                    return

                if not complete:
                    # Abandoned or failed: drop the turn and everything under it.
                    return

                for buffered_span in buffered:
                    self._downstream.on_end(buffered_span)
                self._downstream.on_end(span)
                return

            turn_id = attributes.get(TurnAttributes.ID)
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
        # Anything still buffered belongs to a turn that never ended, which is
        # by definition unfinished — discard it and shut the chain down.
        with self._lock:
            self._open.clear()
        self._downstream.shutdown()

    def force_flush(self, timeout_millis: int = 30_000) -> bool:
        return self._downstream.force_flush(timeout_millis)
