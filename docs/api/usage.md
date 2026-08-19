---
outline: deep
---

<CopyMarkdownButton />

# Usage

`ags.usage` answers **what your models cost**, which is the question the
tracking side spends every LLM call collecting the inputs for. Read-only: rows
are written from the token counts each provider reports, and there is no way to
create one here.

```python
ags.usage.summary(group_by="model")
```

```json
{
  "group_by": "model",
  "currency": "USD",
  "results": [
    { "group": "gpt-4o-mini-2024-07-18", "calls": 2591, "rows": 2591,
      "prompt_tokens": 207360, "completion_tokens": 116585,
      "cache_read_tokens": 103560, "cache_write_tokens": 0,
      "embedding_tokens": 0, "total_tokens": 427505,
      "cost_usd": 0.108822 },
    { "group": "gpt-4o", "calls": 1, "rows": 1,
      "prompt_tokens": 310, "completion_tokens": 74,
      "cache_read_tokens": 0, "cache_write_tokens": 0,
      "embedding_tokens": 0, "total_tokens": 384, "cost_usd": 0.001515 }
  ]
}
```

## The rollup

`summary()` is the "what did last month cost me" call. Biggest first, and
grouped three ways:

```python
ags.usage.summary("model")
ags.usage.summary("conversation")
ags.usage.summary("day", currency="eur")
```

| Parameter | Type | Default |
|---|---|---|
| `group_by` | `str` | `"model"` |
| `currency` | `str` | `"usd"` |

`group_by` is `model`, `conversation` or `day`; `currency` is `usd` or `eur`.
Anything else is rejected before the request is made.

It takes every filter `list()` does and applies them identically, so a summary
can never cover rows the matching `list()` would not have shown:

```python
ags.usage.summary(
    "day",
    environment="production",
    started_at_after=datetime(2026, 8, 1),
)
```

It is not paginated — a rollup is already aggregated, so there is no iterator
here.

## Cost is priced on our side

**The SDK computes no cost and sends none.** It reports token counts, the
resolved model id and the timestamp, which is everything cost is a function of.

That is worth more than it sounds. Rates change and published rates are
sometimes wrong; pricing server-side means every customer is on one rate table
rather than on whichever one their pinned release shipped with, and a rate that
turns out to have been wrong can be **restated across history** instead of
staying frozen at whatever the SDK knew on the day you deployed it.

`cost_source` on every row says where its figure came from:

| Value | Meaning |
|---|---|
| `backend` | priced server-side. The number of record, and what you should expect |
| `unpriced` | no rate matched this model, so nothing was booked |
| `reported` | a figure the client sent itself, kept rather than booked as zero |

**`unpriced` is not free.** It reads as "we do not know", and it is recoverable:
the token counts are exact, so the row is restated the day a rate for that model
exists.

```python
ags.usage.list(cost_source="unpriced")
```

`reported` appears only on historical rows and on data from clients that send
their own figures. This SDK no longer produces any.

:::warning `cost_eur` is absent, not zero
Where no exchange rate was on file, the key is missing from the result
entirely — because a missing rate is an unknown, and a free month is a very
different claim. Read it with `result.get("cost_eur")` and handle `None` as
"not converted", never as nothing spent.

`cost_usd` is always present and is the stored truth. The conversion happens at
read time, which is what lets a corrected rate restate history rather than
needing a backfill.
:::

## The per-call rows

`list()` walks the individual records behind the rollup:

```python
for row in ags.usage.list(conversation_id="wa-3859"):
    print(row["model"], row["total_tokens"], row["cost_usd"])
```

One row per **turn and model** — not per LLM call. A turn's calls are
aggregated by the model that served them, because counts from two models are not
the same unit and a row summing them could never be priced. `calls` says how
many went into the row; a turn that used one model, which is almost all of them,
gets exactly one.

Each row carries the five billable token categories that are priced —
prompt, completion, embedding, cache read and cache write — alongside
`reasoning_tokens` and the audio counts, which are subsets of prompt and
completion and are already priced through them. Pricing those again would
double-count.

| Filter | Selects on |
|---|---|
| `model` | the resolved model id |
| `conversation` (pk), `conversation_id` (string) | one conversation's spend |
| `turn_id` | one exchange |
| `environment` | the environment slug |
| `cost_source` | `backend`, `unpriced` or `reported` |
| `incomplete` | turns that did not finish |
| `started_at_after`, `started_at_before` | when the spend happened |
| `ordering` | the sort |

:::warning This one wants `environment`, not `env`
The conversation and feedback filters accept both spellings. Here `env` is not a
filter at all, and an unrecognised filter is refused rather than ignored — so
you get an error rather than a silently wider result set.
:::

## Two fields that look alike and are not

**`incomplete` is about the turn, not the tokens.** It is true when the exchange
ended in an error, was abandoned mid-stream, hit its deadline or was cut off by
shutdown — `incomplete_reason` says which. The spend on such a turn was really
spent; what is missing is the rest of the exchange.

**`unreported_calls` is about the tokens.** It counts calls whose stream closed
without the provider ever reporting usage. Those contributed 0 to every token
column as an *unknown*, not as a zero, and their share of the cost is 0 for the
same reason. A row with `unreported_calls > 0` understates both, so any
per-call average including it reads low. It is on every row but cannot be
filtered server-side — select on it after reading.

This is also the one case `cost_source` will not warn you about: a streamed call
that closed without usage is priced from the zeros it contributed, so it books
`$0` under `backend`. Authoritative arithmetic on an incomplete input.

:::info Costs arrive as strings on `list()`, numbers on `summary()`
`cost_usd` and `cost_usd_reported` come back from `list()` as strings —
`"0.00005610"` — because the stored decimal is kept exact rather than rounded
through a float. The same field on `summary()` is a number, because that one is
computed. Summing across `list()` means converting first, and `Decimal` is the
conversion that does not throw away the precision the string was preserving.
:::

## Next

- [Tokens & Cost](/tracking/tokens-and-cost) — how these rows get recorded, and
  what happens when a model cannot be named
- [Conversations](./conversations.md) — the conversation a `conversation` group
  points at
- [Spans](./spans.md) — the individual LLM calls a usage row aggregates
