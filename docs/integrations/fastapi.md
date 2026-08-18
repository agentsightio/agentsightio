---
outline: deep
---

<CopyMarkdownButton />

# FastAPI

The whole integration, in the shape production handlers actually have: a request
model, a conversation id buried in the payload, the user's text rewritten before
the model sees it, a streaming response, and a shutdown hook. Nothing here is
FastAPI-specific except the framework's own names — the same five calls work
behind any web framework.

## The endpoint

```python
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

import agentsight


@asynccontextmanager
async def lifespan(app: FastAPI):
    agentsight.init()
    yield
    agentsight.shutdown()


app = FastAPI(lifespan=lifespan)


class ChatRequest(BaseModel):
    session: dict
    messages: list[dict]
    locale: str | None = None


def client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    return forwarded.split(",")[0].strip() or request.client.host


@app.post("/chat")
async def chat(payload: ChatRequest, request: Request):
    question = payload.messages[-1]["content"]
    user_agent = request.headers.get("user-agent", "")

    with agentsight.conversation(
        payload.session["conversation"]["id"],
        customer_id=payload.session.get("customer_id"),
        customer_ip_address=client_ip(request),
        device="mobile" if "Mobile" in user_agent else "desktop",
        language=payload.locale,
        source="web",
    ):
        with agentsight.turn():
            agentsight.user_message(question)
            body = answer(question)
            return agentsight.wrap(
                StreamingResponse(body, media_type="text/event-stream")
            )


async def answer(question: str):
    collected = []
    async for token in agent.astream(build_prompt(question)):
        collected.append(token)
        yield f"data: {token}\n\n"
    agentsight.agent_message("".join(collected))
```

That is the integration. Every request records a conversation with the fields the
dashboard filters on, one exchange with real latency, both messages, and — without
being mentioned anywhere above — every LLM call and every tool call made inside
the block, with token counts and cost.

Four things in it are worth reading closely.

**The id is two dereferences deep**, which is what the context-manager form is
for: dig the id out with ordinary Python, then open the scope around the work. A
decorator can reach a nested id too — with a callable, [further
down](#the-decorator-form) — but it cannot be *named*, and naming a parameter is
the only form a decorator reads well in.

**`user_message()` gets the payload's text, not the prompt.** The model sees
`build_prompt(question)` — retrieved context, history, instructions — and that is
not what the human typed. Recording the prompt would put the wrong text in a
transcript your customer reads, which is the whole reason messages are explicit.

**`wrap()` is not optional.** The handler returns before a single token is sent;
without it the exchange records near-zero latency and the answer detaches into an
orphan turn of its own. [Streaming](/tracking/streaming) is the page for this, and
it is worth reading before you ship the endpoint.

**`agent_message()` lives inside the generator**, on the line after the loop,
because that is the first moment the whole answer exists. It lands on the right
turn even though the framework resumes the generator long after `chat()` returned.

:::warning Two fields worth feeding carefully
`device` takes a word (`"mobile"`, `"desktop"`, `"whatsapp"`) — not the
user-agent string, which is far too long to be a useful label.
`customer_ip_address` takes one address, so behind a proxy pass the first hop of
`X-Forwarded-For` rather than the whole chain. Over-long values are clamped and an
unparseable address is dropped, each with a warning, so neither can lose the batch
it travelled in — but a clamped user-agent is not a device.
[Conversations](/tracking/conversations) has the full field list.
:::

## The blocking endpoint

No stream, no `wrap()` — the block really does contain the work:

```python
@app.post("/ask")
async def ask(payload: ChatRequest):
    question = payload.messages[-1]["content"]

    with agentsight.conversation(payload.session["conversation"]["id"]):
        with agentsight.turn():
            agentsight.user_message(question)
            answer = await agent.arun(build_prompt(question))
            agentsight.agent_message(answer)
            return {"answer": answer}
```

## The decorator form

When you would rather not indent twice, `id_from` takes a callable over the
handler's arguments — which is what makes a nested id reachable:

```python
@app.post("/chat")
@agentsight.turn(id_from=lambda args: args["payload"].session["conversation"]["id"])
async def chat(payload: ChatRequest, request: Request):
    question = payload.messages[-1]["content"]
    agentsight.user_message(question)
    return StreamingResponse(answer(question), media_type="text/event-stream")
```

Order matters: `@app.post` stays outermost, so FastAPI registers the wrapped
function. The decorator opens the conversation as well as the turn, and it hands
the turn over to a returned streaming response by itself — the one case where
`wrap()` is not needed.

Conversation fields go on the decorator as keyword arguments
(`@agentsight.turn(id_from=..., source="web")`), which is fine for values that are
the same on every request and no use for the ones that come off this request. That
is the trade: the decorator is shorter, the context manager can see the request.

## When the client disconnects

A client that vanishes while the framework drains your response is recorded as
abandoned without you doing anything. A handler that notices the disconnect
*itself* and returns cleanly has to say so, because a normal return is
indistinguishable from success:

```python
async def answer(request: Request, question: str):
    async for token in agent.astream(build_prompt(question)):
        if await request.is_disconnected():
            agentsight.abandon_turn()
            return
        yield f"data: {token}\n\n"
```

## Uploads

An `UploadFile` goes straight to `upload_attachments()`, which moves the bytes and
records them:

```python
@app.post("/attach")
async def attach(conversation_id: str, files: list[UploadFile]):
    with agentsight.conversation(conversation_id):
        agentsight.upload_attachments(
            [{"filename": f.filename, "data": await f.read()} for f in files]
        )
```

This is the one call that blocks and raises rather than returning quietly — see
[Attachments](/tracking/attachments) for the limits and the failure contract.

## Before you ship

- `agentsight.shutdown()` in the lifespan, as above. `SIGTERM` does not flush on
  its own, and that is how containers stop.
- `wrap()` on every handler that returns a stream, a generator or a task.
- An [environment](/getting-started/environments) chosen for the deployment.
- `export_interval_ms` sized to your worker count —
  [Deployment & limitations](/getting-started/deployment) explains why the budget
  is shared.

## Next

- [Streaming](/tracking/streaming) — `wrap()`, abandoned turns, and the deadline
- [Turns & Messages](/tracking/turns-and-messages) — the message shapes a real
  handler needs
- [Conversations](/tracking/conversations) — every field on the scope this page
  opens
- [Deployment & limitations](/getting-started/deployment) — shutdown, throughput,
  and the known gaps
- [The streaming example](/examples/streaming) — `wrap()` next to the naive
  version it replaces, runnable without FastAPI
