---
outline: deep
---

<CopyMarkdownButton />

# Pagination

Every `list()` returns a **lazy iterator, not a list**. Iterating it walks the
whole result set, fetching each page only when the previous one runs out, so the
common case needs no paging code at all:

```python
for conversation in ags.conversations.list(is_marked=True):
    print(conversation["conversation_id"])
```

Nothing is requested until iteration starts. Building the iterator is free —
`ags.conversations.list()` on its own makes no request, which is why filters can
be validated the moment you pass them rather than a round trip later.

## Reading a count without reading the rows

`.count()` asks for one page and reads the total off it:

```python
ags.conversations.list(has_feedback=True).count()
```

`.first()` is the same trade in the other direction — the first record, or
`None`, fetching one page at most:

```python
newest = ags.spans.list(status="error").first()
```

## When you want the page itself

`.page(n)` returns a `Page`: the records, plus everything the response said
about the whole result set.

```python
page = ags.conversations.list(environment="production").page()

page.count          # how many match the filters
page.total_pages
len(page)           # how many are on this page
for row in page:
    ...
```

| Attribute | What it holds |
|---|---|
| `results` | the records on this page, as a list |
| `count` | how many records match in total |
| `page_size` | how many were asked for |
| `total_pages` | how many pages that makes |
| `current_page` | which one this is |
| `next`, `previous` | present when there is another page in that direction |
| `extra` | anything a particular endpoint publishes alongside the rows |

A `Page` iterates, indexes and slices like the list of records it wraps, so
`page[0]` and `for row in page` work as you would expect. Both types are
importable for annotations — `from agentsight.api import Page, PageIterator`.

`.pages()` gives you the pages in order rather than the records, for when the
work is naturally per batch:

```python
for page in ags.usage.list().pages():
    write_rows(page.results)
```

## What `extra` is for

Most endpoints publish nothing beyond the rows and `extra` is empty. Feedback is
the one that does:

```python
ags.feedbacks.page().extra
# {'counts': {'all': 3}}
```

It is kept because the response carries it, not because it says anything
`count` does not.

:::info Tickets are not on this surface
Earlier versions of this client documented ticket aggregates here — `tickets`,
`open_tickets` and the per-status tallies. Tickets are internal workflow state
and are not available to an API key at all, so `counts` now holds `all` and
nothing else, feedback payloads carry no nested ticket object, and the ticket
filters are refused rather than ignored. That is a boundary, not a gap.
:::

## The page size

Pages are fetched a hundred records at a time, which is the largest the server
will serve. **It is not a caller parameter** — the iterator owns paging, and
there is no `page_size` argument on any `list()`. Passing one is rejected the
same way any unrecognised filter is.

That is deliberate rather than restrictive. Fewer round trips is the right
default for walking a result set, the page boundaries are invisible to anyone
iterating, and the one thing a smaller page would buy — a cheaper `.count()` —
is already a single request.

## Not everything is paginated

Three calls return their whole answer at once, because the shape they return is
not a page:

- `ags.actions.logs(id)` — a plain list of invocations.
- `ags.usage.summary(...)` — a rollup, already aggregated.
- `ags.spans.trace(id)` — one trace as a tree.

They return the response directly, with no iterator to walk.

## Next

- [Conversations](./conversations.md) — the filters worth combining with a count
- [Usage](./usage.md) — where `summary()` replaces paging entirely
- [Errors and retries](./errors.md) — what a rejected filter raises, and when
