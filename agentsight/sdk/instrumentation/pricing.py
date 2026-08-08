"""Model prices, and the cost arithmetic that depends on them.

Separated from the capture code because prices change on a different schedule
than instrumentation does — this file is expected to be edited often, the rest
of the package rarely.

**Rates verified 2026-08-07** against the providers' published rate cards
(``developers.openai.com/api/docs/pricing`` and
``platform.claude.com/docs/en/about-claude/pricing``). A model absent from
those pages is absent from this table: an unknown model costs ``None``, which
is recoverable from the span archive, while a guessed rate is a wrong number
nobody can tell is wrong.

Two dated items to carry forward:

* **claude-sonnet-5 is on introductory pricing of $2/$10 through 2026-08-31**
  and reverts to $3/$15 on 2026-09-01. Update the entry on that date.
* The fully retired Claude 3 models (3.5 Sonnet, 3 Opus/Sonnet/Haiku) are no
  longer on the rate card, so they are deliberately unpriced. Anyone still
  calling them can supply a rate with :func:`register_price`.
"""

import logging
import threading
from typing import Dict, Optional, Tuple

logger = logging.getLogger("agentsight")


class Price:
    """USD per 1M tokens, plus the cache multipliers for one model family.

    Cache pricing is a *multiplier on the input rate*, not a flat rate, and it
    differs both between providers and within them:

    * Anthropic — explicit caching, uniform across the range. Reads are 0.1x
      input; **writes cost more than plain input** (1.25x at the 5-minute TTL,
      2x at 1 hour). A workload that writes cache without reading it back is
      more expensive than not caching at all, which is exactly the kind of
      thing this breakdown exists to make visible.
    * OpenAI — automatic caching, no write surcharge, but the read discount is
      **per family**: 0.1x on the GPT-5 range, 0.25x on GPT-4.1/o3/o4-mini,
      0.5x on GPT-4o and o1. A blanket 0.5x overcharges a GPT-5 cache read
      five-fold, so the multiplier travels with the model, not the vendor.
    """

    def __init__(self, input_: float, output: float, cache_read: float, cache_write: float):
        self.input = input_
        self.output = output
        self.cache_read = cache_read
        self.cache_write = cache_write


#: 5-minute cache writes. The 1-hour TTL is 2x, but the SDK cannot tell the
#: two apart from the usage block, and the shorter TTL is the default.
_ANTHROPIC = {"cache_read": 0.1, "cache_write": 1.25}

_OPENAI_TENTH = {"cache_read": 0.1, "cache_write": 0.0}
_OPENAI_QUARTER = {"cache_read": 0.25, "cache_write": 0.0}
_OPENAI_HALF = {"cache_read": 0.5, "cache_write": 0.0}

#: Embeddings have no output and no cache tier; models that predate prompt
#: caching have no cache tier either. Both multipliers are 0 and the whole
#: cost rides on ``input``.
_NO_CACHE = {"cache_read": 0.0, "cache_write": 0.0}

