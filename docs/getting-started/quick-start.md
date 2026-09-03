---
outline: deep
---

<CopyMarkdownButton />

# Quickstart

AgentSight records what your agent did — the exchanges, the answer latency, the
tool calls, the LLM spend — from the smallest amount of code that can honestly
capture it. No infrastructure, no collector to run.

## Installation

:::tabs
== pip
```bash
pip install agentsight python-dotenv
```
== poetry
```bash
poetry add agentsight python-dotenv
```
== uv
```bash
uv add agentsight python-dotenv
```
:::

[python-dotenv](https://pypi.org/project/python-dotenv/) is included because
with it present, importing `agentsight` picks up a `.env` file — so your key
never has to be in code.

## Or let your coding agent do it

If a coding agent works in your repository, there are packaged skills that
make the whole integration a task it completes correctly on the first pass —
it reads your code first, asks only what code cannot answer, and verifies
what it recorded before claiming success. A third one builds the file that
brings your existing conversation history over. Install them:

:::tabs
== skills CLI
```bash
npx skills add agentsightio/agentsightio
```
== Claude Code plugin
```
/plugin marketplace add agentsightio/agentsightio
/plugin install agentsight@agentsight
```
:::

then ask in plain words — "add AgentSight to this service" — and skip the
rest of this page. What the skills do, the agents they work with, and the
no-installer route are on [Use with AI agents](/getting-started/ai-agents).

## Setup

Get an API key from the [AgentSight dashboard](https://app.agentsight.io/) and put
it in `.env`:

```bash
AGENTSIGHT_API_KEY="your_api_key_here"
```

:::warning Message content is transmitted
Everything you track — message text, tool arguments, tool responses — is sent to
AgentSight and stored. Nothing is scraped or inferred, but you should know exactly
what leaves your process before you ship.
[What the SDK sends](/getting-started/what-the-sdk-sends) lists every field, and
shows you how to dump the payload locally without sending it.
:::

## Quickstart

```python
import agentsight

agentsight.init()

@agentsight.turn(id_from="session_id", infer=True)
def handle_message(session_id: str, text: str) -> str:
    return my_agent.run(text)
```

That's a complete integration. Every call records a conversation, both messages
and the answer latency — plus every LLM call made inside it, with token usage and
cost, and every tool call the SDK can see: the functions you decorate with
`@agentsight.tool` and the tools your framework reports.

:::info When this shortcut applies
`infer=True` reads the user message from the first string argument and the agent
message from the return value. It fits handlers shaped like `(text) -> str`.

Most production handlers aren't — they take a framework request object, or the id
is nested in a payload, or the text is rewritten before the agent sees it. For
those, see [Turns & Messages](/tracking/turns-and-messages), which is a few more
lines and works everywhere.
:::

`id_from` names the parameter holding your conversation id. When the id is nested
somewhere less convenient, it also takes a callable:

```python
@agentsight.turn(id_from=lambda args: json.loads(args["data"])["conversation_id"])
def chat(request: Request, data: str = Form(...)):
    ...
```

## Seeing it land

Your conversations appear in the [dashboard](https://app.agentsight.io/) within a
few seconds.

If you would rather look before anything is transmitted, point the SDK at a
directory instead of the network — no key, no account, no requests:

```bash
AGENTSIGHT_FILE_EXPORTER=./agentsight-traces python your_app.py
```

`AGENTSIGHT_FILE_EXPORTER` names a **directory**, not a file — the SDK creates
it if needed and writes one JSON file into it per batch. (Putting the variable
in front of `python your_app.py` sets it for that one run; exporting it or
adding it to `.env` works the same.) You get the exact JSON the API would have
received.

## Next steps

- [Core Concepts](./core-concepts.md) — the four things you model, and how they
  nest
- [Turns & Messages](/tracking/turns-and-messages) — the explicit form, for real
  handlers
- [Streaming](/tracking/streaming) — required reading before you ship a streaming
  endpoint
- [Configuration](./configuration.md) — keys, environments, and logging
- [Deployment & limitations](./deployment.md) — graceful shutdown, and the gaps
  worth knowing about
