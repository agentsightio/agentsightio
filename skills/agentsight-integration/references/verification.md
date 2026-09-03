# Verify before you claim done

The failure modes of this integration raise nothing: a missing `wrap()`
records confidently wrong latency, a wrong environment records into silence, a
misnamed handoff tool counts zero escalations. So the definition of done is
not "the code looks right" — it is **you ran the app and read back what it
recorded.** Never report the integration finished without this loop.

The mechanics — running with `AGENTSIGHT_FILE_EXPORTER` set, the `jq` queries
over the dump, the live smoke test with Development Mode, and the
symptom→cause table — live in the base skill:
[../../agentsight/references/debugging.md](../../agentsight/references/debugging.md).
Run that loop, exercising the app through its real transport (HTTP call,
webhook payload, websocket message) — not by importing the handler and
calling it. This file is the checklist that turns the dump into a verdict
against what the interview promised.

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
   arguments, the unhashed id). This check is the promise made in the
   data-consent question, kept.
8. **The environment tag is what the deployment intends.**

If the run was the no-key fallback, stop here: hand over the dump, the
checklist results, and the switch-to-live steps. That is a complete
deliverable. With a key, follow with the live smoke test in debugging.md —
`development` environment first, Development Mode to confirm metrics are
receiving, only then flip to `production`.

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
