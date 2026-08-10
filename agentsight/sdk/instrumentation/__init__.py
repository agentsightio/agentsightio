"""Automatic capture of LLM and framework activity.

Four integrations, two mechanisms:

* **Provider patches** (OpenAI, Anthropic) wrap the SDK's own methods. They see
  every call, including ones a framework makes on the user's behalf.
* **Framework handlers** (LangChain, LlamaIndex) register with the framework's
  callback system. They see tool calls as well as tokens, which the provider
  patches cannot.

Running both at once is normal and does not double-count: a LangChain app on
OpenAI produces one ``llm`` span from the patch and ``tool`` spans from the
handler. The handler deliberately does not emit LLM spans for providers we
already patch — see ``langchain_handler.py``.

Framework handlers emitting **tool** spans is not an optimisation, it is the
only thing that works for some users. In ``webtasy`` the tools are
``BaseToolSpec`` methods registered through ``to_tool_list()``, which
introspects each method's signature and docstring to build the schema the LLM
sees — decorating them means editing 15+ classes and risking the agent's own
behaviour.
"""

from typing import Any, Callable, Dict

from agentsight.sdk.instrumentation.base import (  # noqa: F401  (public surface)
    capturing,
    end_tool_span,
    from_anthropic,
    from_openai,
    record_llm_call,
    start_tool_span,
)
#: Targets that patch a provider SDK and read its own usage object. These are
#: the only names ``provider_patch_covers()`` may answer True for: a framework
#: handler is not a provider, and treating "langchain" as one would silence
#: every call from an app that reports itself that way.
PROVIDER_PATCHES = ("openai", "anthropic")

#: Targets that register with a framework's callback system. They see tool
#: calls, which no provider patch can, and stand down on LLM spans for any
#: system a provider patch above already covers.
FRAMEWORK_HANDLERS = ("langchain", "llama_index")

#: Everything ``init(auto_instrument=True)`` tries. Order is irrelevant — each
#: is installed independently and a failure in one never affects the others.
ALL_TARGETS = PROVIDER_PATCHES + FRAMEWORK_HANDLERS

#: Aliases, so ``auto_instrument=["llamaindex"]`` does what it obviously means.
_ALIASES = {
    "llamaindex": "llama_index",
    "llama-index": "llama_index",
    "claude": "anthropic",
    "openai_agents": "openai",
}


def _installer(target: str) -> Callable[[Any], None]:
    """Imported lazily so a missing provider package costs nothing at import."""
    if target == "openai":
        from agentsight.sdk.instrumentation.openai_patch import install_openai

        return install_openai
    if target == "anthropic":
        from agentsight.sdk.instrumentation.anthropic_patch import install_anthropic

        return install_anthropic
    if target == "langchain":
        from agentsight.sdk.instrumentation.langchain_handler import install_langchain

        return install_langchain
    if target == "llama_index":
        from agentsight.sdk.instrumentation.llama_index_handler import (
            install_llama_index,
        )

        return install_llama_index
    raise ValueError(f"unknown instrumentation target: {target}")


#: Targets already installed in this process, so a second ``init()`` — or a
#: target named twice — cannot stack a patch on a patch and double the tokens.
_installed: Dict[str, bool] = {}


def install(target: str, logger: Any) -> None:
    """Install one target. Raises; the caller logs and carries on.

    Raising rather than swallowing is intentional at this level: ``core.py``
    turns the exception into a debug line, and having the reason available
    there is what makes "why are my tokens missing" answerable.
    """
    resolved = _ALIASES.get(target, target)
    if _installed.get(resolved):
        return
    _installer(resolved)(logger)
    _installed[resolved] = True


def installed_targets() -> Dict[str, bool]:
    """Which auto-instrumentation targets actually installed.

    A provider that is not importable is skipped at debug level, so this is
    how you tell "the patch is on" from "the patch quietly never loaded".
    Used by the tests and by the example scripts.
    """
    return dict(_installed)


def _reset_for_tests() -> None:
    _installed.clear()
