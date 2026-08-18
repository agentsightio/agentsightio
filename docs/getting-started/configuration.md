---
outline: deep
---

<CopyMarkdownButton />

# Configuration

Everything the SDK does is configured in one call. `agentsight.init()` reads a
handful of environment variables, accepts the same values as keyword arguments,
and returns whether tracking is active.

```python
import agentsight

agentsight.init()
```

`init()` **never raises.** A missing or malformed key logs an error and leaves the
SDK disabled, and a disabled SDK is a pass-through: every scope and decorator
still runs your code, records nothing, and your application behaves exactly as if
AgentSight were not installed. The return value is there for the rare caller that
wants to branch on it.

Called a second time after a successful first, `init()` does nothing and
returns `True` — a failed attempt does not block a later one. `is_enabled()`
answers the same question at any point afterwards: `True` while tracking is
live, between a successful `init()` and `shutdown()`, without holding on to
`init()`'s return value.

## The API key

Pass it directly, or set `AGENTSIGHT_API_KEY`:

```python
agentsight.init(api_key="ags_...")
```

```bash
AGENTSIGHT_API_KEY="ags_..."
```

Get the key from the [AgentSight dashboard](https://app.agentsight.io/).
Importing `agentsight` loads a `.env` file if
[python-dotenv](https://pypi.org/project/python-dotenv/) is installed, so a key
sitting in `.env` counts as set without any code of your own.

The key is checked for shape before anything else. If it is absent or malformed,
`init()` says so and returns `False` — it does not wait for the first batch to be
refused. Whether the key is *accepted* is a separate question, answered by
[key verification](#key-verification-at-startup).

## Every `init()` parameter

| Parameter | Type | Default |
|---|---|---|
| `api_key` | `str` | `AGENTSIGHT_API_KEY` |
| `endpoint` | `str` | `AGENTSIGHT_API_ENDPOINT`, or `https://api.agentsight.io` |
| `environment` | `str` | `AGENTSIGHT_ENVIRONMENT` |
| `auto_instrument` | `bool` or list of names | `True` |
| `export_interval_ms` | `int` | `5000` |
| `max_queue_size` | `int` | `2048` |
| `turn_timeout_ms` | `int` | `300000` (five minutes) |
| `span_exporter` | OpenTelemetry `SpanExporter` | none |
| `verify_key` | `bool` | `True` |

Only `api_key` is positional. Everything else is keyword-only.

**`endpoint`** — where batches are POSTed. You need this only against a
self-hosted or staging backend.

**`environment`** — which of the agent's environments this deployment records
against. See [Environments](./environments.md); an unrecognised value is reported
at startup rather than discovered later.

**`auto_instrument`** — which providers and frameworks are instrumented without
any code from you. `True` covers all of them: OpenAI, Anthropic, LangChain and
LlamaIndex. Pass a list to narrow it, or `False` to turn it off entirely and keep
only your explicit calls:

```python
agentsight.init(auto_instrument=["openai", "anthropic"])
agentsight.init(auto_instrument=False)
```

The names `llamaindex`, `llama-index`, `claude` and `openai_agents` are accepted
as aliases. A library that is not installed is skipped quietly — asking for
`anthropic` in a process that has never imported it is not an error.

**`export_interval_ms`** — how long finished spans wait before a batch is sent.
See [Throughput](#throughput); the default is deliberately not the fastest
setting.

**`max_queue_size`** — how many spans may wait in memory. Once it is full, newly
recorded spans are dropped as they arrive rather than the queue growing without
bound, and the SDK warns you before it gets there.

**`turn_timeout_ms`** — the deadline for a turn whose lifetime was handed to
`wrap()`, five minutes by default. It exists so a stream nobody drains cannot
leave a turn open forever: on expiry the turn is closed and recorded as
incomplete, with a warning naming what happened. `0` disables the deadline. A
turn inside a `with` block is unaffected — it ends when the block ends.

**`span_exporter`** — swaps the transport. Any OpenTelemetry `SpanExporter` slots
in behind the same buffering and batching, which puts your code between the SDK
and the network. With one supplied no API key is required, because the key exists
only to authenticate the default transport.

**`verify_key`** — see [below](#key-verification-at-startup).

## Environment variables

Five, all optional:

| Variable | Effect |
|---|---|
| `AGENTSIGHT_API_KEY` | the key `init()` uses when none is passed |
| `AGENTSIGHT_API_ENDPOINT` | overrides `https://api.agentsight.io` |
| `AGENTSIGHT_ENVIRONMENT` | selects the environment for the whole deployment |
| `AGENTSIGHT_FILE_EXPORTER` | writes spans to a directory instead of sending them |
| `AGENTSIGHT_APP_URL` | cosmetic — the dashboard address quoted in "find your API key at …" error messages |

A keyword argument always beats the matching variable, so a value in code cannot
be silently overridden by a shell.

:::info Upgrading from an earlier release
`AGENTSIGHT_LOG_LEVEL` and `AGENTSIGHT_TOKEN_HANDLER_TYPE` are no longer read.
Logging is configured with the standard library — see [Logging](#logging) — and
token capture needs no handler because it is automatic.
:::

## Seeing what is sent, without sending it

Point `AGENTSIGHT_FILE_EXPORTER` at a directory and the SDK writes what it would
have transmitted and transmits nothing. No API key, no account, no network:

```bash
AGENTSIGHT_FILE_EXPORTER=./agentsight-traces python your_app.py
```

You get one JSON file per batch — the same bytes the API would have
received, built by the same code. `init()` announces it loudly, because a stale
variable in a shell must never look like a working integration.

An explicit `span_exporter=` wins over the variable, because code is a clearer
statement of intent than an environment left over from yesterday.

It is a development aid: it does not retry, batch by size, or bound how much disk
it uses. [What the SDK sends](/getting-started/what-the-sdk-sends) walks through
reading the output.

## Key verification at startup

On by default. `init()` asks the backend once, on a background thread, whether
the key actually works.

This exists because only the *shape* of a key can be checked locally. A key that
has been revoked, one belonging to an inactive subscription, and a live key
carrying the read role where write was needed all look exactly like a working key
from inside your process — until the first batch is refused, at which point it is
dropped and reported once a minute, forever. Something that fails that quietly
should be announced while somebody is still watching the logs.

Each of those cases is logged as an error naming the cause. Failing to reach the
backend is not one of them: it is logged at debug level and nothing else, because
a check that could not complete is not evidence the key is bad.

The check **never blocks `init()`, never raises, and never disables tracking.**

```python
agentsight.init(verify_key=False)
```

Skipping it also gives up what the same response carries: the list of
environments this agent has. Turning it off leaves only the built-in pair
acceptable to `environment=`.

## Logging

Everything the SDK says goes through the standard library logger named
`agentsight`. There is no logging configuration of our own:

```python
import logging

logging.getLogger("agentsight").setLevel(logging.DEBUG)
```

Two messages are worth recognising, and both are rate-limited to once a minute so
a struggling process cannot flood your logs with a problem you already know
about:

- **Backpressure.** The export queue is filling and spans will start being
  dropped. It arrives before the queue is full rather than after, and names the
  three things that change the outcome: `max_queue_size`, `export_interval_ms`,
  and whether the API is reachable at all.
- **A dropped batch.** Something was rejected or could not be delivered, with the
  reason and a count of how many earlier drops were suppressed since the last
  warning.

Anything the SDK cannot record but can safely ignore — a metadata value clamped
to its limit, a `customer_ip_address` that is not an address — is logged once,
not once per call.

## Throughput

Two settings control how spans leave your process.

`export_interval_ms` is how long a finished span waits for company before its
batch is sent. `max_queue_size` is how many spans may be waiting at once.

The default interval of five seconds is deliberately not the fastest setting.
Sending is a **per-process** rate spent against a **per-agent** allowance, so
every worker in your deployment draws on the same budget: the figure that matters
is not the interval but the interval divided across your worker count. A single
process can afford to send often; forty cannot.

Lower it if your worker count is small and you want the dashboard to keep up.
Nothing in the SDK reads its own data back, so the only cost of waiting is
freshness. [Deployment & limitations](./deployment.md) has the version of this
that matters when you scale out.
