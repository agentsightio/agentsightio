"""The LlamaIndex handler — tool calls a provider patch cannot see.

This is the integration that exists because decorating is not always possible.
In a real agent the tools are `BaseToolSpec` methods registered through
`to_tool_list()`, which introspects each method's signature and docstring to
build the schema the model sees; putting `@agentsight.tool` on them means
editing every class and risking the agent's own behaviour. Registering with
the framework's dispatcher instead costs the user nothing.

Offline it uses LlamaIndex's own `MockLLM`, so the dispatcher, the handler and
every span are real — only the model is fake. With `OPENAI_API_KEY` set it
uses a real OpenAI model *and* installs the OpenAI patch, which demonstrates
the rule that keeps the two integrations from double-counting: the handler
stands down on LLM spans for any provider a patch already covers, so you still
get exactly one `llm` span per call.

    python examples/04_llama_index.py
    AGENTSIGHT_EXAMPLES_OFFLINE=1 python examples/04_llama_index.py
"""

import _common  # noqa: F401  — puts the repository root on sys.path
from llama_index.core.llms import ChatMessage, MockLLM
from llama_index.core.tools import FunctionTool

import agentsight as ags


def multiply(a: int, b: int) -> int:
    """Multiply two numbers."""
    return a * b


def lookup_order(order_id: str) -> str:
    """Look up an order by id."""
    return f"{order_id}: ships tomorrow"


def broken_tool(query: str) -> str:
    """Always fails, to show what a failed tool call records."""
    raise RuntimeError("upstream inventory service is down")


def main() -> None:
    live = _common.live("OPENAI_API_KEY")
    # With a real provider, install its patch too — that combination is the
    # one worth proving, and it is what a real deployment runs.
    targets = ["llama_index", "openai"] if live else ["llama_index"]
    run = _common.start("04_llama_index", auto_instrument=targets)

    if live:
        from llama_index.llms.openai import OpenAI

        llm = OpenAI(model="gpt-4o-mini")
    else:
        llm = MockLLM(max_tokens=24)

    tools = [
        FunctionTool.from_defaults(fn=multiply),
        FunctionTool.from_defaults(fn=lookup_order),
        FunctionTool.from_defaults(fn=broken_tool),
    ]
    by_name = {t.metadata.name: t for t in tools}

    with ags.conversation("demo-llamaindex", customer_id="user-99", source="web"):
        with ags.turn("ask"):
            ags.user_message("What is 6 times 7, and where is order A-1?")

            # Called directly rather than through an agent loop: an agent has
            # to be *persuaded* to call a tool, which needs a real model and
            # makes the example about prompt luck instead of instrumentation.
            product = by_name["multiply"].call(a=6, b=7)
            order = by_name["lookup_order"].call(order_id="A-1")

            answer = llm.chat([ChatMessage(role="user", content="summarise")])
            ags.agent_message(f"{product} — and {order}. ({answer.message.content})")

        with ags.turn("tool-failure"):
            ags.user_message("check stock")
            try:
                by_name["broken_tool"].call(query="widgets")
            except Exception as exc:
                # LlamaIndex may hand the failure back as a ToolOutput rather
                # than raise; either way the span records is_error.
                print(f"tool failed as intended: {type(exc).__name__}")
            ags.agent_message("Inventory is unavailable right now.")

        # A completion outside any turn — the background summarisation kind of
        # call that quietly accumulates spend nobody attributes to a user.
        llm.complete("summarise the conversation so far")

    run.finish()


if __name__ == "__main__":
    main()
