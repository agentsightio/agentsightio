"""`wrap()` — when the block ends before the work does.

A `with` block ends when the function returns. A unit of work often doesn't:
a handler that returns a streaming response has not finished answering, and
the framework drains the generator afterwards. Close the span at the `return`
and you record ~0ms latency and no agent message — confidently wrong data,
which is worse than none, and nothing raises to tell you.

This is the single most commonly mis-integrated thing in the SDK, so the
example shows the wrong version alongside the right one. Standard library
only: FastAPI/Starlette responses are the usual case, but the primitive is not
about FastAPI, and a Celery task or queue consumer needs exactly the same tool.

    venv/bin/python examples/06_streaming.py
"""

import asyncio

import _common  # noqa: F401  — puts the repository root on sys.path

import agentsight as ags

TOKENS = ["Order ", "A-1 ", "ships ", "tomorrow."]


async def answer_tokens():
    """Yields the answer, then records it.

    The `agent_message()` call belongs *inside* the generator. `wrap()`
    re-attaches the turn's scope around each step, so a call made here lands on
    the right turn even though the generator is resumed by the framework long
    after the handler returned. Making the same call from the consumer after
    draining would open a fresh turn instead, because by then nothing is
    active — and nothing would raise to say so.

    A consumer that stops early never reaches the last line, which is exactly
    right: there was no complete answer to record.
    """
    collected = []
    for token in TOKENS:
        await asyncio.sleep(0.02)
        collected.append(token)
        yield token
    ags.agent_message("".join(collected))


# --------------------------------------------------------------------- wrong


def handler_without_wrap():
    """What a naive integration looks like. Do not copy this one."""
    with ags.turn("no-wrap"):
        ags.user_message("Where is my order?")
        return answer_tokens()  # the turn ends HERE, before a token is sent


# ----------------------------------------------------------------------- right


def handler_with_wrap():
    """One call, and the turn now ends when the stream does."""
    with ags.turn("wrapped"):
        ags.user_message("Where is my order?")
        return ags.wrap(answer_tokens())


async def drain(stream, stop_after=None):
    """Stand-in for the framework that consumes the response body."""
    collected = []
    async for token in stream:
        collected.append(token)
        if stop_after is not None and len(collected) >= stop_after:
            # The consumer walked away — a closed tab, mid-answer.
            await stream.aclose()
            break
    return "".join(collected)


async def main_async() -> None:
    run = _common.start("06_streaming", auto_instrument=False)

    with ags.conversation("demo-streaming", customer_id="user-55", source="web"):
        # 1. Without wrap(): the span closes at the return. Compare its
        #    duration against the wrapped one below — that gap is the whole
        #    point, and no error is raised to warn you about it.
        await drain(handler_without_wrap())

        # 2. With wrap(): the turn's duration is the real answer latency, and
        #    the agent message the generator emits on its last line lands on
        #    this turn rather than on one of its own.
        await drain(handler_with_wrap())

        # 3. The consumer stops halfway. The turn is recorded as abandoned:
        #    never a half-exchange in the transcript, but the tokens it burned
        #    still count and the abandonment is visible as what it is.
        partial = handler_with_wrap()
        await drain(partial, stop_after=2)

        # 4. No object to bind to at all — work finished by a later callback,
        #    a websocket reply, a queue consumer. keep_open() defers the turn
        #    and you end it yourself; the watchdog closes it as incomplete if
        #    you never do (init(turn_timeout_ms=...), five minutes by default).
        with ags.turn("deferred") as deferred:
            ags.user_message("ping over a websocket")
            deferred.keep_open()

        await asyncio.sleep(0.05)  # ...the callback arrives later
        # On the scope, not the module: out here the deferred turn is no longer
        # the active one, so `ags.agent_message()` would open a turn of its own.
        deferred.agent_message("pong")
        deferred.end(complete=True)

    run.finish()


if __name__ == "__main__":
    asyncio.run(main_async())
