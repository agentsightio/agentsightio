"""Cross-cutting behaviour the four provider modules share.

Each module was built and reviewed on its own, so the defects that live
*between* them had nobody looking: which target may suppress which, whether an
abandoned stream is freed, and whether one call can be billed twice because two
watchers both think it is theirs.
"""

import gc
import weakref

import pytest

from agentsight.sdk import instrumentation
from agentsight.sdk.instrumentation import (
    ALL_TARGETS,
    FRAMEWORK_HANDLERS,
    PROVIDER_PATCHES,
)
from agentsight.sdk.instrumentation.base import from_anthropic, provider_patch_covers


@pytest.fixture
def registry():
    """Restore the installed-target map, which is process-global."""
    saved = dict(instrumentation._installed)
    try:
        yield instrumentation._installed
    finally:
        instrumentation._installed.clear()
        instrumentation._installed.update(saved)


# ---------------------------------------------------------------------------
# A framework handler is not a provider patch
# ---------------------------------------------------------------------------


def test_every_target_is_one_kind_or_the_other():
    assert set(PROVIDER_PATCHES) | set(FRAMEWORK_HANDLERS) == set(ALL_TARGETS)
    assert not set(PROVIDER_PATCHES) & set(FRAMEWORK_HANDLERS)


@pytest.mark.parametrize("handler", FRAMEWORK_HANDLERS)
def test_a_framework_handler_cannot_cover_a_call(registry, handler):
    """Otherwise the handler silences the very calls it exists to record.

    An app that reports its system as "langchain" — which is what a chain with
    no identifiable model does — would go unrecorded the moment the LangChain
    handler was installed, because the coverage check would see its own name in
    the registry and stand down.
    """
    registry[handler] = True
    assert provider_patch_covers(handler) is False


@pytest.mark.parametrize("patch", PROVIDER_PATCHES)
def test_a_provider_patch_covers_its_own_system_only_once_installed(registry, patch):
    registry.pop(patch, None)
    assert provider_patch_covers(patch) is False
    registry[patch] = True
    assert provider_patch_covers(patch) is True


def test_an_unidentified_system_is_never_covered(registry):
    registry.update({name: True for name in ALL_TARGETS})
    for system in ("unknown", "bedrock", "vertex", "ollama", "", None):
        assert provider_patch_covers(system) is False, (
            "a system we do not patch must be recorded by whoever saw it"
        )


# ---------------------------------------------------------------------------
# Providers that ride on a patched SDK
# ---------------------------------------------------------------------------


def test_openai_compatible_providers_stand_down_for_the_openai_patch(registry):
    """`ChatDeepSeek` and friends subclass `BaseChatOpenAI`: the call goes out
    through the patched `openai` SDK, so both watchers would bill it."""
    from agentsight.sdk.instrumentation.langchain_handler import _COVERED_BY

    registry["openai"] = True
    for provider in ("deepseek", "xai", "together", "fireworks"):
        assert provider_patch_covers(_COVERED_BY.get(provider, provider)) is True

    registry.pop("openai")
    for provider in ("deepseek", "xai"):
        assert provider_patch_covers(_COVERED_BY.get(provider, provider)) is False, (
            "with no openai patch installed the handler is the only watcher"
        )


def test_riding_on_a_patch_does_not_rename_the_system():
    """Suppression and identity are different questions. A DeepSeek call is
    covered by the OpenAI patch, but it is not an OpenAI call."""
    from agentsight.sdk.instrumentation.langchain_handler import (
        _COVERED_BY,
        _SYSTEM_ALIASES,
    )

    assert "deepseek" not in _SYSTEM_ALIASES
    assert _COVERED_BY["deepseek"] == "openai"
    # Azure is the one case where renaming is right: it really is OpenAI.
    assert _SYSTEM_ALIASES["azure"] == "openai"


# ---------------------------------------------------------------------------
# Anthropic reasoning tokens
# ---------------------------------------------------------------------------


class _Usage:
    def __init__(self, **fields):
        self.input_tokens = 100
        self.output_tokens = 50
        self.cache_read_input_tokens = 0
        self.cache_creation_input_tokens = 0
        self.__dict__.update(fields)


def test_anthropic_reasoning_is_zero_when_the_api_reports_nothing():
    """Today's shape. Extended thinking is billed inside output_tokens with no
    breakdown, and a fabricated split would be worse than none."""
    assert from_anthropic(_Usage())["reasoning_tokens"] == 0


def test_anthropic_reasoning_is_read_if_it_ever_appears():
    """Forward compatibility, not a claim that the field exists."""
    usage = _Usage(output_tokens_details={"thinking_tokens": 30})
    normalized = from_anthropic(usage)
    assert normalized["reasoning_tokens"] == 30
    assert normalized["output_tokens"] == 50, (
        "reasoning is a subset of output, so finding it must not change the total"
    )


# ---------------------------------------------------------------------------
# Streams must not be kept alive by their own instrumentation
# ---------------------------------------------------------------------------


class _FakeStream:
    """Enough of a provider stream to exercise the close hook."""

    def __init__(self):
        self.closed = False
        self._iterator = iter(["a", "b"])

    def close(self):
        self.closed = True

    def __iter__(self):
        return self._iterator


@pytest.mark.parametrize(
    "end_on_close",
    [
        pytest.param("openai_patch", id="openai"),
        pytest.param("anthropic_patch", id="anthropic"),
    ],
)
def test_the_close_hook_does_not_put_the_stream_in_a_reference_cycle(end_on_close):
    """A hook that closes over ``stream.close`` makes the stream unreachable
    only to the *cyclic* collector — reintroducing exactly the delay the hook
    exists to remove, on the path where the user drops the stream instead of
    closing it.
    """
    import importlib

    module = importlib.import_module(
        f"agentsight.sdk.instrumentation.{end_on_close}"
    )

    stream = _FakeStream()
    closed = []
    module._end_on_close(stream, lambda: closed.append(True), _SilentLogger())

    ref = weakref.ref(stream)
    gc.disable()
    try:
        del stream
        assert ref() is None, "refcount alone must reclaim the stream"
    finally:
        gc.enable()


@pytest.mark.parametrize("module_name", ["openai_patch", "anthropic_patch"])
def test_the_close_hook_still_closes_both_halves(module_name):
    import importlib

    module = importlib.import_module(
        f"agentsight.sdk.instrumentation.{module_name}"
    )

    stream = _FakeStream()
    closed = []
    module._end_on_close(stream, lambda: closed.append(True), _SilentLogger())

    stream.close()
    assert closed == [True], "the wrapper generator ends first"
    assert stream.closed is True, "and the provider's own close still runs"


def test_a_failing_iterator_close_does_not_stop_the_provider_close():
    from agentsight.sdk.instrumentation import openai_patch

    stream = _FakeStream()

    def explode():
        raise RuntimeError("generator close failed")

    openai_patch._end_on_close(stream, explode, _SilentLogger())
    stream.close()
    assert stream.closed is True


class _SilentLogger:
    def debug(self, *args, **kwargs):
        pass

    def warning(self, *args, **kwargs):
        pass
