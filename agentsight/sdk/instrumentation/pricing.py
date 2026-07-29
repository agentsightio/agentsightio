"""Model prices, and the cost arithmetic that depends on them.

Separated from the capture code because prices change on a different schedule
than instrumentation does — this file is expected to be edited often, the rest
of the package rarely.
"""

from typing import Dict, Optional


class Price:
    """USD per 1M tokens, plus the cache multipliers for one provider family.

    Cache pricing is a *multiplier on the input rate*, not a flat rate, and it
    differs sharply between providers:

    * Anthropic — explicit caching. Reads are ~0.1x input; **writes cost more
      than plain input** (1.25x at the 5-minute TTL, 2x at 1 hour). A workload
      that writes cache without reading it back is more expensive than not
      caching at all, which is exactly the kind of thing this breakdown exists
      to make visible.
    * OpenAI — automatic caching. Reads are ~0.5x input and there is no write
      surcharge at all, so ``cache_write`` is 0.
    """

    def __init__(self, input_: float, output: float, cache_read: float, cache_write: float):
        self.input = input_
        self.output = output
        self.cache_read = cache_read
        self.cache_write = cache_write


_ANTHROPIC_CACHE = {"cache_read": 0.1, "cache_write": 1.25}
_OPENAI_CACHE = {"cache_read": 0.5, "cache_write": 0.0}

#: Embeddings have no output and no cache tier, so both multipliers are 0 and
#: the whole cost rides on ``input``.
_NO_CACHE = {"cache_read": 0.0, "cache_write": 0.0}

#: Keyed by model-id prefix so dated snapshots match their base model.
_PRICES: Dict[str, Price] = {
    # --- OpenAI chat -------------------------------------------------------
    "gpt-4o-mini": Price(0.15, 0.60, **_OPENAI_CACHE),
    "gpt-4o": Price(2.50, 10.00, **_OPENAI_CACHE),
    "gpt-4.1-nano": Price(0.10, 0.40, **_OPENAI_CACHE),
    "gpt-4.1-mini": Price(0.40, 1.60, **_OPENAI_CACHE),
    "gpt-4.1": Price(2.00, 8.00, **_OPENAI_CACHE),
    "o4-mini": Price(1.10, 4.40, **_OPENAI_CACHE),
    "o3-mini": Price(1.10, 4.40, **_OPENAI_CACHE),
    "o3": Price(2.00, 8.00, **_OPENAI_CACHE),
    "o1-mini": Price(1.10, 4.40, **_OPENAI_CACHE),
    "o1": Price(15.00, 60.00, **_OPENAI_CACHE),
    # --- OpenAI embeddings -------------------------------------------------
    "text-embedding-3-small": Price(0.02, 0.0, **_NO_CACHE),
    "text-embedding-3-large": Price(0.13, 0.0, **_NO_CACHE),
    "text-embedding-ada-002": Price(0.10, 0.0, **_NO_CACHE),
    # --- Anthropic ---------------------------------------------------------
    "claude-opus-5": Price(5.00, 25.00, **_ANTHROPIC_CACHE),
    "claude-sonnet-5": Price(3.00, 15.00, **_ANTHROPIC_CACHE),
    "claude-haiku-4-5": Price(1.00, 5.00, **_ANTHROPIC_CACHE),
    "claude-opus-4-8": Price(5.00, 25.00, **_ANTHROPIC_CACHE),
    "claude-opus-4-7": Price(5.00, 25.00, **_ANTHROPIC_CACHE),
    "claude-opus-4-6": Price(5.00, 25.00, **_ANTHROPIC_CACHE),
    "claude-sonnet-4-6": Price(3.00, 15.00, **_ANTHROPIC_CACHE),
    "claude-fable-5": Price(10.00, 50.00, **_ANTHROPIC_CACHE),
}


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
    get. Fine-tuned model ids in particular will never be in the bundled table.
    """
    _PRICES[model_prefix] = Price(input_, output, cache_read, cache_write)


def lookup_price(model: Optional[str]) -> Optional[Price]:
    if not model:
        return None
    # Longest prefix wins, so "gpt-4o-mini" doesn't match the "gpt-4o" entry.
    for known in sorted(_PRICES, key=len, reverse=True):
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