#: Keyed by model-id prefix so dated snapshots match their base model, and so
#: a more specific id wins over a less specific one — ``lookup_price`` takes
#: the longest matching prefix, which is what keeps ``gpt-4o-mini`` off the
#: ``gpt-4o`` rate and ``claude-opus-4-5`` off the ``claude-opus-4`` rate.
_PRICES: Dict[str, Price] = {
    # --- OpenAI: GPT-5 -----------------------------------------------------
    "gpt-5.6-sol": Price(5.00, 30.00, **_OPENAI_TENTH),
    "gpt-5.6-terra": Price(2.00, 12.00, **_OPENAI_TENTH),
    "gpt-5.6-luna": Price(0.20, 1.20, **_OPENAI_TENTH),
    "gpt-5.5-pro": Price(30.00, 180.00, **_NO_CACHE),
    "gpt-5.5": Price(5.00, 30.00, **_OPENAI_TENTH),
    "gpt-5.4-pro": Price(30.00, 180.00, **_NO_CACHE),
    "gpt-5.4-mini": Price(0.75, 4.50, **_OPENAI_TENTH),
    "gpt-5.4-nano": Price(0.20, 1.25, **_OPENAI_TENTH),
    "gpt-5.4": Price(2.50, 15.00, **_OPENAI_TENTH),
    "gpt-5.2-pro": Price(21.00, 168.00, **_NO_CACHE),
    "gpt-5.2": Price(1.75, 14.00, **_OPENAI_TENTH),
    "gpt-5.1": Price(1.25, 10.00, **_OPENAI_TENTH),
    "gpt-5-pro": Price(15.00, 120.00, **_NO_CACHE),
    "gpt-5-mini": Price(0.25, 2.00, **_OPENAI_TENTH),
    "gpt-5-nano": Price(0.05, 0.40, **_OPENAI_TENTH),
    "gpt-5": Price(1.25, 10.00, **_OPENAI_TENTH),
    # --- OpenAI: GPT-4.1 ---------------------------------------------------
    "gpt-4.1-nano": Price(0.10, 0.40, **_OPENAI_QUARTER),
    "gpt-4.1-mini": Price(0.40, 1.60, **_OPENAI_QUARTER),
    "gpt-4.1": Price(2.00, 8.00, **_OPENAI_QUARTER),
    # --- OpenAI: GPT-4o ----------------------------------------------------
    "gpt-4o-mini": Price(0.15, 0.60, **_OPENAI_HALF),
    # The May 2024 snapshot never got the price cut the alias did.
    "gpt-4o-2024-05-13": Price(5.00, 15.00, **_OPENAI_HALF),
    "gpt-4o": Price(2.50, 10.00, **_OPENAI_HALF),
    # --- OpenAI: reasoning -------------------------------------------------
    "o4-mini": Price(1.10, 4.40, **_OPENAI_QUARTER),
    "o3-pro": Price(20.00, 80.00, **_NO_CACHE),
    "o3-mini": Price(1.10, 4.40, **_OPENAI_HALF),
    "o3": Price(2.00, 8.00, **_OPENAI_QUARTER),
    "o1-pro": Price(150.00, 600.00, **_NO_CACHE),
    # Retired and off the current rate card; kept at its last published rate
    # so history stays priced rather than silently becoming None.
    "o1-mini": Price(1.10, 4.40, **_OPENAI_HALF),
    "o1": Price(15.00, 60.00, **_OPENAI_HALF),
    # --- OpenAI: pre-caching generations -----------------------------------
    "gpt-4-turbo": Price(10.00, 30.00, **_NO_CACHE),
    "gpt-3.5-turbo-1106": Price(1.00, 2.00, **_NO_CACHE),
    "gpt-3.5-turbo": Price(0.50, 1.50, **_NO_CACHE),
    # --- OpenAI embeddings -------------------------------------------------
    "text-embedding-3-small": Price(0.02, 0.0, **_NO_CACHE),
    "text-embedding-3-large": Price(0.13, 0.0, **_NO_CACHE),
    "text-embedding-ada-002": Price(0.10, 0.0, **_NO_CACHE),
    # --- Anthropic ---------------------------------------------------------
    "claude-fable-5": Price(10.00, 50.00, **_ANTHROPIC),
    "claude-mythos-5": Price(10.00, 50.00, **_ANTHROPIC),
    "claude-opus-5": Price(5.00, 25.00, **_ANTHROPIC),
    "claude-opus-4-8": Price(5.00, 25.00, **_ANTHROPIC),
    "claude-opus-4-7": Price(5.00, 25.00, **_ANTHROPIC),
    "claude-opus-4-6": Price(5.00, 25.00, **_ANTHROPIC),
    "claude-opus-4-5": Price(5.00, 25.00, **_ANTHROPIC),
    "claude-opus-4-1": Price(15.00, 75.00, **_ANTHROPIC),
    "claude-opus-4": Price(15.00, 75.00, **_ANTHROPIC),
    # Introductory rate, expires 2026-08-31 -> 3.00 / 15.00. See module header.
    "claude-sonnet-5": Price(2.00, 10.00, **_ANTHROPIC),
    "claude-sonnet-4-6": Price(3.00, 15.00, **_ANTHROPIC),
    "claude-sonnet-4-5": Price(3.00, 15.00, **_ANTHROPIC),
    "claude-sonnet-4": Price(3.00, 15.00, **_ANTHROPIC),
    "claude-haiku-4-5": Price(1.00, 5.00, **_ANTHROPIC),
    "claude-3-5-haiku": Price(0.80, 4.00, **_ANTHROPIC),
}

