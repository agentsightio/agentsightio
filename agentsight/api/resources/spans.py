"""Reading the raw span archive."""

from typing import Any, Dict

from agentsight.api import _params
from agentsight.api._pagination import PageIterator
from agentsight.api.resources._base import Resource
from agentsight.exceptions import ValidationError


class Spans(Resource):
    """``ags.spans`` — the OpenTelemetry spans this SDK sent, as stored.

    Read-only. Rows are written by the tracking SDK's exporter and projected
    server-side into conversations, messages, action logs and token usage;
    there is no way to create or edit one here.

    This is the archive those projections are *derived from*, so it holds what
    they deliberately drop: exact parent/child structure, per-call durations
    and status, OpenTelemetry resource and instrumentation-scope attributes,
    tool arguments and responses, and any attribute a newer SDK emits that the
    backend has no projection rule for yet. When a conversation renders in a
    way you did not expect, this is where the answer is.

    Three shapes, cheapest first:

    :meth:`list`
        spans matching filters, newest first. Carries ``attributes`` and
        ``events`` — the tool arguments, responses and message content — but
        never ``payload``.
    :meth:`get`
        one span by id, optionally with ``payload``: the verbatim span, the
        largest field on the row, and the only place the raw OTel envelope is
        readable.
    :meth:`trace`
        one whole trace, nested by ``parent_span_id`` instead of flat. The
        shape to reach for when the question is "what happened inside this
        turn", rather than "find me the spans that look like X".
    """

    def list(self, **filters: Any) -> PageIterator:
        """Spans matching ``filters``, newest first.

        Returns a lazy iterator — nothing is fetched until you iterate::

            for span in ags.spans.list(kind="tool", status="error"):
                print(span["name"], span["duration_ms"])

        Call ``.page()`` on the result instead to read ``count`` without
        walking everything.

        Filters: ``conversation`` (pk), ``conversation_id`` (string),
        ``environment``, ``kind``, ``name``, ``ordering``, ``parent_span_id``,
        ``span_id``, ``started_at_after``, ``started_at_before``, ``status``,
        ``trace_id``. Datetimes and booleans are converted for you.

        The set is small on purpose: it is built around the three indexes the
        span table has, so every filter offered is one the database can serve.
        There is no substring search on ``name`` and no filtering inside
        ``attributes`` — over an archive of every span an agent ever sent,
        those are the queries that would need an index before they were worth
        offering.

        ``kind`` is whatever the emitting SDK called it — ``turn``, ``llm``,
        ``tool``, ``task``, ``button``, ``attachment``, ``conversation`` today,
        and it is deliberately not validated here, because a newer SDK version
        may send a kind this release has never heard of and the backend stores
        it rather than rejecting it.

        Rows never carry ``payload``, at any page size. See :meth:`get`.
        """
        return PageIterator(
            lambda query: self._request("GET", "/api/spans/", params=query),
            self._filters(filters),
        )

    def get(self, span: int, *, payload: bool = False) -> Dict[str, Any]:
        """One span by its integer id.

        ``payload=True`` adds the verbatim OpenTelemetry span — resource
        attributes, instrumentation scope, links, trace flags and state, status
        description, dropped-record counts, and any field a future SDK adds.
        Nothing was discarded on the way in, so this is the whole thing as it
        arrived.

        It is off by default, and only ever available one span at a time. The
        field repeats ``attributes`` and ``events`` inside itself and is about
        half a stored span's bytes; a list of them is the mistake the
        conversation list had to correct, where every row arrived carrying its
        whole transcript.

        ``span`` is the ``id`` from a list row, not the ``span_id`` — that one
        is the OpenTelemetry identifier and is only unique within a
        conversation.
        """
        if not isinstance(span, int) or isinstance(span, bool):
            raise ValidationError(
                f"get() needs a span id (the `id` field on a row), got {span!r}"
            )
        return self._request(
            "GET",
            f"/api/spans/{span}/",
            # Sent explicitly rather than left to the server's default. The
            # conversation list is what happens when a client assumes one.
            params={"payload": "true" if payload else "false"},
        )

    def trace(self, trace_id: str) -> Dict[str, Any]:
        """One trace as a tree, nested by ``parent_span_id``.

        The same spans ``list(trace_id=...)`` returns, arranged the way they
        happened — which LLM call ran inside which turn, which tool the model
        reached for, where the time went::

            trace = ags.spans.trace(span["trace_id"])
            for root in trace["roots"]:
                print(root["name"], [child["name"] for child in root["children"]])

        Returns ``{trace_id, span_count, truncated, roots}``. Each node is a
        span row plus a ``children`` list, nested to whatever depth the agent
        produced, and never carrying ``payload`` — read that one span at a time
        through :meth:`get`.

        A span whose parent is not in the trace appears as a root rather than
        being dropped, so ``span_count`` always equals the number of nodes in
        the tree.

        ``truncated`` is ``True`` when the trace was larger than the server
        assembles in one response and the tail was cut. It means spans are
        missing from this tree, not that the trace ended there; reach for
        ``list(trace_id=...)`` and page if you need all of them.

        Not paginated, so there is no iterator here.
        """
        if not trace_id:
            raise ValidationError("trace() needs a trace_id")
        return self._request("GET", f"/api/traces/{trace_id}/")

    # -- internals ---------------------------------------------------------

    def _filters(self, filters: Dict[str, Any]) -> Dict[str, Any]:
        params = _params.build(
            # `rename={}` on purpose: like /api/token-usage/, this route's
            # filter really is spelled `environment`, and the `env` alias the
            # conversation and feedback routes use would be silently ignored —
            # which returns more rows than the caller asked for.
            filters, _params.SPAN_FILTERS, what="span", rename={},
        )
        # Never the server's default: a list of verbatim spans is the one
        # response this route exists to not send.
        params["payload"] = "false"
        return params
