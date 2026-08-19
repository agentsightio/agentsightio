---
outline: deep
---

<CopyMarkdownButton />

# Streaming

A `with` block ends when the function returns. **A unit of work often doesn't.**
A handler that returns a streaming response has not finished answering — the
framework drains the body afterwards, and everything worth recording happens
then. This page is one call long, and it is required reading before you ship a
streaming endpoint.

```python
@app.post("/chat")
async def chat(payload: ChatRequest):
    with agentsight.conversation(payload.conversation_id):
        with agentsight.turn():
            agentsight.user_message(payload.text)
            body = answer(payload.text)
            return agentsight.wrap(
                StreamingResponse(body, media_type="text/event-stream")
            )
```

`wrap()` hands the turn's lifetime to the object you return, so the turn ends
when the stream does.

## What goes wrong without it

Nothing raises. You get data, and the data is wrong. The same handler, run twice
— once returning the generator directly, once through `wrap()`:

| Turn recorded | Duration | What it holds |
|---|---|---|
| the handler's, without `wrap()` | **0.1 ms** | the user's question, and no answer |
| the orphan that appeared beside it | 0.1 ms | the answer, in an exchange of its own |
| the handler's, with `wrap()` | **82.3 ms** | the question, the answer, real latency |

Both halves of that are worth reading twice. The turn closed at the `return`, so
its duration measures the handshake rather than the answer. And the
`agent_message()` the generator recorded a few milliseconds later arrived when
no turn was active, so it **opened one of its own** — an orphan half-exchange
in a transcript your client reads.

**Confidently wrong data is worse than none**, which is why this page exists at
all. Latency charts read as instant, answers detach from the questions that
produced them, and nothing in your logs suggests anything happened.

## What `wrap()` accepts

Say this part early, because it is not a streaming feature. It is the answer to
*any* block that ends before its work does.

| What you hand it | What ends the turn |
|---|---|
| a response object with a `body_iterator` (FastAPI/Starlette) | the body being drained |
| a sync or async generator, or any iterator | iteration finishing |
| an `asyncio.Task` or `Future`, or a `concurrent.futures.Future` | the future completing |
| any awaitable | the await returning |
| anything else | nothing — see below |

Two details that matter when you read the return value:

- **A future comes back as the same object.** Only a completion callback is
  added, so identity, `isinstance` and everything else your code does with it
  are unchanged.
- **An awaitable comes back wrapped**, so `await` what `wrap()` returned rather
  than what you passed it.