#: Prefixes longest-first. Recomputed on every table change rather than sorted
#: on every LLM call — this ran inside the hot path of each request.
_PREFIXES: Tuple[str, ...] = ()
_lock = threading.Lock()

#: Model ids already reported as unpriced, so the log says it once instead of
#: once per call.
_unpriced: set = set()


def _reindex() -> None:
    global _PREFIXES
    _PREFIXES = tuple(sorted(_PRICES, key=len, reverse=True))


_reindex()


def register_price(
    model_prefix: str,
    input_: float,
    output: float,
    *,
    cache_read: float = 0.0,
    cache_write: float = 0.0,
) -> None:
    """Teach the SDK a model it does not know.

    Exists so an unknown model is a *configuration* problem the user can fix in
    one line, rather than a missing number they have to wait for a release to
    get. Fine-tuned model ids in particular will never be in the bundled table,
    and neither will a rate you negotiated.

    ``cache_read`` and ``cache_write`` are multipliers on ``input_``, not
    absolute rates — 0.1 means a cache read costs a tenth of an input token.
    """
    with _lock:
        _PRICES[model_prefix] = Price(input_, output, cache_read, cache_write)
        _reindex()
        _unpriced.discard(model_prefix)


def lookup_price(model: Optional[str]) -> Optional[Price]:
    if not model:
        return None
    # Longest prefix wins, so "gpt-4o-mini" doesn't match the "gpt-4o" entry.
    for known in _PREFIXES:
        if model.startswith(known):
            return _PRICES[known]
    return None


def estimate_cost(
    model: Optional[str],
    input_tokens: int = 0,
    output_tokens: int = 0,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
    embedding_tokens: int = 0,
) -> Optional[float]:
    """USD for one call, or None for an unknown model.

    Reasoning and audio tokens are deliberately absent: they are subsets of
    input/output and are already priced through those. Adding them here would
    double-count. An unknown model yields ``None`` rather than a wrong number —
    a missing cost is recoverable from the raw span archive, a silently wrong
    one is not.
    """
    price = lookup_price(model)
    if price is None:
        _note_unpriced(model)
        return None
    total = (
        input_tokens * price.input
        + output_tokens * price.output
        + cache_read_tokens * price.input * price.cache_read
        + cache_write_tokens * price.input * price.cache_write
        # Embedding models bill one rate for everything they consume.
        + embedding_tokens * price.input
    )
    return round(total / 1_000_000, 8)


def _note_unpriced(model: Optional[str]) -> None:
    """Say once, per model, that its cost will read as nothing.

    Without this the failure is invisible: the tokens are recorded correctly,
    the cost column is simply empty, and nobody finds out until someone asks
    what last month cost.
    """
    if not model:
        return
    with _lock:
        if model in _unpriced:
            return
        _unpriced.add(model)
    logger.debug(
        "AgentSight: no price for model %r, so its cost is not being "
        "computed. agentsight.register_price(%r, input_per_1m, "
        "output_per_1m) fixes it.",
        model,
        model,
    )


def _reset_for_tests() -> None:
    with _lock:
        _unpriced.clear()
