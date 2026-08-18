---
outline: deep
---

<CopyMarkdownButton />

# LlamaIndex

[`examples/04_llama_index.py`](https://github.com/agentsightio/agentsightio/blob/main/examples/04_llama_index.py)
demonstrates the [LlamaIndex integration](/integrations/llamaindex) — the one
that exists because decorating is not always possible. In a real agent the
tools are `BaseToolSpec` methods registered through `to_tool_list()`, which
introspects each method's signature and docstring to build the schema the
model sees; putting `@agentsight.tool` on them means editing every class and
risking the agent's own behaviour. The SDK's handler on the framework's
dispatcher sees those tool calls without touching them.

```bash
python examples/04_llama_index.py
AGENTSIGHT_EXAMPLES_OFFLINE=1 python examples/04_llama_index.py
```

Offline it uses LlamaIndex's own `MockLLM`, so the dispatcher, the handler and
every span are real — only the model is fake. With `OPENAI_API_KEY` set it
uses a real OpenAI model **and** installs the OpenAI patch as well, which is
the combination a real deployment runs — and the one that proves the rule that
keeps the two integrations from double-counting: the handler stands down on
LLM spans for any provider a patch already covers, so each call produces
exactly one `llm` span.

## What it runs

- **A turn with two tool calls and an LLM call** — `FunctionTool` calls the
  handler observes from the dispatcher, no decorator anywhere. The tools are
  called directly rather than through an agent loop: an agent has to be
  *persuaded* to call a tool, which needs a real model and makes the example
  about prompt luck instead of instrumentation.
- **A failing tool** — LlamaIndex may hand the failure back as a `ToolOutput`
  rather than raise; either way the span records the error.
- **Turnless spend** — a completion outside any turn, the background
  summarisation kind of call that quietly accumulates spend nobody attributes
  to a user.

## What to look for in the output

In `examples/traces/04_llama_index/`: `tool` spans that exist despite no
`@agentsight.tool` anywhere in the script, the failed one marked with its
error, and — in live mode — one `llm` span per model call even with two
integrations installed.
