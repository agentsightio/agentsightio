---
outline: deep
---

<CopyMarkdownButton />

# What gets traced & why

AgentSight records a small set of things, and each one is shaped after something real in your product — a customer's thread, an exchange, a click — rather than after your call stack. This page is the product-level tour: what each thing is, and *why it is captured the way it is*. For the exact bytes on the wire, see [What the SDK sends](/getting-started/what-the-sdk-sends).

## Conversations

A conversation is a **business entity, not a trace**. A WhatsApp thread, a support session, a week of back-and-forth with one customer: it can last hours or days, survive restarts and deploys, and pass through as many processes as your architecture involves. It is identified by a string **you** control — whatever id your own system already uses for that thread — so your data and AgentSight's agree on what "this conversation" means without a mapping table.

That is why it is not modelled as a trace: a trace lives as long as a request, but a conversation lives as long as the customer's problem. A conversation also carries the business context worth filtering by — customer, device, language, and free-form metadata you can update as the conversation unfolds.

## Turns

A turn is **one exchange**: the user asks, the agent works, the agent answers. Its duration *is* your answer latency — measured, not approximated. Everything the agent did to produce the answer — tool calls, LLM calls — nests inside the turn, so "how much of the wait was tools, and how much was the model?" is answerable for free, for every exchange, without any extra instrumentation.

## Messages

A message is a **point in time**: something was said, by the user or by the agent. Record as many as you like, in any order, from either sender — a burst of three user messages, an answer followed by a card, an exchange where the agent silently escalates and never replies. There is no required shape.

Messages are **explicit by design**. The SDK could guess at them — from your handler's arguments, from what went into the LLM — but inference would put the *wrong text* into a transcript your client reads: a rewritten prompt instead of what the human typed, an image description instead of the image caption they wrote. Being explicit here is a correctness guarantee, not a missing feature.

## Tools & tasks

Tools and tasks are **units of work with measured durations**. A *tool* is something the agent calls out to — a search, an order lookup, a payment API. A *task* is internal work — parsing a document, reranking results. Decorate the function and the SDK records when it started, when it ended, what it was called with, and what it returned — or the error it raised. They appear as actions on the dashboard, so "what did the agent actually do?" has an answer your client can see.

## LLM calls, tokens & cost

Every LLM call inside a conversation is **counted automatically** — including the evaluator, router, and classifier calls nobody would ever hand-track, which is usually where surprising cost hides. The SDK records the token counts and the model that actually answered; **cost is priced server-side** from those figures, so when a provider's rate changes — or a published rate turns out to have been wrong — your history can be restated instead of staying frozen at whatever the SDK knew when you deployed it.

Prompts and completions are **never sent**. LLM spans carry the accounting only.

## Buttons

A click happens **in the browser, not in your call stack** — no decorator on the server can see it — so it is the one thing that takes a single explicit call when your backend hears about it. It is recorded and archived as a button interaction in its own right, not as a fake sentence injected into the transcript.

## Attachments

Files shared in a conversation, with a deliberate split:

- **`record_attachments()`** records *that* files exist — name, size, type — and moves no bytes. For files whose contents already live somewhere else.
- **`upload_attachments()`** uploads the files themselves and stores them with the conversation.

They are separate calls so that whether file contents travel is always your explicit choice.

## The wire-level view

Everything on this page is the product-level story. The complete disclosure — every attribute the SDK transmits, named with an example value and the call that produces it, what is never sent, the size limits, and the controls for suppressing capture — is in **[What the SDK sends](/getting-started/what-the-sdk-sends)**. It also shows how to see the exact payload yourself, from your own application, before anything is transmitted at all.
