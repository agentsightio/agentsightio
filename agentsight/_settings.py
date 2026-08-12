"""Constants and resolvers shared by both planes.

Nothing in this module raises, performs I/O, or imports anything from the
package. That is the whole point of its existence.

It exists because ``init()`` must never raise into user code (design §10), so
the tracking plane cannot import anything that validates on construction. Both
planes need the same key pattern, default hosts, auth header, URL joiner and
environment slugs; without a shared home that cannot raise, each side writes
them out again and the two drift.
"""

import os
import re
import threading
from typing import Iterable, Optional

#: ``ags_`` + 32 hex + ``_`` + a 6-hex checksum. The backend rejects anything
#: else before it touches the database, so matching here saves a round trip.
API_KEY_PATTERN = re.compile(r"^ags_[a-f0-9]{32}_[a-f0-9]{6}$", re.IGNORECASE)

DEFAULT_ENDPOINT = "https://api.agentsight.io"
DEFAULT_APP_URL = "https://app.agentsight.io"

ENV_API_KEY = "AGENTSIGHT_API_KEY"
ENV_ENDPOINT = "AGENTSIGHT_API_ENDPOINT"
ENV_APP_URL = "AGENTSIGHT_APP_URL"
ENV_ENVIRONMENT = "AGENTSIGHT_ENVIRONMENT"

SDK_NAME = "agentsight-python"

# The installed distribution's version, so the wire always reports what is
# actually running. The fallback covers a source checkout that was never
# pip-installed and must track pyproject.toml by hand.
try:
    from importlib.metadata import version as _distribution_version

    SDK_VERSION = _distribution_version("agentsight")
except Exception:  # pragma: no cover - PackageNotFoundError in dev checkouts
    SDK_VERSION = "0.1.0"

USER_AGENT = f"{SDK_NAME}/{SDK_VERSION}"

#: The **offline fallback**, not the authority. Every agent is created with
#: exactly these two, and ingest rejects anything else with a 400 that takes
#: the whole batch down with it, so validating locally is what keeps a typo in
#: ``AGENTSIGHT_ENVIRONMENT`` from silently costing every batch.
#:
#: Agents can carry more than the pair: custom ``AgentEnvironment`` rows exist
#: server-side, and ``GET /api/me/`` lists them. This module still performs no
#: I/O and ``init()`` must never raise into user code, so the tracking plane
#: cannot make a network call to find out what it is allowed to send. Instead
#: the key preflight — which already makes that call — feeds what it learns
#: into :func:`learn_environments`; until it has, the pair below is what the
#: tracking plane assumes when it cannot ask. ``AgentSight().environments()``
#: remains the authoritative list for anyone checking by hand.
#:
#: The shorthand is a convenience the backend accepts on query params but
#: never stores.
PRODUCTION = "production"
DEVELOPMENT = "development"
KNOWN_ENVIRONMENTS = (PRODUCTION, DEVELOPMENT)
ENVIRONMENT_ALIASES = {"prod": PRODUCTION, "dev": DEVELOPMENT}

#: The slugs the SDK will currently put on the wire: the fallback pair plus
#: whatever the preflight has confirmed. It only ever widens. Locked because
#: the preflight writes from its own thread while every request thread reads
#: through :func:`normalize_environment`.
_environments_lock = threading.Lock()
_allowed_environments = set(KNOWN_ENVIRONMENTS)


def learn_environments(slugs: Iterable[object]) -> None:
    """Widen the allowed set with slugs the backend confirmed exist.

    Fed by the key preflight from ``/api/me/``. Additive only — nothing is
    ever removed, so the fallback pair keeps working whatever the backend
    reports. Junk input (a wrong shape, ``None``, empty strings) is dropped
    without raising: this runs on a thread nobody joins, and the module's
    contract is that nothing in it raises.
    """
    try:
        cleaned = {
            str(slug).strip().lower()
            for slug in slugs
            if slug is not None and str(slug).strip()
        }
    except Exception:
        return
    if not cleaned:
        return
    with _environments_lock:
        _allowed_environments.update(cleaned)


def allowed_environments() -> "tuple[str, ...]":
    """A sorted snapshot of what :func:`normalize_environment` accepts now.

    For log lines that name the set. A snapshot rather than a view, because
    the live set can grow between the read and the print.
    """
    with _environments_lock:
        return tuple(sorted(_allowed_environments))


def _reset_environments_for_tests() -> None:
    with _environments_lock:
        _allowed_environments.clear()
        _allowed_environments.update(KNOWN_ENVIRONMENTS)


