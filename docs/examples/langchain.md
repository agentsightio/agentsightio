---
outline: deep
---

<CopyMarkdownButton />

# LangChain

[`examples/05_langchain.py`](https://github.com/agentsightio/agentsightio/blob/main/examples/05_langchain.py)
demonstrates the [LangChain integration](/integrations/langchain). The SDK's
callback handler registers itself through LangChain's
`register_configure_hook(..., inheritable=True)`, so it is attached to every
run without anyone passing `callbacks=[...]` — and a tool nested inside a
chain inherits it from the parent run rather than needing its own wiring.

```bash
python examples/05_langchain.py
AGENTSIGHT_EXAMPLES_OFFLINE=1 python examples/05_langchain.py
```

Offline it uses LangChain's own fake chat model: the callback path, the run
tree and every span are real. With `OPENAI_API_KEY` set and `langchain-openai`
installed it uses a real model **and** installs the OpenAI patch, which shows
the stand-down rule — the handler emits no `llm` span for a provider a patch
already covers, so each call is counted once, not twice.

## What it runs

- **A turn with two tool calls and a chain** — `@tool`-decorated LangChain
  tools invoked directly, then a `RunnableLambda | model` chain, so the spans
  nest the way a real application's do: the work inside the chain's run
  inherits the handler from the parent.
- **A failing tool** — the span records the error.
- **Turnless spend** — a chain invoked outside any turn: spend that belongs to
  the conversation but to no single exchange.

## What to look for in the output

In `examples/traces/05_langchain/`: `tool` spans produced by LangChain's own
`@tool` decorator with no AgentSight decorator in sight, and the chain's LLM
call attributed correctly — once — whether the model is fake or real.
