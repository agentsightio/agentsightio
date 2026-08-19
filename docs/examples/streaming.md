---
outline: deep
---

<CopyMarkdownButton />

# Streaming and `wrap()`

[`examples/06_streaming.py`](https://github.com/agentsightio/agentsightio/blob/main/examples/06_streaming.py)
is the example to run before you ship a streaming endpoint. It demonstrates
[`wrap()`](/tracking/streaming) — the answer to the one place a naive
integration silently records wrong data — and shows the wrong version next to
the right one, because nothing raises to tell you which one you wrote.

```bash
python examples/06_streaming.py
```

Standard library only: FastAPI/Starlette responses are the usual case, but the
primitive is not about FastAPI — a Celery task or a queue consumer needs
exactly the same tool.

## The problem, then the fix

A `with` block ends when the function returns. A streaming handler has not
finished answering at its `return` — the framework drains the generator
afterwards. Close the turn at the `return` and you record ~0 ms latency and no
agent message: confidently wrong data, which is worse than none.

```python
def handler_without_wrap():
    with ags.turn("no-wrap"):
        ags.user_message("Where is my order?")
        return answer_tokens()   # the turn ends HERE, before a token is sent

def handler_with_wrap():
    with ags.turn("wrapped"):
        ags.user_message("Where is my order?")
        return ags.wrap(answer_tokens())   # the turn now ends when the stream does
```

The script runs both and prints them side by side — the duration gap between
the two turns is the whole point.

`wrap()` re-attaches the turn's scope around each step of the generator, so
the `agent_message()` call belongs *inside* the generator, on its last line:
made there, it lands on the right turn even though the framework resumes the
generator long after the handler returned. Made from the consumer after
draining, it would open a fresh turn instead — by then nothing is active, and
nothing would raise to say so.

## The consumer walks away

The third run drains only two tokens and closes the stream — a closed tab,
mid-answer. The generator never reaches its last line, which is exactly right:
there was no complete answer to record. The turn is recorded as abandoned —
never a half-exchange in the transcript, but the tokens it burned still count.

## No object to bind to at all

The last run is work finished by a later callback — a websocket reply, a queue
consumer. There is no response object to wrap, so the turn defers itself:

```python
with ags.turn("deferred") as deferred:
    ags.user_message("ping over a websocket")
    deferred.keep_open()

# ...later, when the callback arrives:
deferred.agent_message("pong")
deferred.end(complete=True)
```

The late calls go through the scope, not the module — out there the deferred
turn is no longer the active one, and `ags.agent_message()` would open a turn
of its own. If you never call `end()`, the watchdog closes the turn as
incomplete after `init(turn_timeout_ms=...)` — five minutes by default.

## What to look for in the output

Four turns in `examples/traces/06_streaming/`: the naive one with its
near-zero duration, the wrapped one with real answer latency and the agent
message on it, the walked-away one marked `INCOMPLETE(abandoned)`, and the
deferred one complete despite ending outside its `with` block.
