"""Turning arbitrary Python values into span attributes, safely.

Every function here obeys one rule: **it never raises**. Serialization runs
inside the user's call stack, so an un-encodable argument must degrade to a
placeholder rather than propagate out of a decorated function (design §10).

The second rule is newer and just as load-bearing: **whatever ``to_json``
returns parses**. Ingest stores metadata in a JSON column, so a truncated
document that no longer parses does not lose the oversized value — it loses
every small key beside it, silently. Truncation happens per value, and the
document that comes back is always valid JSON saying what it dropped.
"""

import functools
import inspect
import ipaddress
import json
import logging
import threading
from typing import Any, Dict, List, Optional, Tuple

#: Unbounded strings turn one pathological argument (a loaded DataFrame, a
#: file blob) into a multi-megabyte export. Truncation is marked, not silent.
MAX_ATTRIBUTE_LENGTH = 16_384

TRUNCATION_SUFFIX = "...[truncated]"

#: Where ``to_json`` records what it had to drop, so a reader of the stored
#: metadata can tell "the user sent nothing" from "we could not carry it".
TRUNCATION_KEY = "_agentsight_truncated"

#: Ingest declares ``max_length=255`` on every conversation string field, and
#: it validates the whole payload at once — so one 300-character ``device``
#: rejects the batch it rode in on, including the conversations that were
#: perfectly valid. Clamping here turns a total loss into a marked one.
MAX_FIELD_LENGTH = 255

#: Per-value budgets tried in order when a document is too long. The first is
#: nearly the whole allowance, so a single large value keeps almost all of
#: itself; later ones share the allowance out when many values are large.
_LEAF_BUDGETS = (
    MAX_ATTRIBUTE_LENGTH - 64,
    MAX_ATTRIBUTE_LENGTH // 4,
    MAX_ATTRIBUTE_LENGTH // 16,
    MAX_ATTRIBUTE_LENGTH // 64,
    256,
)

logger = logging.getLogger("agentsight")

_warned: set = set()
_warn_lock = threading.Lock()


def warn_once(key: str, message: str, *args: Any) -> None:
    """One warning per distinct key for the life of the process.

    These fire from inside request handling, so the offending call is usually
    in a loop: a warning per call would bury the one line that mattered under
    thousands of copies of itself.
    """
    with _warn_lock:
        if key in _warned:
            return
        _warned.add(key)
    logger.warning(message, *args)


def _reset_warnings_for_tests() -> None:
    with _warn_lock:
        _warned.clear()


def truncate(value: str, limit: int = MAX_ATTRIBUTE_LENGTH) -> str:
    if len(value) <= limit:
        return value
    return value[: limit - len(TRUNCATION_SUFFIX)] + TRUNCATION_SUFFIX


def clamp_field(name: str, value: Optional[str]) -> Optional[str]:
    """A conversation field, cut to what ingest will accept.

    Warns once per field name, because the mistake that produces this is
    systematic — a user-agent string in ``device``, a whole prompt in
    ``name`` — and the caller needs to know the stored value is not the one
    they passed.
    """
    if value is None:
        return None
    if not isinstance(value, str):
        value = to_text(value)
    if len(value) <= MAX_FIELD_LENGTH:
        return value
    warn_once(
        "clamp:%s" % name,
        "AgentSight: conversation field %r was %d characters and has been "
        "clamped to %d; the API rejects anything longer.",
        name,
        len(value),
        MAX_FIELD_LENGTH,
    )
    return value[:MAX_FIELD_LENGTH]


def valid_ip(value: Optional[str]) -> Optional[str]:
    """The address if it parses, otherwise ``None`` and one warning.

    Ingest declares an ``IPAddressField``, so ``"unknown"`` or a comma-joined
    proxy chain rejects the whole batch. Dropping the field costs one column
    on one conversation; keeping it costs every conversation in the payload.
    """
    if value is None:
        return None
    text = value.strip() if isinstance(value, str) else str(value).strip()
    if not text:
        return None
    try:
        ipaddress.ip_address(text)
    except ValueError:
        warn_once(
            "ip",
            "AgentSight: customer_ip_address %r is not an IP address and has "
            "been dropped. If this is a forwarded-for header, take one address "
            "from it before passing it in.",
            value,
        )
        return None
    return text


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


