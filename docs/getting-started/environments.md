---
outline: deep
---

<CopyMarkdownButton />

# Manage Environments

Testing before going live is crucial, and the same applies to your AI.

## How it works

Every agent is seeded with two environments: **development** and **production**.
They are created with the agent, and every conversation is recorded against one
of them. An agent given further environments server-side keeps working
unchanged — the SDK learns the full list at startup.

* **Development:** for testing and iteration.
* **Production:** for live, real-world interactions.

AgentSight tags each conversation with its environment, so test traffic and real
traffic stay separate in your dashboard.

## Rules & Behavior

| Environment | Purpose | Dashboard Access | Analytics Availability |
| --------------- | -------------------------------------------- | ----------------------------------------------------- | ---------------------------------------------------------------- |
| **Development** | Used for building and testing your AI.       | View transcripts, messages, actions, and attachments. | ❌ No analytics or reports (test data is excluded from insights). |
| **Production**  | Used for deployed, real-world conversations. | Full access to dashboards, analytics, and reports.    | ✅ Analytics and reports available.                               |

To view your development data inside the dashboard, simply toggle **Development
Mode**. Analytics and reports are computed from production traffic only, so
Development Mode shows you which metrics are receiving data instead of charts —
enough to confirm your integration is working, without test runs skewing the
numbers your dashboards report.

> **Note:** Conversations are recorded against **production** unless you select
> an environment.

## How to set the environment

Set it once for the whole deployment. Either pass it to `init()`:

```python
agentsight.init(environment="development")
```

or set it in the environment, which is usually what you want — the same code then
records against development on a developer's machine and production once
deployed:

```bash
AGENTSIGHT_ENVIRONMENT=development   # or: production
```

`dev` and `prod` are accepted as shorthand for either form.

### Overriding it for one conversation

The deployment-wide setting is the default, not a ceiling. A single conversation
can name its own environment, which is what you want for a seeded demo or an
evaluation run inside a production process:

```python
with agentsight.conversation("eval-run-41", environment="development"):
    ...
```

Everything recorded inside that conversation inherits it.

### Checking what an agent has

`environments()` on the API client is the authoritative list:

```python
from agentsight.api import AgentSight

ags = AgentSight()
print(ags.environments())   # ['production', 'development']
```

## When the value is wrong

An unrecognised environment is reported as an error at startup, while you are
still watching the logs — not discovered later as a batch that quietly went
nowhere.

If one reaches a conversation anyway, that conversation is recorded without an
environment rather than being dropped, and the SDK warns once naming the value it
could not place. A typo costs you the environment tag; it never costs you the
data.

For more configuration options, see the [Configuration](./configuration.md) page.
