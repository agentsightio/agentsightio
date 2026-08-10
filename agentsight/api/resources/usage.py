"""Reading token usage and what it cost."""

from typing import Any, Dict

from agentsight.api import _params
from agentsight.api._pagination import PageIterator
from agentsight.api.resources._base import Resource


class Usage(Resource):
    """``ags.usage`` — tokens spent, and the money that went with them.

    Read-only. Rows are written by the tracking SDK from the token counts each
    provider reports; there is no way to create one here.

    **Cost is priced by the backend. This SDK computes none of it**, and sends
    none — it reports the token counts, the resolved model id and the
    timestamp, which is everything cost is a function of. That keeps every
    customer on one rate table instead of on whichever one their pinned release
    shipped with, and it means a rate that turns out to have been wrong can be
    restated across history rather than being frozen per-release.

    ``cost_source`` says where a row's ``cost_usd`` came from:

    ``backend``
        priced server-side. The number of record, and what you should expect.
    ``unpriced``
        no price matched this model, so no cost was booked. Reads as "we do not
        know", never as "this was free" — and it is recoverable, because the
        tokens are exact and the backend can restate the row once a rate for
        that model exists.
    ``reported``
        a client sent its own figure and no server-side price matched, so it
        was kept rather than booking zero. This SDK no longer produces such
        rows; the value remains for older clients and for historical data.

    Only the five billable token categories are priced. ``reasoning_tokens``
    and the audio counts are subsets of prompt/completion that are already
    priced through them, so pricing them again would double-count.
    """

    def list(self, **filters: Any) -> PageIterator:
        """Per-call token usage, one record per LLM call.

        Filters: ``conversation`` (pk), ``conversation_id`` (string),
        ``cost_source``, ``environment``, ``incomplete``, ``model``,
        ``ordering``, ``started_at_after``, ``started_at_before``, ``turn_id``.

        ``incomplete`` selects the calls whose usage never arrived — a stream
        that closed without a usage event, most often. Their token counts are
        unknowns rather than zeros, and averaging over them without excluding
        them understates every per-call figure.
        """
        return PageIterator(
            lambda query: self._request("GET", "/api/token-usage/", params=query),
            self._filters(filters),
        )

    def summary(
        self,
        group_by: str = "model",
        *,
        currency: str = "usd",
        **filters: Any,
    ) -> Dict[str, Any]:
        """Spend rolled up, biggest first. The "what did last month cost me".

        ``group_by`` is ``model``, ``conversation`` or ``day``; ``currency`` is
        ``usd`` or ``eur``. Takes every filter :meth:`list` does, and applies
        them identically — a summary can never cover rows the matching
        ``list()`` would not have shown.

        Returns the response as it arrives — ``{group_by, currency, results}``,
        where each result carries ``group``, ``calls``, ``rows``, the token
        counts and ``cost_usd``. Not paginated, so there is no iterator here.

        ``cost_eur`` is **absent, not zero**, on any row where no exchange rate
        was on file: a missing rate is an unknown, and a free month is a very
        different claim. ``cost_usd`` is always present and is the stored
        truth — the conversion happens at read time, so a corrected rate
        restates history rather than needing a backfill.
        """
        params = self._filters(filters)
        params["group_by"] = _params.check_choice(
            group_by, _params.USAGE_GROUP_BY, what="group_by"
        )
        params["currency"] = _params.check_choice(
            currency, _params.USAGE_CURRENCIES, what="currency"
        )
        return self._request("GET", "/api/token-usage/summary/", params=params)

    # -- internals ---------------------------------------------------------

    def _filters(self, filters: Dict[str, Any]) -> Dict[str, Any]:
        _params.check_choice(
            filters.get("cost_source"), _params.COST_SOURCES, what="cost_source"
        )
        # `rename={}` on purpose: this route's filter really is spelled
        # `environment`, and the `env` alias the conversation and feedback
        # routes use would be silently ignored here.
        return _params.build(
            filters, _params.USAGE_FILTERS, what="usage", rename={}
        )
