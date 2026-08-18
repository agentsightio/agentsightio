---
outline: deep
---

<CopyMarkdownButton />

# Errors and retries

**This client raises.** That is the opposite of the tracking SDK, which
swallows everything so a monitoring library can never break your handler — and
the difference is deliberate. A dropped span costs you one row on a chart. A
read that quietly returns nothing costs you a wrong answer you then act on.

Everything raised here descends from `AgentSightError`, and the hierarchy is
shallow on purpose: status code first, message second, with narrower classes
only where callers genuinely branch.

```python
from agentsight.exceptions import APIError, NotFoundError

try:
    conversation = ags.conversations.get("wa-3859")
except NotFoundError:
    conversation = None
except APIError as exc:
    log.warning("AgentSight said %s: %s", exc.status_code, exc.detail)
```

Every one of these is also importable straight from the package —
`agentsight.NotFoundError` and `agentsight.exceptions.NotFoundError` are the
same class.

## The hierarchy

| Exception | Raised when |
|---|---|
| `AgentSightError` | the base of everything below |
| `ConfigurationError` | the client cannot be built from what it was given |
| `MissingApiKeyError` | no key was passed and none is in the environment |
| `InvalidApiKeyError` | a key is present but not shaped like one |
| `APIError` | the server answered, and the answer was an error |
| `AuthenticationError` | the credential was rejected |
| `SubscriptionInactiveError` | the key is fine; the agent is not paid up |
| `PermissionDeniedError` | authenticated, but not allowed to do this |
| `NotFoundError` | no such row, or a lookup that matched nothing |
| `ValidationError` | the request was rejected as malformed |
| `MethodNotAllowedError` | that verb is not offered on that resource |
| `RateLimitError` | too many requests, and waiting is the right response |
| `ServerError` | the server failed, and retrying did not help |
| `NetworkError` | the request never got an answer at all |
| `UploadError` | an attachment upload was refused |

`ConfigurationError` and its two children are raised before any request is
attempted. `APIError` and its children mean a real response came back —
`except APIError` catches everything the server can say. `NetworkError` is
outside that family precisely because there was no response to classify:
DNS, connection, timeout, TLS.

`UploadError` belongs to `agentsight.upload_attachments()` on the tracking side
rather than to this client, and is listed here because it is the one tracking
call allowed to raise — it moves customer files, not telemetry.

## What the exceptions carry

Every `APIError` carries three things:

```python
except APIError as exc:
    exc.status_code    # 400, 403, 404, 429, 500…
    exc.detail         # the server's own words, where it gave any
    exc.response       # the parsed body
```

Error bodies are not uniform — some name a `detail`, some an `error`, some a
field map — so they are normalised into that one attribute rather than left for
each call site to unpick.

Two subclasses add one attribute each:

**`ValidationError.errors`** is the parsed error body when the server sent a
JSON object — usually the per-field map naming what was rejected — and an
empty dict otherwise.

**`RateLimitError.retry_after`** is the server's own pacing, in seconds, or
`None` where it sent none. It is already normalised — a date form is converted
to a duration, and a time in the past reads as `0.0`.

```python
except RateLimitError as exc:
    time.sleep(exc.retry_after or 5)
```

## Three that are easy to misread

**`SubscriptionInactiveError` is the 401 that rotating a key will not fix.**
Everything else in the 401 family — unknown key, revoked key, key not linked to
an agent — is a credential problem. This one means the credential is fine and
the account is not; catching it separately is what lets you say so.

**`PermissionDeniedError` usually means a read-role key attempted a write.**
Every method marked *write role* in these pages raises it for such a key. You
no longer have to discover the role that way: `ags.me()["role"]` reports it.

:::info `ValidationError` is raised locally too
An unknown filter name, a sentiment that is not one of the three, a `group_by`
the summary does not offer — all of these raise before anything is sent. The
message names the values that would have worked. You can tell the two apart:
a locally-raised one has `status_code` of `None` and an empty `errors`.

```python
ags.conversations.list(has_ticket=True)
# ValidationError: unknown conversation filter(s): has_ticket.
#                  Supported: action_name, conversation_id, customer_id, …
```

Refusing an unrecognised filter is worth the strictness. A filter the server
does not apply returns *more* rows than you asked for, and a typo that quietly
widens a result set is far worse than one that errors.
:::

## What gets retried

**Reads retry. Writes never do.**

A read that fails on a 5xx, a 429 or a network fault is attempted again — three
attempts by default, waiting half a second and then two seconds. `max_retries`
on the client changes that count. A 429 that names its own pacing overrides the
curve: the server knows better than the backoff does.

Writes are attempted exactly once, whatever the failure. Nothing this client
writes is safe to replay — a repeated `feedbacks.create_for_conversation()` is a
second row, not a retried one — so a failed write raises and the decision is
yours. Where the failure was a 429, `retry_after` tells you how long to wait
before making that decision.

`ServerError` on a read therefore means the server failed *and* retrying did
not help. A write is attempted exactly once — for the reason above — so a
write's first 500 raises immediately.

## Next

- [The API client](./index.md) — `timeout` and `max_retries`, and where `me()`
  reports your role
- [Pagination](./pagination.md) — where a rejected filter surfaces, and when
- [Conversations](./conversations.md) — the filters that are accepted, listed
