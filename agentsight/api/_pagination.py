"""Walking list endpoints without making the caller think about pages.

This backend answers list requests two different ways. Most routes return a
seven-key envelope — ``count``, ``page_size``, ``total_pages``,
``current_page``, ``next``, ``previous``, ``results`` — which is DRF's four
plus three. A handful (``buttons/stats/``, ``actions/{pk}/logs/``, and every
view with ``pagination_class = None``) return a bare JSON array instead.

:class:`Page` flattens that difference so no call site has to know which kind
of endpoint it is talking to, and :class:`PageIterator` turns the paged form
into something you can just iterate.
"""

import logging
from typing import Any, Callable, Dict, Iterator, List, Optional

logger = logging.getLogger("agentsight")

#: The backend clamps ``page_size`` here (``ExtendedPageNumberPagination``),
#: so asking for more is silently ignored rather than honoured.
MAX_PAGE_SIZE = 100

#: Ask for the maximum by default: the fewer round trips spent walking a
#: result set, the better, and the caller never sees the page boundaries.
DEFAULT_PAGE_SIZE = 100

_ENVELOPE_KEYS = frozenset(
    {"count", "page_size", "total_pages", "current_page", "next", "previous", "results"}
)


class Page:
    """One page of results, plus whatever the envelope said about the whole set."""

    __slots__ = (
        "results",
        "count",
        "page_size",
        "total_pages",
        "current_page",
        "next",
        "previous",
        "extra",
    )

    def __init__(
        self,
        results: List[Any],
        *,
        count: Optional[int] = None,
        page_size: Optional[int] = None,
        total_pages: Optional[int] = None,
        current_page: Optional[int] = None,
        next: Optional[str] = None,
        previous: Optional[str] = None,
        extra: Optional[Dict[str, Any]] = None,
    ):
        self.results = results
        self.count = count if count is not None else len(results)
        self.page_size = page_size
        self.total_pages = total_pages
        self.current_page = current_page
        self.next = next
        self.previous = previous
        #: Per-endpoint additions to the envelope — ``counts`` on the feedback
        #: lists, for instance. Kept rather than dropped because it is the only
        #: place some aggregates are published.
        self.extra = extra or {}

    @classmethod
    def from_response(cls, body: Any) -> "Page":
        if isinstance(body, list):
            return cls(body)
        if not isinstance(body, dict):
            return cls([] if body is None else [body])

        results = body.get("results")
        if results is None:
            # Not a list envelope at all — a single object answered where a
            # page was expected. Treat it as a page of one rather than losing it.
            return cls([body])

        return cls(
            results,
            count=body.get("count"),
            page_size=body.get("page_size"),
            total_pages=body.get("total_pages"),
            current_page=body.get("current_page"),
            next=body.get("next"),
            previous=body.get("previous"),
            extra={k: v for k, v in body.items() if k not in _ENVELOPE_KEYS},
        )

    def __iter__(self) -> Iterator[Any]:
        return iter(self.results)

    def __len__(self) -> int:
        return len(self.results)

    def __getitem__(self, index):
        return self.results[index]

    def __repr__(self) -> str:
        return (
            f"<Page {len(self.results)} of {self.count}"
            f"{f', page {self.current_page}/{self.total_pages}' if self.current_page else ''}>"
        )


class PageIterator:
    """Lazily walks every page of a list endpoint.

    Iterating yields individual records, fetching the next page only when the
    current one runs out. Nothing is requested until iteration starts.

    Paging is driven by incrementing ``?page=`` rather than following the
    envelope's absolute ``next`` URL, so every request goes through the same
    transport — same auth, same retry policy, same base URL — instead of a
    URL the server built from whatever host header it saw.

    ``?paginate=false`` is deliberately never used: it returns the entire
    result set as one unbounded array, which is the thing this class exists to
    avoid.
    """

    def __init__(
        self,
        fetch: Callable[[Dict[str, Any]], Any],
        params: Optional[Dict[str, Any]] = None,
        *,
        page_size: Optional[int] = None,
    ):
        self._fetch = fetch
        self._params = dict(params or {})
        self._page_size = _clamp(page_size)

    # -- iteration ---------------------------------------------------------

    def __iter__(self) -> Iterator[Any]:
        for page in self.pages():
            for record in page.results:
                yield record

    def pages(self) -> Iterator[Page]:
        """Every page in order, fetched on demand."""
        number = 1
        while True:
            page = self.page(number)
            yield page

            if not page.results:
                return
            if page.next is None:
                # A bare-array endpoint has no `next` either, which is
                # correct: there is exactly one page of it.
                return
            if page.total_pages is not None and number >= page.total_pages:
                return
            number += 1

    def page(self, number: int = 1) -> Page:
        """A single page, envelope intact — how you read ``count`` or ``extra``
        without walking the whole result set."""
        params = dict(self._params)
        params["page"] = number
        params["page_size"] = self._page_size
        return Page.from_response(self._fetch(params))

    # -- conveniences ------------------------------------------------------

    def first(self) -> Optional[Any]:
        """The first record, or ``None``. Fetches one page at most."""
        for record in self:
            return record
        return None

    def count(self) -> int:
        """How many records match, without fetching them all."""
        return self.page(1).count

    def __repr__(self) -> str:
        return f"<PageIterator {self._params}>"


def _clamp(page_size: Optional[int]) -> int:
    if page_size is None:
        return DEFAULT_PAGE_SIZE
    if page_size > MAX_PAGE_SIZE:
        logger.warning(
            "page_size=%s exceeds the backend maximum of %s; using %s",
            page_size,
            MAX_PAGE_SIZE,
            MAX_PAGE_SIZE,
        )
        return MAX_PAGE_SIZE
    return max(1, page_size)
