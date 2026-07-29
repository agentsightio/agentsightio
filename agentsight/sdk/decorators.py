"""``@tool`` and ``@task`` — the decorators that replace ``track_action()``.

Both produce the same rows; they differ only in the word you use. A tool is
something the agent calls out to; a task is a unit of internal work.

Everything ``track_action()`` asked users to type by hand is measured here
instead: ``started_at`` and ``ended_at`` are the span's real boundaries,
``duration_ms`` is its real duration, ``tools_used`` is the real arguments and
``response`` is the real return value.
"""

import asyncio
import functools
from typing import Any, Callable, Optional

from opentelemetry.trace import Status, StatusCode

from agentsight.sdk import context as ags_context
from agentsight.sdk.semconv import (
    SpanAttributes,
    SpanKind,
    ToolAttributes,
)
from agentsight.sdk.serialization import bind_arguments, to_json, to_text


def _start_span(operation: str, kind: str):
    """None when the SDK is off or there is no conversation to attach to."""
    from agentsight.sdk.core import get_tracer, is_enabled

    if not is_enabled() or not ags_context.tracking_enabled():
        return None

    try:
        attributes = dict(ags_context.conversation_attributes())
        attributes[SpanAttributes.KIND] = kind
        attributes[SpanAttributes.ENTITY_NAME] = operation
        attributes[ToolAttributes.NAME] = operation
        return get_tracer().start_as_current_span(operation, attributes=attributes)
    except Exception:
        # §10: no span is a fine outcome. Not running the user's function is not.
        return None


def _record_arguments(span, func: Callable, args, kwargs) -> None:
    try:
        arguments = bind_arguments(func, args, kwargs)
        arguments.pop("self", None)
        span.set_attribute(ToolAttributes.ARGUMENTS, to_json(arguments))
    except Exception:
        pass


def _record_result(span, result: Any) -> None:
    try:
        span.set_attribute(ToolAttributes.RESPONSE, to_text(result))
        span.set_status(Status(StatusCode.OK))
    except Exception:
        pass


def _record_error(span, exc: BaseException) -> None:
    try:
        span.set_attribute(ToolAttributes.ERROR, to_text(exc))
        span.record_exception(exc)
        span.set_status(Status(StatusCode.ERROR, str(exc)))
    except Exception:
        pass


def _build(kind: str):
    """Factory for the ``@tool`` / ``@task`` pair."""

    def decorator_family(
        func: Optional[Callable] = None, *, name: Optional[str] = None
    ):
        def wrap(target: Callable) -> Callable:
            operation = name or target.__name__

            if asyncio.iscoroutinefunction(target):

                @functools.wraps(target)
                async def async_wrapper(*args, **kwargs):
                    ctx = _start_span(operation, kind)
                    if ctx is None:
                        return await target(*args, **kwargs)
                    with ctx as span:
                        _record_arguments(span, target, args, kwargs)
                        try:
                            result = await target(*args, **kwargs)
                        except BaseException as exc:
                            # The row is still written — a failed tool call is
                            # data. The exception propagates untouched.
                            _record_error(span, exc)
                            raise
                        _record_result(span, result)
                        return result

                return async_wrapper

            @functools.wraps(target)
            def sync_wrapper(*args, **kwargs):
                ctx = _start_span(operation, kind)
                if ctx is None:
                    return target(*args, **kwargs)
                with ctx as span:
                    _record_arguments(span, target, args, kwargs)
                    try:
                        result = target(*args, **kwargs)
                    except BaseException as exc:
                        _record_error(span, exc)
                        raise
                    _record_result(span, result)
                    return result

            return sync_wrapper

        if func is not None and callable(func):
            return wrap(func)  # bare @tool
        return wrap  # @tool(name=...)

    return decorator_family


#: ``@tool`` / ``@tool(name="fallback_to_human")``.
#:
#: ``name`` matters: Human Escalation Rate keys off specific action names
#: (``fallback_to_human``, ``open_ticket``, ``ticket``, ``contact_human``).
tool = _build(SpanKind.TOOL)

#: ``@task`` — identical rows, different word.
task = _build(SpanKind.TASK)
