"""A deadline for turns whose lifetime was handed to something else.

``turn.wrap()`` gives the span's lifetime to an iterator, a future or a task.
That is correct right up until nothing ever ends: a consumer that takes two
chunks from a generator and then holds it forever leaves the turn open, its
buffered child spans held in memory, and the exchange never reaches the
dashboard. Nothing raises — it just silently never arrives, which is the worst
failure mode available.

So every deferred turn gets a deadline. When it expires the turn is finished as
**incomplete** with reason ``deadline`` and exported that way: ingest keeps it
out of the transcript, but the tokens a half-drained stream burned stay on the
books, and the memory it was holding is released.

The same logic is why :func:`shutdown` *fires* every pending deadline instead
of discarding it. A span that never ends can never be exported, so clearing
the heap at process exit would silently lose every turn still in flight —
those fire early with the cause ``False`` ("not expired, draining") and their
turns go out with reason ``shutdown``.

One thread serves every deadline. A ``threading.Timer`` per turn would be
correct and would also mean one OS thread per in-flight stream, which on a busy
server is thousands.
"""

import heapq
import itertools
import logging
import threading
from typing import Any, Callable, List, Optional, Tuple

#: 5 minutes. Long enough that a slow LLM streaming a long answer is never cut
#: off, short enough that a leak is bounded.
DEFAULT_TIMEOUT_MS = 300_000

#: How long shutdown() will wait for a callback that is already running. This
#: is an atexit path, so the ceiling is what stops one stuck turn from holding
#: the whole process open.
_SHUTDOWN_WAIT_SECONDS = 5.0

logger = logging.getLogger("agentsight")


class _Watchdog:
    def __init__(self):
        self._lock = threading.Lock()
        self._wake = threading.Condition(self._lock)
        self._heap: List[Tuple[float, int, Any]] = []
        self._cancelled = set()
        self._counter = itertools.count()
        self._thread: Optional[threading.Thread] = None
        #: True while the worker is invoking a callback outside the lock.
        #: shutdown() waits on it so it cannot return while a deadline is
        #: mid-fire — core.shutdown() would tear the export pipeline down
        #: under that callback's feet and the span it ends would be lost.
        self._firing = False

    def arm(self, delay_seconds: float, callback: Callable[[bool], None]) -> Optional[int]:
        """Schedule ``callback``. Returns a handle for :meth:`cancel`.

        The callback receives one argument: ``True`` when its deadline
        actually expired, ``False`` when it is being fired early because the
        watchdog is draining and would otherwise never fire it at all.
        """
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
        self._thread = threading.Thread(
            target=self._run, name="agentsight-watchdog", daemon=True
        )
        self._thread.start()

    def _run(self) -> None:
        while True:
            with self._wake:
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
                self._firing = True

            # Outside the lock: the callback finishes a span, which reaches the
            # exporter, and holding the watchdog lock across that would let a
            # slow export stall every other deadline.
            try:
                callback(True)
            except Exception:
                pass
            finally:
                with self._wake:
                    self._firing = False
                    self._wake.notify_all()

    def shutdown(self) -> None:
        """Fire every pending deadline now. The watchdog stays usable after.

        Clearing the heap here would leave each armer's span open forever,
        and a span that never ends can never be exported — the work a turn
        did before the process exited would be silently lost. Firing early
        instead lets every open deferred turn end while the export pipeline
        downstream of us is still alive; core.shutdown() flushes it right
        after this returns.

        Two deliberate properties:

        * **No decommissioning.** There is no "stopped" state — a flag would
          have to be checked by arm() and reset somewhere, and the window
          between the two is where deadlines get orphaned (armed onto a heap
          no thread serves). The worker is a daemon thread that already dies
          when idle and dies with the process; an arm() after shutdown is
          simply new business, which is also what makes re-init() work.
        * **In-flight callbacks are awaited, but not forever.** The worker may
          have popped a deadline and be mid-callback outside the lock;
          returning before it finishes would let core.shutdown() kill the
          provider under a span that is still being ended. The wait releases
          the lock, so the callback's own cancel() call cannot deadlock
          against it — but it is bounded, because this runs from ``atexit``
          and a callback that hangs would hang the process on the way out.
          Giving up costs one turn's span; not giving up costs the exit.

        Callbacks fire outside the lock, same as in _run and for a stronger
        reason: finishing a turn cancels its own deadline, which re-enters
        cancel() on this watchdog — under the lock that is a deadlock.
        """
        with self._wake:
            pending: List[Callable[[bool], None]] = []
            while self._heap:
                _deadline, handle, callback = heapq.heappop(self._heap)
                if handle not in self._cancelled:
                    pending.append(callback)
            self._cancelled.clear()
            deadline = _monotonic() + _SHUTDOWN_WAIT_SECONDS
            while self._firing:
                remaining = deadline - _monotonic()
                if remaining <= 0:
                    logger.debug(
                        "watchdog: a turn callback is still running after %ss; "
                        "continuing shutdown without it",
                        _SHUTDOWN_WAIT_SECONDS,
                    )
                    break
                self._wake.wait(timeout=min(0.1, remaining))
            self._wake.notify_all()
        for callback in pending:
            try:
                callback(False)
            except Exception:
                pass


def _monotonic() -> float:
    import time

    return time.monotonic()


_watchdog = _Watchdog()


def arm(delay_seconds: float, callback: Callable[[bool], None]) -> Optional[int]:
    return _watchdog.arm(delay_seconds, callback)


def cancel(handle: Optional[int]) -> None:
    _watchdog.cancel(handle)


def shutdown() -> None:
    _watchdog.shutdown()