def _dump(value: Any) -> Optional[str]:
    try:
        return json.dumps(value, cls=_SafeEncoder, ensure_ascii=False)
    except Exception:
        return None


def _truncate_leaves(value: Any, budget: int) -> Any:
    if isinstance(value, str):
        return truncate(value, budget)
    if isinstance(value, dict):
        return {key: _truncate_leaves(item, budget) for key, item in value.items()}
    if isinstance(value, list):
        return [_truncate_leaves(item, budget) for item in value]
    return value


def _fits(document: Optional[str]) -> bool:
    return document is not None and len(document) <= MAX_ATTRIBUTE_LENGTH


#: How many dropped key names the marker names before it just counts them.
#: Unbounded, the record of what was dropped grows as fast as dropping shrinks
#: the document — a metadata dict of ten thousand short keys never converges,
#: and the whole thing is lost to the fallback instead of mostly surviving.
_MAX_NAMED_DROPS = 20


def _dropped_marker(dropped: List[Any]) -> Dict[str, Any]:
    marker: Dict[str, Any] = {"dropped_count": len(dropped)}
    marker["dropped_keys"] = [str(k) for k in dropped[:_MAX_NAMED_DROPS]]
    return marker


def _drop_entries(reduced: Any) -> Optional[str]:
    """Last resort: shed whole entries, largest first, and say which."""
    if isinstance(reduced, dict):
        surviving: Dict[Any, Any] = dict(reduced)
        dropped: List[Any] = []
        order = sorted(
            surviving, key=lambda k: len(_dump(surviving[k]) or ""), reverse=True
        )
        while True:
            candidate: Dict[Any, Any] = dict(surviving)
            if dropped:
                candidate[TRUNCATION_KEY] = _dropped_marker(dropped)
            document = _dump(candidate)
            if _fits(document):
                return document
            if not order:
                return None
            key = order.pop(0)
            surviving.pop(key, None)
            dropped.append(key)

    if isinstance(reduced, list):
        items: List[Any] = list(reduced)
        while items:
            items.pop()
            marker = {TRUNCATION_KEY: "%d item(s) dropped" % (len(reduced) - len(items))}
            document = _dump(items + [marker])
            if _fits(document):
                return document
    return None


def to_json(value: Any) -> str:
    """Serialize any value to a JSON string that parses, never raising.

    Under the size limit this is a plain ``json.dumps`` and the output is
    byte-identical to what it always was. Over it, values are cut individually
    and — if that is still not enough — whole entries are shed, with both
    facts recorded in the document rather than left for the reader to infer.
    """
    document = _dump(value)
    if document is None:
        document = _dump(repr(value))
        if document is None:
            return '"<unserializable>"'
    if len(document) <= MAX_ATTRIBUTE_LENGTH:
        return document

    # Round-trip first: the parsed form holds only JSON types, so the
    # truncation walk below never has to guess how an arbitrary object will
    # encode — _SafeEncoder has already decided.
    try:
        parsed = json.loads(document)
    except Exception:  # pragma: no cover - _dump only emits parseable output
        return _dump({TRUNCATION_KEY: "%d characters dropped" % len(document)}) or "{}"

    for budget in _LEAF_BUDGETS:
        candidate = _dump(_truncate_leaves(parsed, budget))
        if candidate is not None and len(candidate) <= MAX_ATTRIBUTE_LENGTH:
            return candidate

    shed = _drop_entries(_truncate_leaves(parsed, _LEAF_BUDGETS[-1]))
    if shed is not None:
        return shed
    return _dump({TRUNCATION_KEY: "%d characters dropped" % len(document)}) or "{}"


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


#: Bounded, not ``maxsize=None``: the cache holds strong references to its
#: keys, and a caller decorating lambdas or closures in a loop would otherwise
#: pin every one of them alive for the process.
@functools.lru_cache(maxsize=1024)
def _signature_of(func: Any) -> inspect.Signature:
    return inspect.signature(func)


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
        try:
            signature = _signature_of(func)
        except TypeError:
            # Unhashable callables cannot pass through lru_cache; inspect
            # uncached so they still get real parameter names rather than
            # the positional fallback below.
            signature = inspect.signature(func)
        bound = signature.bind_partial(*args, **kwargs)
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
