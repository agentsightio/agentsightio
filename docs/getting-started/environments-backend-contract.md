# Backend change: environments are a table now

**No SDK change is required. Version 0.0.44 and every older release keep working
exactly as they are.** That was a hard requirement of the backend change, not a
happy accident — read on for why, and for two pre-existing SDK bugs this is a
good moment to fix.

---

## What changed on the backend

Environments (`production` / `development`) used to be a hardcoded string enum on
two Django models. They are now rows in a real table, one set per agent, seeded
automatically. A data migration gave every existing agent its two environments.

The purpose is groundwork: adding a third environment later becomes a row insert
rather than a schema migration plus a coordinated release across every client.

---

## Why nothing breaks

The SDK is published to PyPI. Every version ever released stays installable
forever, those versions POST `{"environment": "production"}`, and there is **no
version field in the `open_conversation` ingest payload** to branch on. So the
backend cannot ever stop accepting the string form.

That constraint shaped the design:

- The environment **slug** (`"production"`, `"development"`) is treated as a
  published contract on the backend. Slugs are not user-editable and are never
  renamed — the display label is a separate `name` column for exactly that
  reason.
- The `environment` key on requests and responses still carries the same
  strings. A backend serializer field converts slug ↔ row on the way in and out,
  specifically so the FK never leaks onto the wire as an integer.

### Your call sites, all unchanged

| Path | Sends | Status |
|---|---|---|
| [agentsight/client/main_client.py:438](../../agentsight/client/main_client.py#L438) | `"environment": self.config.environment or environment` | works |
| [agentsight/client/main_client.py:814](../../agentsight/client/main_client.py#L814) | same | works |
| [agentsight/sdk/exporter.py:136-138](../../agentsight/sdk/exporter.py#L136-L138) | flattens `agentsight.conversation.environment` → `environment` | works |
| [agentsight/sdk/api.py:156-160](../../agentsight/sdk/api.py#L156-L160) | same, for the immediate visit ping | works |
| [agentsight/enums.py:50-62](../../agentsight/enums.py#L50-L62) | `Environment` enum values | still exactly the accepted slugs |

The backend also still accepts the shorthand `"dev"` / `"prod"`, is
case-insensitive, and trims whitespace. An unrecognized value is still a 400.

---

## What is new (additive, optional)

Responses that carried `environment` now also carry `environment_id`:

```jsonc
{
  "environment": "production",   // unchanged
  "environment_id": 7            // new
}
```

The SDK only ever reads `data.get('environment')`
([main_client.py:701](../../agentsight/client/main_client.py#L701)), so this is
invisible to it. You may ignore it indefinitely. Environment ids are **per
agent** — an id from one agent is rejected on another — so the slug remains the
better thing to send.

Conversation feedback is likewise unaffected: `POST /api/conversation-feedbacks/`
creates conversation-kind feedback, whose environment the backend derives from
the conversation. **No payload change.**

---

## Two pre-existing bugs worth fixing now

Neither is caused by this change. Both are about environments specifically, and
both are currently *silent*, which is why they are easy to miss.

### 1. `AGENTSIGHT_ENVIRONMENT` is never validated

[agentsight/config.py:40-43](../../agentsight/config.py#L40-L43):

```python
environment: Optional[Environment] = field(
    default_factory=lambda: os.getenv("AGENTSIGHT_ENVIRONMENT"),
```

The annotation says `Environment`, but this returns a raw `str` and is never
coerced through `Environment.from_env()`. Compare `token_handler` just below at
[config.py:50-53](../../agentsight/config.py#L50-L53), which *does* coerce, and
`__post_init__` at [config.py:104-118](../../agentsight/config.py#L104-L118),
which normalizes `log_level` and `token_handler` but not `environment`.

Consequence: `AGENTSIGHT_ENVIRONMENT=staging` is sent to the backend verbatim
and comes back a 400 — at request time, from the server, rather than as a clear
`ValueError` at configuration time. `Environment.from_env` already exists and
raises exactly the right error; it just isn't wired up.

This gets more relevant, not less, once custom environments exist: users *will*
start setting this to things like `staging`, and the failure should name the
problem locally.

### 2. `agentsight.init(environment=...)` is a no-op on the OTel path

[agentsight/sdk/core.py:131](../../agentsight/sdk/core.py#L131):

```python
_state.environment = environment or os.getenv("AGENTSIGHT_ENVIRONMENT")
```

`_state.environment` is written here and **read nowhere else in the package**.
So on the OTel path, environment only flows if it is passed per-`conversation()`;
the global setting is silently discarded.

This contradicts
[docs/getting-started/environments.md:60-71](environments.md#L60-L71), which
tells users the env var applies globally.

### Also worth a look

[docs/tracking/track-interaction.md:39,54](../tracking/track-interaction.md#L39)
documents the default as `"production"`, while
[main_client.py:410](../../agentsight/client/main_client.py#L410) defaults to
`"development"`. Pre-existing inconsistency, unrelated to the backend.

---

## If a third environment ever ships

When custom environments become creatable, the SDK will need no structural
change — send its slug in the same `environment` field. The one thing to fix
first is the validation in `Environment` / `from_env`, which currently hardcodes
the two values and would reject a legitimate `"staging"` before the request is
even made.

Full backend detail: `ags_backend/docs/agent-environments.md`.
