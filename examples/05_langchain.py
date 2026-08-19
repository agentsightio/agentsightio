"""The LangChain handler — tools and LLM calls, with no wiring per call.

The handler registers itself through `register_configure_hook(..., inheritable=True)`,
so it is attached to every run without anyone passing `callbacks=[...]`, and a
tool nested inside a chain inherits it from the parent run rather than needing
its own.

Offline it uses LangChain's own fake chat model: the callback path, the run
tree and every span are real. With `OPENAI_API_KEY` set and `langchain-openai`
installed it uses a real model *and* installs the OpenAI patch, which shows the
stand-down rule — the handler emits no `llm` span for a provider a patch
already covers, so the call is counted once, not twice.

    python examples/05_langchain.py
    AGENTSIGHT_EXAMPLES_OFFLINE=1 python examples/05_langchain.py
"""

import _common  # noqa: F401  — puts the repository root on sys.path
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.runnables import RunnableLambda
from langchain_core.tools import tool

import agentsight as ags


@tool
def multiply(a: int, b: int) -> int:
    """Multiply two numbers."""
    return a * b


@tool
def lookup_order(order_id: str) -> str:
    """Look up an order by id."""
    return f"{order_id}: ships tomorrow"


@tool
def broken_tool(query: str) -> str:
    """Always fails, to show what a failed tool call records."""
    raise RuntimeError("upstream inventory service is down")


def make_model():
    if _common.live("OPENAI_API_KEY"):
        try:
            from langchain_openai import ChatOpenAI

            return ChatOpenAI(model="gpt-4o-mini"), True
        except ImportError:
            print("langchain-openai is not installed — falling back to the fake model")

    return FakeMessagesListChatModel(
        responses=[AIMessage(content="Order A-1 ships tomorrow.")]
    ), False


def main() -> None:
    model, real_provider = make_model()
    targets = ["langchain", "openai"] if real_provider else ["langchain"]
    run = _common.start("05_langchain", auto_instrument=targets)

    # A chain, so the spans nest the way a real application's do: the tool
    # call below happens inside the chain's run and inherits its handler.
    chain = RunnableLambda(lambda text: [HumanMessage(content=text)]) | model

    with ags.conversation("demo-langchain", customer_id="user-77", source="web"):
        with ags.turn("ask"):
            ags.user_message("What is 6 times 7, and where is order A-1?")

            product = multiply.invoke({"a": 6, "b": 7})
            order = lookup_order.invoke({"order_id": "A-1"})
            answer = chain.invoke("summarise the order status")

            ags.agent_message(f"{product} — and {order}. ({answer.content})")

        with ags.turn("tool-failure"):
            ags.user_message("check stock")
            try:
                broken_tool.invoke({"query": "widgets"})
            except Exception as exc:
                print(f"tool failed as intended: {type(exc).__name__}")
            ags.agent_message("Inventory is unavailable right now.")

        # Outside any turn: spend that belongs to the conversation but to no
        # single exchange.
        chain.invoke("classify the sentiment of this conversation")

    run.finish()


if __name__ == "__main__":
    main()
