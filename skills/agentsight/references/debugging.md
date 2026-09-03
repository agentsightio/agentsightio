# Debugging: read back what was actually recorded

Nothing on the tracking plane ever raises, so a wrong integration produces
plausible wrong data, not errors. That cuts both ways: no error message will
ever point you at the problem, but the recorded output — read back locally or
in the dashboard — always shows it. Every "why is this metric empty?" and
every "did my change record correctly?" resolves the same way: **run the app,
read back what it recorded.** Never conclude from the code alone.

## Contents

- [The file-exporter loop](#the-file-exporter-loop)
- [Symptom → cause](#symptom--cause)
- [The live smoke test](#the-live-smoke-test)

## The file-exporter loop

The SDK can write every batch to local JSON instead of transmitting — no key,
no account, no network:

```bash
AGENTSIGHT_FILE_EXPORTER=/tmp/agentsight-verify python -m your_app
# exercise the real entry points: send a message, trigger a tool,
# stream an answer, hit the escalation path
```

Each file in the directory is one export batch — the exact payload that would
have been sent, which also makes this the honest answer to "show me what
leaves the process" when data consent comes up:

```bash
jq '.conversations[] | {conversation_id, customer_id, device, language, environment}' /tmp/agentsight-verify/*.json
jq '.conversations[].spans[] | {kind, name, duration_ms}' /tmp/agentsight-verify/*.json
# Messages are EVENTS on the turn span, not spans of their own — read them there:
jq '.conversations[].spans[] | select(.kind=="turn") | .events[].attributes' /tmp/agentsight-verify/*.json
```

Exercise the app through its real transport (HTTP call, webhook payload,
websocket message) — not by importing the handler and calling it, which can
miss exactly the lifetime bugs this loop exists to catch. Unset the variable
afterwards: set, it means **nothing is transmitted**, so a file exporter left
configured in production is itself a cause of total silence.

## Symptom → cause

The failure modes, from the dashboard symptom back to the line of code. Every
one of these records confidently wrong data rather than raising.

| Symptom | Cause and fix |
|---|---|
| Transcripts and actions appear, but analytics and charts stay empty | Recording into `development` — that environment is excluded from analytics **by design**. Check `AGENTSIGHT_ENVIRONMENT` on the deployment that should be production. |
| Nothing recorded at all | In order: `AGENTSIGHT_FILE_EXPORTER` still set (nothing transmits); `init()` never ran in the worker process (pre-fork servers preload in the parent — move it to the post-fork hook); no key / read-role key (watch the `agentsight` logger at startup — `init()` returning `True` is not key validation, the background check is); calls outside any `conversation` scope are dropped with only a debug line. |
| Turn durations near zero (~0.1 ms) on streaming endpoints | Missing `wrap()` — the turn closed at `return`, timing the handshake instead of the answer. See [streaming-and-lifetime.md](streaming-and-lifetime.md). |
| An orphan half-exchange: one turn holding only the question, another holding only the answer | `agent_message()` ran after the turn ended — outside the generator, or module-level in a callback where no turn is active. Record on the generator's last line, or hold the `TurnScope` and use its methods. |
| Every tool call recorded twice | The function is decorated **and** framework-reported. LangChain/LlamaIndex tools arrive undecorated — remove the decorator. |
| Human Escalation Rate is zero, but the handoff tool shows in tool usage | The action's name is not one of the four exact escalation names (`fallback_to_human` / `open_ticket` / `ticket` / `contact_human`). Rename via `@agentsight.tool(name=…)`. |
| Individual Users reads 0 | `customer_id` never passed on the conversation. Same pattern for the World Map (`customer_ip_address` — must parse as an IP or it is dropped), Device Usage, and Agent Language. |
| An LLM call shows no cost | No model name resolved — permanently unpriceable; wrap the call site in `model_hint()` now. A *named* model showing `unpriced` is different: tokens are exact and cost is restated when a rate exists. |
| Token totals look too low | Direct Bedrock/Vertex/Ollama/LiteLLM calls or `with_streaming_response` in the path — no patch covers them, see [frameworks.md](frameworks.md). A stream that ended without a usage event is marked unreported, not billed as zero. |
| Conversations exist but can't be found by the id support quotes | A generated or per-visit id was recorded instead of the durable business id. There is no repair for already-recorded threads — fix the id source. |
| The Source chart is empty | `source` is recorded but not yet surfaced anywhere — this one is not a bug. |
| A recent change isn't visible yet | Spans batch on `export_interval_ms` (default 5 s) and SIGTERM does not flush — an orderly `shutdown()` does. Short-lived processes need `flush()` after the turn ends. |
| Embed shows an error or an empty container | Different surface entirely — see [embed.md](embed.md): origin allow-list, token state, container height. |

## The live smoke test

With a key available, confirm the pipeline end to end without touching
production numbers:

1. Unset `AGENTSIGHT_FILE_EXPORTER`.
2. Run once with the environment set to `development`.
3. Watch the logs: the background key check is what reports a refused key, an
   inactive subscription, or a read-role key (recording needs write).
4. In the dashboard, toggle **Development Mode**: it shows which metrics are
   receiving data instead of charts — confirmation the integration is landing,
   without test runs skewing production numbers. The recorded conversation's
   transcript is viewable there too.
5. Only then flip the deployment to `production`. Development data is excluded
   from analytics by design, so a deployment left on `development` looks like
   silence, not an error.
