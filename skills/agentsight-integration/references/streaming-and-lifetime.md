# Streaming and turn lifetime

The part of the integration most likely to be silently wrong. A `with` block
ends when the function returns; **a unit of work often doesn't.** A handler
that returns a streaming response has not finished answering — the framework
drains the body afterwards, and everything worth recording happens then.

Read this before touching any handler that streams, defers, queues, or hands
work to another thread. Then verify with the file exporter — the failure modes
here raise nothing and produce plausible-looking wrong data.

## Contents

- [wrap()](#wrap)
- [Record the answer inside the generator](#record-the-answer-inside-the-generator)
- [The decorator form defers for you](#the-decorator-form-defers-for-you)
- [Abandonment](#abandonment)
- [Futures and thread pools](#futures-and-thread-pools)
- [keep_open() — when there is nothing to bind to](#keep_open--when-there-is-nothing-to-bind-to)
- [The deadline](#the-deadline)
- [flush() vs shutdown(), and wiring shutdown](#flush-vs-shutdown-and-wiring-shutdown)

## wrap()

```python
with agentsight.conversation(payload.conversation_id):
    with agentsight.turn():
        agentsight.user_message(payload.text)
        return agentsight.wrap(StreamingResponse(answer(payload.text)))
```

`wrap()` hands the turn's lifetime to the object returned, so the turn ends
when the stream does.

**What goes wrong without it — nothing raises, the data is just wrong:** the
turn closes at `return` with a ~0.1 ms duration (the handshake, not the
answer) holding the question and no answer; the `agent_message()` recorded
later inside the generator finds no active turn and opens an **orphan
half-exchange** of its own in a client-facing transcript. Latency charts read
as instant. This is the symptom to check for in verification: near-zero turn
durations plus orphan turns.

What `wrap()` accepts — it is not only a streaming feature, it is the answer
to *any* block that ends before its work does:

| Handed | Turn ends when |
|---|---|
| a response object with a `body_iterator` (FastAPI/Starlette) | the body is drained |
| a sync/async generator, or any iterator | iteration finishes |
| an `asyncio.Task`/`Future`, or `concurrent.futures.Future` | the future completes |
| any awaitable | the await returns |
| anything else | untouched — the deadline closes the turn |

A future comes back as **the same object** (only a completion callback added);
an awaitable comes back **wrapped**, so `await` what `wrap()` returned. With
nothing to bind to, or no turn active, it returns the object unchanged and
never raises — there is no handler shape where adding it makes things worse.

## Record the answer inside the generator

The assembled answer is only known when the stream finishes, so
`agent_message()` belongs on the generator's **last line**:

```python
async def answer(text: str):
    collected = []
    async for token in agent.stream(text):
        collected.append(token)
        yield f"data: {token}\n\n"
    agentsight.agent_message("".join(collected))
```

It lands on the right turn even though the framework resumes the generator
long after the handler returned — `wrap()` re-attaches the conversation and
turn around **each step** of the iteration. Outside the generator, in whatever
drained the response, no turn is active and the message opens a fresh one:
that is the orphan exchange. A consumer that stops early never reaches the
last line, which is exactly right — there was no complete answer to record.

## The decorator form defers for you

```python
@agentsight.turn(id_from="conversation_id")
async def chat(conversation_id: str, text: str):
    agentsight.user_message(text)
    return StreamingResponse(answer(text))     # no wrap() needed
```

The decorator sees the return value and hands the turn over itself when it is
a streaming response, generator, or future. The list is deliberately short —
a returned list or dict means the handler finished. The `with` form cannot
see the return value at all; that is the whole reason `wrap()` exists.

## Abandonment

A consumer walking away mid-answer is neither a failure nor an exchange. The
turn is recorded as **abandoned**: it never appears in the transcript as a
half-exchange, and the tokens it burned still show in usage. A client
disconnecting while the framework drains the response is covered
automatically. An app that notices the disconnect itself and returns cleanly
must say so — from the SDK's side a normal return is indistinguishable from
success:

```python
if await request.is_disconnected():
    agentsight.abandon_turn()
    return
```

## Futures and thread pools

```python
with agentsight.turn() as exchange:
    agentsight.user_message(text)
    return agentsight.wrap(pool.submit(answer, text))
```

A future that raises records the turn as an error; a cancelled future records
it as abandoned. **A worker thread has no scope of its own**: a module-level
`agentsight.agent_message()` inside the pooled function is dropped — record
the answer where the result is, or call it on the scope object
(`exchange.agent_message(...)`), which writes to that turn from any thread.

## keep_open() — when there is nothing to bind to

A websocket exchange finished by a later callback; a queued job whose reply
arrives on another channel. No returned object carries the lifetime, so take
the turn out of the block's hands and end it yourself:

```python
with agentsight.conversation(conversation_id):
    with agentsight.turn() as exchange:
        agentsight.user_message(text)
        exchange.keep_open()
        enqueue_reply(text, on_done=lambda reply: finish(exchange, reply))

def finish(exchange, reply):
    exchange.agent_message(reply)
    exchange.end(complete=True)
```

`exchange.end(complete=False)` is the same call for a reply that never came or
came back an error — the exchange stays out of the transcript, the work stays
on the record.

**Hold the scope and use it.** Once the block has exited, the kept-open turn
is no longer the *active* one, so module-level `agent_message()` /
`end_turn()` in the callback target whichever turn is active there — usually
none, and the message opens an orphan. `TurnScope.user_message()`,
`.agent_message()`, `.end()` exist for exactly this callback. Use module-level
`end_turn()` only where the finishing code still runs inside the block that
opened the turn.

## The deadline

Every turn whose lifetime was handed off (`wrap()` or `keep_open()`) gets a
deadline — `init(turn_timeout_ms=…)`, **five minutes by default**, `0`
disables. On expiry the turn is closed and recorded as incomplete, with a
warning on the `agentsight` logger. A plain `with`-block turn is unaffected —
it ends when the block ends. If the app legitimately holds exchanges open
longer (a human-in-the-loop queue), raise the timeout rather than letting real
exchanges expire.

## flush() vs shutdown(), and wiring shutdown

Spans are batched; at any moment a few seconds of recorded work is in memory.
An orderly exit flushes automatically. **SIGTERM — how every container,
orchestrator and process manager stops an app — does not.** The SDK
deliberately installs no signal handler (a library fighting the app for one
loses), so this is the one thing that needs the developer's code — and a
Tier 3 question when no hook exists: "may I add it?"

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    agentsight.init()
    yield
    agentsight.shutdown()
```

- No lifespan owner? Handle the signal:
  `signal.signal(signal.SIGTERM, lambda s, f: (agentsight.shutdown(), sys.exit(0)))`
  (as a proper function; call `shutdown()` then exit).
- On Celery, the hook is `worker_shutdown`.
- `shutdown()` first ends the handed-off turns (marked incomplete — a stream
  in flight goes out labelled rather than lost), then flushes. A `with`-block
  turn still open in another live thread is not ended for you: its turn span
  is lost, though the work recorded inside it is still delivered.
- **Short-lived processes** (serverless handlers, scripts): `agentsight.flush()`
  does the job without tearing the SDK down. It delivers everything **whose
  turn has ended** — spans inside an open turn deliberately wait (a turn and
  its work travel together), so end the turn first, then flush.

Ship checklist (mirror of the docs' own): `shutdown()` wired into the host's
shutdown path · an environment chosen per deployment · `export_interval_ms`
sized to worker count · `AGENTSIGHT_FILE_EXPORTER` unset in production.
