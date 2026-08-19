---
outline: deep
---

<CopyMarkdownButton />

# Deployment & limitations

Everything here is a decision we made on purpose, and each one is fine as long as
you know about it before you meet it. One of them needs a few lines of code from
you; the rest are things to recognise if you see them.

## Graceful shutdown

**This is the one that needs code.** Spans are batched, so at any moment a few
seconds of recorded work is still in memory. An orderly exit flushes it
automatically. `SIGTERM` — how every container, orchestrator and process manager
stops your app — does not.

Wire `agentsight.shutdown()` into whatever your host already calls on the way
out:

```python
from contextlib import asynccontextmanager

from fastapi import FastAPI

import agentsight


@asynccontextmanager
async def lifespan(app: FastAPI):
    agentsight.init()
    yield
    agentsight.shutdown()


app = FastAPI(lifespan=lifespan)
```

If nothing in your stack owns shutdown, handle the signal yourself:

```python
import signal

import agentsight

agentsight.init()


def _shutdown(signum, frame):
    agentsight.shutdown()
    raise SystemExit(0)


signal.signal(signal.SIGTERM, _shutdown)
```

On Celery, `worker_shutdown` is the hook.

:::info Why the SDK doesn't do this for you
Installing a signal handler from a library means fighting the application for it —
whoever registers last wins, and it is your process. So the SDK deliberately
installs none, and calling `shutdown()` is yours to place.
:::

`shutdown()` closes the turns whose lifetime was handed off — `wrap()` and
`keep_open()` — marks them incomplete, and flushes what is waiting. A `with`-block
turn still open in another live thread is not ended for you: its turn span is
lost, though the work recorded inside it is still delivered.

### Short-lived processes

In a serverless handler or a script that exits on its own, `flush()` is the call
you want:

```python
agentsight.flush()
```

It delivers everything **whose turn has ended**. Spans inside a turn that is still
open deliberately wait for it — a turn and the work beneath it travel together —
so end the turn first, then flush.

## The flush budget is shared

Spans leave your process in batches. Spans recorded inside a turn are held in
memory until that turn ends — a turn and the work beneath it travel together —
and once released they join the export queue. On an interval set by
`export_interval_ms` (five seconds by default), everything waiting in that
queue goes out as one batch. So the interval is not "everything in memory every
five seconds": an open turn sends nothing, and a finished one is on the wire
within one interval of ending.

The thing to know when you scale out: sending is a **per-process** rate spent
against a **per-agent** allowance. Every worker in your deployment draws on the
same budget, so what matters is not the interval but the interval divided across
your worker count. One process sending every five seconds is nothing. Forty
processes sending every five seconds is forty times that, against the same
allowance.

So: raise `export_interval_ms` as your worker count grows, and lower it when the
count is small and you want the dashboard to keep up. Nothing in the SDK reads its
own data back, so the only cost of waiting longer is freshness.

You will be told if it is not keeping up. The SDK warns — once a minute, on the
`agentsight` logger — before the queue is full rather than after, and names the
three things that change the outcome: `max_queue_size`, `export_interval_ms`, and
whether the API is reachable at all.

## Limitations

Known gaps, each one accepted rather than overlooked.

**Data is kept indefinitely.** There is no retention window today. One is under
consideration; if it is adopted it will be stated in
[What the SDK sends](/getting-started/what-the-sdk-sends), and before it applies.

**A very large single exchange may not be shown completely.** One turn that
produces far more work than a typical exchange can outgrow a single transmission,
and the dashboard may then account for less of it than was actually sent. Normal
exchanges are nowhere near this.

**`with_streaming_response` produces no span.** Ordinary streaming
(`stream=True`) **is** fully recorded, token usage included — this limitation is
not about streaming in general. It is about one specific wrapper on the OpenAI
and Anthropic clients, `with_streaming_response`, which hands you the raw HTTP
body to read yourself: until you read it there is genuinely nothing to record,
so the SDK stays out of it and the tokens spent on those calls are not captured.
Every other mode, including `with_raw_response`, is recorded.

**LangChain cache hits can report tokens nobody was billed for.** A cached
response still reports usage figures through the callback, and the handler cannot
tell that answer from a fresh one. Treat token counts as an upper bound if you
rely on LangChain's cache.

**A streamed call that reports no usage is marked, not billed as zero.** Some
providers end a stream without a usage event. Rather than record an authoritative
`0` — indistinguishable from a call that really was free — the SDK marks the call
as having reported nothing. Unknown spend reads as unknown.

**`@tool` costs roughly 100 microseconds per call.** Irrelevant against anything
that touches a network, and worth knowing if you decorate a function that returns
instantly and is called in a tight loop.

## Before you ship

- `agentsight.shutdown()` wired into your host's shutdown path
- An [environment](./environments.md) chosen for the deployment
- `export_interval_ms` sized to your worker count
- `AGENTSIGHT_FILE_EXPORTER` unset — with it set, nothing is transmitted
