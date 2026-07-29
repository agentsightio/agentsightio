"""Turning arbitrary Python values into span attributes, safely.

Every function here obeys one rule: **it never raises**. Serialization runs
inside the user's call stack, so an un-encodable argument must degrade to a
placeholder rather than propagate out of a decorated function (design §10).
"""

import inspect
import json
from typing import Any, Dict, Optional, Tuple

#: Unbounded strings turn one pathological argument (a loaded DataFrame, a
#: file blob) into a multi-megabyte export. Truncation is marked, not silent.
MAX_ATTRIBUTE_LENGTH = 16_384

TRUNCATION_SUFFIX = "...[truncated]"


def truncate(value: str, limit: int = MAX_ATTRIBUTE_LENGTH) -> str:
    if len(value) <= limit:
        return value
    return value[: limit - len(TRUNCATION_SUFFIX)] + TRUNCATION_SUFFIX


class _SafeEncoder(json.JSONEncoder):
    """Falls back through common object protocols, then ``repr``."""

    def default(self, o: Any) -> Any:
        for attr in ("model_dump", "dict", "to_dict"):  # pydantic v2, v1, pandas-ish
            method = getattr(o, attr, None)
            if callable(method):
                try:
                    return method()
                except Exception:
                    pass
        try:
            return repr(o)
        except Exception:
            return f"<unrepresentable {type(o).__name__}>"


def to_json(value: Any) -> str:
    """Serialize any value to a JSON string, never raising."""
    try:
        return truncate(json.dumps(value, cls=_SafeEncoder, ensure_ascii=False))
    except Exception:
        try:
            return truncate(json.dumps(repr(value)))
        except Exception:
            return '"<unserializable>"'


def to_text(value: Any) -> str:
    """Best-effort readable string, for message content.

    Messages appear verbatim in client-facing transcripts, so a plain string
    must survive as itself rather than acquiring JSON quotes.
    """
    if value is None:
        return ""
    if isinstance(value, str):
        return truncate(value)
    try:
        return truncate(str(value))
    except Exception:
        return "<unrepresentable>"


def bind_arguments(
    func: Any,
    args: Tuple[Any, ...],
    kwargs: Dict[str, Any],
) -> Dict[str, Any]:
    """Map a call's arguments to parameter names.

    Named arguments are what make ``id_from="session_id"`` work whether the
    caller passed it positionally or by keyword.

    Falls back to positional keys for builtins and C extensions whose
    signature cannot be inspected. Callers drop ``self`` themselves, since
    only they know whether the wrapped callable is a method.
    """
    try:
        bound = inspect.signature(func).bind_partial(*args, **kwargs)
        bound.apply_defaults()
        return dict(bound.arguments)
    except Exception:
        fallback: Dict[str, Any] = {f"arg{i}": a for i, a in enumerate(args)}
        fallback.update(kwargs)
        return fallback


def first_string_argument(arguments: Dict[str, Any]) -> Optional[str]:
    """The first non-empty ``str`` argument, in declaration order.

    Only used by the opt-in ``infer=True`` shortcut. Ordering holds because
    ``bind_arguments`` returns signature order and dicts preserve insertion.
    """
    for value in arguments.values():
        if isinstance(value, str) and value.strip():
            return value
    return None
