# The embeddable dashboard

AgentSight's embed is a **read-only, white-labeled dashboard rendered inside
the developer's own product** — the "share it with your client" surface:
analytics, saved reports, conversation history, feedback, optionally tickets.

State the negative first, because it prevents a whole class of wrong
integrations: **the embed records nothing.** It emits no telemetry, collects
no feedback, and sends no "widget opened" signal. All tracking comes from the
Python SDK in the developer's backend; the embed only displays what was
recorded. "Widget opened, nobody typed" is `open_conversation()` on the
backend — nothing to wire on the embed side.

## Setup order (in the AgentSight dashboard, per agent)

The dashboard's embed settings walk this order; teach it the same way,
because the snippet cannot work until the first two exist:

1. **Embed Origins** — allow-list the exact origin (scheme + host + port)
   of the page that will host the snippet. No wildcards, no paths. This is
   the number-one setup failure: an origin not on the list gets a 403 and an
   empty container.
2. **Embed Tokens** — create a token (`agse_…`). Shown **once**; revocable;
   there is no rotate — revoke the old one and create a new one. Access is
   read-only (the recommended default) or read & write (adds
   marking/renaming conversations, ticket creation and comments). Expiry is
   settable; "never expires" on a token embedded in a public page is a real
   tradeoff worth naming to the developer.
3. **Feature flags** — what the embed exposes is configured in the dashboard,
   not in the snippet. PII-adjacent fields (`customer_id`, IP, geolocation,
   device) are **off by default** because embed viewers do not log in —
   anyone who can load the client's page sees whatever is enabled. Chart
   visibility has its own per-embed flags. Changes apply to already-open
   embeds.
4. **Get the snippet** — generated on the same settings page.

## The snippet

```html
<script
  src="https://embed.agentsight.io/loader.js"
  data-embed-token="agse_..."
  data-container="agentsight-embed"
  defer
></script>
<div id="agentsight-embed" style="width: 100%; height: 100%;"></div>
```

- **The container needs a real height.** The embed fills its container; a
  zero-height parent renders an invisible dashboard. This is the second most
  common setup failure after origins.
- Optional attributes: `data-theme="light"|"dark"` pins the starting theme
  (otherwise it auto-detects the host page's light/dark markers and follows
  live changes); `data-show-header="false"`; `data-show-theme-toggle="false"`.
- Serve the host page from a real HTTP origin — the origin check cannot pass
  from a `file://` page.

## Tokens are not API keys

| | `ags_…` API key | `agse_…` embed token |
|---|---|---|
| Lives | server-side only | in the client's page |
| Grants | read/write on the data API | a scoped dashboard session for one agent |
| In a browser | **never** | by design |

The loader exchanges the embed token for a short-lived session itself; the
developer never handles that part. An API key pasted into a page is a
credential leak — if found during pre-flight, flag it.

## Errors the developer will actually see

| Symptom | Meaning |
|---|---|
| "This dashboard isn't authorized to appear here." (403) | host origin not on the allow-list — add the exact origin |
| "This dashboard is no longer available. Contact your provider." (401) | token revoked, expired, or wrong |
| Empty/invisible container, no error | container has no height |
| Works locally, fails deployed | the deployed origin was never allow-listed |

Removing an origin or revoking a token takes effect immediately, including on
already-open pages — that is the kill switch.

## One id, both surfaces

The embed's conversation and feedback views are searched by the
**`conversation_id` the SDK recorded**. This is another reason Tier 1
question 2 matters: a stable, human-recognizable id is what the developer's
client will paste into the embed's search; a generated id makes every lookup
a dead end.
