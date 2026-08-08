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
from typing import Optional

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

#: Every agent is created with exactly these two environments, and ingest
#: rejects anything else with a 400 that takes the whole batch down with it.
#: The slug is the published wire value — the backend's own model says so —
#: so it is safe to hard-code, and the shorthand below is a convenience the
#: backend accepts on query params but never stores.
#:
#: This list is temporary by design. Custom environments per agent are
#: supported end to end except for the API to create and list them; when that
#: lands, this pair is replaced by a lookup against the agent's own slugs.
PRODUCTION = "production"
DEVELOPMENT = "development"
KNOWN_ENVIRONMENTS = (PRODUCTION, DEVELOPMENT)
ENVIRONMENT_ALIASES = {"prod": PRODUCTION, "dev": DEVELOPMENT}


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
    """
    if value is None:
        return None
    slug = str(value).strip().lower()
    if not slug:
        return None
    slug = ENVIRONMENT_ALIASES.get(slug, slug)
    return slug if slug in KNOWN_ENVIRONMENTS else None


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