#: Optional backend behaviours, learned the same way the environments are:
#: ``GET /api/me/`` advertises them, the key preflight records them here, and
#: nothing is assumed until it has. ``gzip-ingest`` is the one that exists
#: today — ``POST /api/ingest/`` accepts ``Content-Encoding: gzip``.
GZIP_INGEST = "gzip-ingest"

_capabilities_lock = threading.Lock()
_capabilities: "set[str]" = set()


def learn_capabilities(names: Iterable[object]) -> None:
    """Record behaviours the backend advertised on ``GET /api/me/``.

    Fed by the key preflight. Additive only, and strict about shape: the
    published wire form is a list of strings, and only that teaches anything.
    A backend that shapes the field differently — a dict, a bare string
    (iterable, character by character!), ``None`` — must not enrich the set,
    because a capability learned by accident turns into an encoding some
    backend cannot decode. Nothing here raises: this runs on a thread nobody
    joins, and the module's contract forbids it.
    """
    if isinstance(names, (str, bytes, dict)):
        return
    try:
        cleaned = {
            name.strip().lower()
            for name in names
            if isinstance(name, str) and name.strip()
        }
    except Exception:
        return
    if not cleaned:
        return
    with _capabilities_lock:
        _capabilities.update(cleaned)


def has_capability(name: str) -> bool:
    """Whether the preflight has seen the backend advertise ``name``.

    ``False`` means *not confirmed*, not *absent*: with the preflight
    disabled, unreachable, or talking to a backend that predates the
    capability list, this stays ``False`` — so a caller branching on it must
    fall back to behaviour every backend accepts.
    """
    with _capabilities_lock:
        return name in _capabilities


def _reset_capabilities_for_tests() -> None:
    with _capabilities_lock:
        _capabilities.clear()


def resolve_api_key(explicit: Optional[str] = None) -> Optional[str]:
    """An explicit key wins over the environment. Blank is the same as absent."""
    key = explicit if explicit is not None else os.getenv(ENV_API_KEY)
    if key is not None:
        key = key.strip()
    return key or None


def resolve_endpoint(explicit: Optional[str] = None) -> str:
    endpoint = explicit if explicit is not None else os.getenv(ENV_ENDPOINT)
    endpoint = (endpoint or "").strip()
    return endpoint or DEFAULT_ENDPOINT


def resolve_app_url(explicit: Optional[str] = None) -> str:
    app_url = explicit if explicit is not None else os.getenv(ENV_APP_URL)
    app_url = (app_url or "").strip()
    return app_url or DEFAULT_APP_URL


def resolve_environment(explicit: Optional[str] = None) -> Optional[str]:
    environment = explicit if explicit is not None else os.getenv(ENV_ENVIRONMENT)
    if environment is not None:
        environment = environment.strip()
    return environment or None


def normalize_environment(value: Optional[str]) -> Optional[str]:
    """The canonical slug for a supplied environment, or ``None`` if unknown.

    Mirrors what the backend does before it looks the row up: strip, lowercase,
    and map the ``prod``/``dev`` shorthand onto the stored long form. Returning
    ``None`` for an unrecognised value is what lets the callers refuse to put
    it on the wire — ingest would 400 the entire payload over it.

    "Unrecognised" means absent from the *learned* set: the fallback pair plus
    whatever the key preflight has confirmed via :func:`learn_environments`.
    The answer for a custom slug therefore changes from ``None`` to the slug
    once the preflight lands — a caller that caches it caches the pessimistic
    answer.
    """
    if value is None:
        return None
    slug = str(value).strip().lower()
    if not slug:
        return None
    slug = ENVIRONMENT_ALIASES.get(slug, slug)
    with _environments_lock:
        return slug if slug in _allowed_environments else None


def is_valid_api_key(api_key: Optional[str]) -> bool:
    if not api_key:
        return False
    return bool(API_KEY_PATTERN.match(api_key))


def auth_header(api_key: str) -> str:
    """The one place the wire format of the credential is written down.

    The backend matches on the literal keyword ``Api-Key`` — not ``Bearer``,
    not ``X-API-Key``.
    """
    return f"Api-Key {api_key}"


def join_url(endpoint: str, path: str) -> str:
    """Join a base URL and an API path exactly once.

    The backend runs with ``APPEND_SLASH = False``, so a path's trailing slash
    is load-bearing and is preserved here. Only the seam is normalised, which
    is what stops an endpoint configured as ``https://api.example.com/`` from
    producing ``https://api.example.com//api/conversations/``.
    """
    return f"{endpoint.rstrip('/')}/{path.lstrip('/')}"
