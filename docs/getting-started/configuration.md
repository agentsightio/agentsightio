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

## The environment

Which of the agent's environments this deployment records against — pass
`environment=` to `init()`, or set `AGENTSIGHT_ENVIRONMENT` for the whole
deployment:

```python
agentsight.init(environment="production")
```

See [Environments](./environments.md); an unrecognised value is reported at
startup rather than discovered later.

## Environment variables

Four, all optional:

| Variable | Effect |
|---|---|
| `AGENTSIGHT_API_KEY` | the key `init()` uses when none is passed |
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

It is a development aid: it does not retry, batch by size, or bound how much disk
it uses. [What the SDK sends](/getting-started/what-the-sdk-sends) walks through
reading the output.

## Key verification at startup

`init()` asks the backend once, on a background thread, whether the key
actually works.

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
It is an early, loud answer — not the gate itself: every batch is authenticated
by the backend when it arrives, so a key that does not work never results in
data being written, verified or not.

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
  dropped. It arrives before the queue is full rather than after, and names
  what changes the outcome — including whether the API is reachable at all.
- **A dropped batch.** Something was rejected or could not be delivered, with the
  reason and a count of how many earlier drops were suppressed since the last
  warning.

Anything the SDK cannot record but can safely ignore — a metadata value clamped
to its limit, a `customer_ip_address` that is not an address — is logged once,
not once per call.

Spans leave your process batched, on an interval;
[Deployment & limitations](./deployment.md) covers how that behaves when you
scale out.
