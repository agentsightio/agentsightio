"""A deadline for turns whose lifetime was handed to something else.

``turn.wrap()`` gives the span's lifetime to an iterator, a future or a task.
That is correct right up until nothing ever ends: a consumer that takes two
chunks from a generator and then holds it forever leaves the turn open, its
buffered child spans held in memory, and the exchange never reaches the
dashboard. Nothing raises — it just silently never arrives, which is the worst
failure mode available.

So every deferred turn gets a deadline. When it expires the turn is finished as
**incomplete**, which per decision 11 means it is dropped in the SDK before
export, together with every tool and LLM span underneath it. A half-drained
stream is not an exchange, and the memory it was holding is released.

One thread serves every deadline. A ``threading.Timer`` per turn would be
correct and would also mean one OS thread per in-flight stream, which on a busy
server is thousands.
"""

import heapq
import itertools
import threading
from typing import Any, Callable, List, Optional, Tuple

#: 5 minutes. Long enough that a slow LLM streaming a long answer is never cut
#: off, short enough that a leak is bounded.
DEFAULT_TIMEOUT_MS = 300_000


class _Watchdog:
    def __init__(self):
        self._lock = threading.Lock()
        self._wake = threading.Condition(self._lock)
        self._heap: List[Tuple[float, int, Any]] = []
        self._cancelled = set()
        self._counter = itertools.count()
        self._thread: Optional[threading.Thread] = None
        self._stopping = False

    def arm(self, delay_seconds: float, callback: Callable[[], None]) -> Optional[int]:
        """Schedule ``callback``. Returns a handle for :meth:`cancel`."""
        if delay_seconds <= 0:
            return None
        deadline = _monotonic() + delay_seconds
        with self._wake:
            handle = next(self._counter)
            heapq.heappush(self._heap, (deadline, handle, callback))
            self._ensure_thread()
            self._wake.notify()
        return handle

    def cancel(self, handle: Optional[int]) -> None:
        if handle is None:
            return
        with self._wake:
            self._cancelled.add(handle)

    # -- internals ----------------------------------------------------------

    def _ensure_thread(self) -> None:
        """Started on first use, so an SDK that never streams costs no thread."""
        if self._thread is not None and self._thread.is_alive():
            return
        self._stopping = False
        self._thread = threading.Thread(
            target=self._run, name="agentsight-watchdog", daemon=True
        )
        self._thread.start()

    def _run(self) -> None:
        while True:
            with self._wake:
                if self._stopping:
                    return
                if not self._heap:
                    # Nothing pending: wait a little for work, then let the
                    # thread die rather than idle for the life of the process.
                    self._wake.wait(timeout=30.0)
                    if not self._heap:
                        self._thread = None
                        return
                    continue

                deadline, handle, callback = self._heap[0]
                remaining = deadline - _monotonic()
                if remaining > 0:
                    self._wake.wait(timeout=remaining)
                    continue

                heapq.heappop(self._heap)
                if handle in self._cancelled:
                    self._cancelled.discard(handle)
                    continue

            # Outside the lock: the callback finishes a span, which reaches the
            # exporter, and holding the watchdog lock across that would let a
            # slow export stall every other deadline.
            try:
                callback()
            except Exception:
                pass

    def shutdown(self) -> None:
        with self._wake:
            self._stopping = True
            self._heap.clear()
            self._cancelled.clear()
            self._wake.notify_all()


def _monotonic() -> float:
    import time

    return time.monotonic()


_watchdog = _Watchdog()


def arm(delay_seconds: float, callback: Callable[[], None]) -> Optional[int]:
    return _watchdog.arm(delay_seconds, callback)


def cancel(handle: Optional[int]) -> None:
    _watchdog.cancel(handle)


def shutdown() -> None:
    _watchdog.shutdown()
