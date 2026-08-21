# Verify before you claim done

The failure modes of this integration raise nothing: a missing `wrap()`
records confidently wrong latency, a wrong environment records into silence, a
misnamed handoff tool counts zero escalations. So the definition of done is
not "the code looks right" — it is **you ran the app and read back what it
recorded.** Never report the integration finished without this loop.

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
leaves the process" (Tier 1 question 3):

```bash
jq '.conversations[] | {conversation_id, customer_id, device, language, environment}' /tmp/agentsight-verify/*.json
jq '.conversations[].spans[] | {kind, name, duration_ms}' /tmp/agentsight-verify/*.json
# Messages are EVENTS on the turn span, not spans of their own — read them there:
jq '.conversations[].spans[] | select(.kind=="turn") | .events[].attributes' /tmp/agentsight-verify/*.json
```

Exercise the app through its real transport (HTTP call, webhook payload,
websocket message) — not by importing the handler and calling it, which can
miss exactly the lifetime bugs this loop exists to catch.

## The checklist

Work through it against the JSON, not from memory:

1. **The conversation block carries the agreed fields.** The right
   `conversation_id` (the durable business id, not a generated `conv_…`),
   plus every field the interview settled: `customer_id`, `device`,
   `language`, and the rest. A field that was agreed but absent means the
   plumbing didn't reach the call.
2. **Turn durations are plausible.** A streaming exchange whose turn lasted
   ~0.1 ms means `wrap()` is missing or in the wrong place. The turn should
   span the whole answer.
3. **No orphan exchanges.** An extra turn holding only the agent's answer,
   beside a near-instant turn holding only the question, is the
   `agent_message()`-outside-the-generator bug.
4. **Both messages are present and are the human's actual words** — not a
   rewritten, translated, or scrubbed variant. (Look for them as events on
   the turn span — an empty message-span query is a wrong query, not proof
   of a missing message.)
5. **Tool spans appear, correctly named.** Every function the interview said
   to instrument; the handoff tool under its escalation name
   (`fallback_to_human` / `open_ticket` / `ticket` / `contact_human`); and
   **no doubles** — a tool recorded twice means it is decorated *and*
   framework-reported.
6. **LLM spans carry a model name and token counts.** A call with no model
   name needs `model_hint()` now — it is permanently unpriceable later. A
   streamed call may legitimately mark usage as unreported; confirm it is the
   known case, not every call.
7. **Nothing left the process that the interview excluded.** Grep the JSON
   for the values that were supposed to stay home (the skipped tool's
   arguments, the unhashed id). This check is the promise made in Tier 1
   question 3, kept.
8. **The environment tag is what the deployment intends.**

If the run was the no-key fallback, stop here: hand over the dump, the
checklist results, and the switch-to-live steps. That is a complete
deliverable.

## The live smoke test

With a key available:

1. Unset `AGENTSIGHT_FILE_EXPORTER` (set, it means nothing is transmitted —
   also the last line of the ship checklist).
2. Run once with the environment set to `development`.
3. Watch the logs: `init()` returning `True` is not key validation — the
   background check is what reports a refused key, an inactive subscription,
   or a read-role key (recording needs write).
4. In the dashboard, toggle **Development Mode**: it shows which metrics are
   receiving data instead of charts — confirmation the integration is
   landing, without test runs skewing production numbers. The recorded
   conversation's transcript is viewable there too.
5. Only then flip the deployment to `production`. Development data is
   excluded from analytics by design, so a deployment left on `development`
   looks like silence — say so in the report, next to where the environment
   is configured.

## What the final report contains

- What was instrumented, file by file, and the one-sentence justification for
  each explicit call (why `wrap()` here, why explicit messages, why this
  function is not decorated).
- Which interview defaults were taken, verbatim from `AGENTSIGHT.md`.
- **Named gaps** — escalation not renamed, feedback not wired,
  `open_conversation()` unreachable, direct-call models untracked — each with
  the single change that would close it.
- The verification evidence: which checklist items passed, on which dump.
- The ship checklist state: shutdown wired · environment per deployment ·
  `export_interval_ms` vs worker count · file exporter unset in production.