:::info Safe to leave in place
Handed something with no end to bind to, `wrap()` returns it untouched and
leaves the turn open — the [deadline](#the-deadline) closes it rather than the
turn closing before its work happened. Called with no turn active, it returns
the object unchanged. Neither case raises, so there is no shape of handler where
adding the call makes things worse.
:::

## Record the answer inside the generator

The assembled answer is only known once the stream has finished, so
`agent_message()` belongs on the generator's last line:

```python
async def answer(text: str):
    collected = []
    async for token in agent.stream(text):
        collected.append(token)
        yield f"data: {token}\n\n"
    agentsight.agent_message("".join(collected))
```

It lands on the right turn even though the generator is resumed by the framework
long after your handler returned: `wrap()` re-attaches the conversation and the
turn around **each step** of the iteration. A consumer that stops early never
reaches that line, which is exactly right — there was no complete answer to
record.

:::warning Where the call goes matters
Inside the generator, `agent_message()` reaches the turn that was wrapped.
Outside it — in whatever code drained the response — no turn is active any
more, so the message opens a fresh turn instead. That is the orphan exchange in
the table above, and nothing reports it.
:::

## The decorator form defers for you

Used as a decorator, `turn()` can see what your handler returned, and hands the
turn over by itself when that is a streaming response, a generator or a future:

```python
@agentsight.turn(id_from="conversation_id")
async def chat(conversation_id: str, text: str):
    agentsight.user_message(text)
    return StreamingResponse(answer(text))     # no wrap() needed
```

The list is deliberately short: a handler that returns a list or a dict has
finished, and treating those as unfinished work would leave every ordinary turn
open until its deadline. The `with` form cannot see your return value at all,
which is the whole reason the explicit call exists.

## When the customer closes the tab

A consumer walking away mid-answer is not a failure, and it is not an exchange
either. The turn is recorded as **abandoned**: it never appears in the
transcript as a half-exchange, the tokens it burned still show up in your usage,
and the abandonment is visible as what it is rather than vanishing.

That covers a client that disconnects while the framework is draining your
response. It does not cover an app that notices the disconnect itself:

```python
async def answer(request: Request, text: str):
    async for token in agent.stream(text):
        if await request.is_disconnected():
            agentsight.abandon_turn()
            return
        yield f"data: {token}\n\n"
```

**From the SDK's side a normal return is indistinguishable from success**, so a
handler that detects the disconnect and returns cleanly has to say so.

## Work that isn't a stream

Anything bound to a future works the same way, which is what makes this a
general tool rather than an HTTP one:

```python
with agentsight.turn() as exchange:
    agentsight.user_message(text)
    return agentsight.wrap(pool.submit(answer, text))
```

A future that raises records the turn as an error; a cancelled future records it
as abandoned, because a cancelled task is the caller walking away rather than
the work blowing up.

:::warning A worker thread has no scope of its own
Scopes are per-context, and submitting to a pool does not carry yours across. A
module-level `agentsight.agent_message()` from inside the pooled function is
dropped — there is no active conversation there to attach it to. Record the
answer where you have the result, or call it on the scope object
(`exchange.agent_message(...)`), which writes to that turn from any thread.
:::

## When there is nothing to bind to

Sometimes there is no object at all: a websocket exchange finished by a later
callback, a queued job whose reply arrives on another channel. `keep_open()`
takes the turn out of the block's hands, and you end it yourself:

```python
@celery.task
def answer_question(conversation_id: str, text: str):
    with agentsight.conversation(conversation_id):
        with agentsight.turn() as exchange:
            agentsight.user_message(text)
            exchange.keep_open()
            enqueue_reply(text, on_done=lambda reply: finish(exchange, reply))


def finish(exchange, reply):
    exchange.agent_message(reply)
    exchange.end(complete=True)
```

`exchange.end(complete=False)` is the same call for a reply that never came, or
came back an error: it keeps the exchange out of the transcript exactly as an
abandoned stream is kept out, and the work it did stays on the record.

**Hold the scope and use it.** Once the block has exited, a turn kept open is no
longer the *active* one, so the module-level `agent_message()` and
`agentsight.end_turn()` target whichever turn is active in the callback's
context — which is usually none, and a message with no turn opens one of its
own. `TurnScope.user_message()` and `TurnScope.agent_message()` exist for
exactly this callback. Reach for the module-level `end_turn()` only where the
code finishing the work still runs inside the block that opened the turn.

## The deadline

A turn handed off and never ended would stay open forever, holding the work
beneath it, and the exchange would never arrive. So every deferred turn gets a
deadline — `init(turn_timeout_ms=...)`, **five minutes by default**. On expiry
the turn is closed and recorded as incomplete, with a warning on the
`agentsight` logger naming what happened. `0` disables it. A turn inside a plain
`with` block is unaffected: it ends when the block ends.

## Graceful shutdown is your job

:::warning The one loss mode a library cannot cover
Recorded work is batched, so a few seconds of it is in memory at any moment. An
orderly exit flushes automatically; **`SIGTERM` — how containers stop — does
not.** Call `agentsight.shutdown()` from your app's own shutdown hook.

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    agentsight.init()
    yield
    agentsight.shutdown()
```

Deferred turns are ended first on the way out, so a stream still in flight goes
out marked incomplete rather than being lost with the process. In a process that
exits on its own — a serverless handler, a script — `agentsight.flush()` after
the turn has ended does the same job without tearing the SDK down.
[Deployment & limitations](/getting-started/deployment) has the Celery and bare
`signal` versions.
:::

## Next

- [FastAPI](/integrations/fastapi) — the whole thing as one runnable app, id
  nested in the payload and all
- [Turns & Messages](./turns-and-messages.md) — the exchange this page is a
  special case of
- [Tokens & Cost](./tokens-and-cost.md) — what a streamed LLM call reports,
  and when it reports nothing
- [Configuration](/getting-started/configuration) — keys, environments, and
  logging
- [Deployment & limitations](/getting-started/deployment) — shutdown hooks and
  the gaps worth knowing about
