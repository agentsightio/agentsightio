"""The one HTTP path to the AgentSight API.

Before this existed the package spoke to the same backend three different ways
— the legacy client, the span exporter and the attachment uploader — each with
its own session, its own retry rule and its own hand-written ``Api-Key``
header. This is the replacement for the first and third of those. The exporter
keeps its own loop deliberately: it runs on the batch processor's background
thread and must return ``FAILURE`` rather than raise, which is the opposite of
what everything here does.

Two entry points, because the two callers want different things:

``request()``   parses the body and raises the exception taxonomy. This is what
                the ``agentsight.api`` resources use.
``raw()``       hands back the :class:`requests.Response` untouched. This is
                what :mod:`agentsight.sdk.uploads` uses, because it owes its
                callers ``UploadError`` and does its own status handling.

Both share the session, the auth header, the URL joining and the retry policy.
"""

import email.utils
import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import requests

from agentsight import _settings
from agentsight.exceptions import (
    APIError,
    AuthenticationError,
    MethodNotAllowedError,
    NetworkError,
    NotFoundError,
    PermissionDeniedError,
    RateLimitError,
    ServerError,
    SubscriptionInactiveError,
    ValidationError,
)

# The stdlib logger, configured by the host application and nothing else. The
# SDK never installs handlers or sets ``propagate``: a library that configures
# logging silences itself for anyone who already configured it themselves.
logger = logging.getLogger("agentsight")

#: Backoff before retry attempt N, in seconds. Same shape the span exporter
#: uses, so the two planes behave alike under a flaky backend.
_BACKOFF = (0.5, 2.0)

#: Ceiling on a server-supplied ``Retry-After``. Waiting is better than
#: failing, but a caller blocked inside a library call has no way to change
#: its mind, so there is a limit past which raising and letting them decide is
#: the more honest answer.
MAX_RETRY_AFTER = 30.0

_SUCCESS = (200, 201, 202, 204)


def retry_after(
    response: requests.Response, cap: float = MAX_RETRY_AFTER
) -> Optional[float]:
    """The server's own pacing, in seconds, or ``None`` if it did not say.

    Lives here rather than in either retry loop because both planes need it and
    neither owns it: :class:`Transport` retries GETs with it, and the span
    exporter — which keeps its own loop on purpose — imports it for the same
    reason. Written once so the two cannot drift.

    RFC 9110 allows two spellings and both are in the wild: a count of seconds,
    and an HTTP-date. DRF sends the first; a proxy in front of it may rewrite to
    the second, so parsing only one is how this silently stops working.

    Clamped into ``[0, cap]`` — a past date means "now", and an unparseable
    header means ``None`` rather than an exception, because every caller is
    somewhere that would rather wait a default than fail.
    """
    raw = response.headers.get("Retry-After")
    if not raw:
        return None

    raw = raw.strip()
    try:
        seconds = float(raw)
    except ValueError:
        try:
            parsed = email.utils.parsedate_to_datetime(raw)
        except (TypeError, ValueError):
            return None
        if parsed is None:  # pragma: no cover — 3.10+ raises instead of returning
            return None
        if parsed.tzinfo is None:
            # A date with no zone is UTC by RFC 9110; reading it as local time
            # would shift the wait by the host's offset.
            parsed = parsed.replace(tzinfo=timezone.utc)
        seconds = (parsed - datetime.now(tz=timezone.utc)).total_seconds()

    return max(0.0, min(seconds, cap))


class Transport:
    """A pooled, authenticated connection to one AgentSight backend."""

    DEFAULT_TIMEOUT = 15
    DEFAULT_MAX_RETRIES = 3

    def __init__(
        self,
        api_key: str,
        endpoint: str,
        *,
        timeout: float = DEFAULT_TIMEOUT,
        max_retries: int = DEFAULT_MAX_RETRIES,
    ):
        self.endpoint = endpoint
        self.timeout = timeout
        self.max_retries = max(1, max_retries)
        self._session = requests.Session()
        self._session.headers.update(
            {
                "Authorization": _settings.auth_header(api_key),
                "Content-Type": "application/json",
                # Without this the browsable API renderer is free to answer
                # with HTML, which turns every parse into a confusing failure.
                "Accept": "application/json",
                "User-Agent": _settings.USER_AGENT,
            }
        )

    # -- public ------------------------------------------------------------

    def request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        json: Any = None,
        timeout: Optional[float] = None,
    ) -> Any:
        """Send a request, returning the parsed body or raising."""
        response = self.raw(
            method, path, params=params, json=json, timeout=timeout
        )
        if response.status_code in _SUCCESS:
            return _body(response)
        raise _error_for(response)

    def raw(
        self,
        method: str,
        path: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        json: Any = None,
        timeout: Optional[float] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        """Send a request and hand back the response, whatever its status.

        Retries are applied here so both entry points get them, and only to
        GET: writes are never replayed automatically. Most creates are not
        idempotent — a replayed ``POST /api/feedbacks/`` files a second row
        for every kind except message feedback, whose create updates the one
        vote per message and is the single write a caller may safely retry by
        hand. So a write that comes back throttled is raised as
        :class:`RateLimitError` carrying ``retry_after``, and the caller
        decides. A GET has no such problem and is retried, honouring
        ``Retry-After`` when the server sends one.
        """
        method = method.upper()
        url = _settings.join_url(self.endpoint, path)
        retryable = method == "GET"
        attempts = self.max_retries if retryable else 1
        last_exc: Optional[Exception] = None

        for attempt in range(attempts):
            try:
                response = self._session.request(
                    method,
                    url,
                    params=params,
                    json=json,
                    headers=headers,
                    timeout=timeout if timeout is not None else self.timeout,
                )
            except requests.RequestException as exc:
                last_exc = exc
                if attempt + 1 >= attempts:
                    break
                self._sleep(attempt, f"{method} {url}", str(exc))
                continue

            if retryable and attempt + 1 < attempts:
                if response.status_code >= 500:
                    self._sleep(
                        attempt, f"{method} {url}", f"HTTP {response.status_code}"
                    )
                    continue
                if response.status_code == 429:
                    self._sleep(
                        attempt,
                        f"{method} {url}",
                        "HTTP 429 (throttled)",
                        override=retry_after(response),
                    )
                    continue

            return response

        raise NetworkError(
            f"{method} {url} failed after {attempts} attempt(s): {last_exc}"
        ) from last_exc

    def close(self) -> None:
        self._session.close()

    # -- internals ---------------------------------------------------------

    def _sleep(
        self, attempt: int, what: str, why: str, *, override: Optional[float] = None
    ) -> None:
        """Wait before the next attempt.

        ``override`` is the server's own ``Retry-After`` where it sent one; it
        wins over the fixed curve, because the backend knows its own budget and
        we are only guessing.
        """
        delay = override if override is not None else _BACKOFF[
            min(attempt, len(_BACKOFF) - 1)
        ]
        logger.warning("%s failed (%s); retrying in %ss", what, why, delay)
        time.sleep(delay)


# --------------------------------------------------------------------------
# Response handling
# --------------------------------------------------------------------------


def _body(response: requests.Response) -> Any:
    """Parsed JSON, or ``{}`` for the empty bodies DELETE and 204 return."""
    if not response.content:
        return {}
    try:
        return response.json()
    except ValueError:
        return {}


def _detail(body: Any, response: requests.Response) -> str:
    """The backend's own words, wherever it chose to put them.

    Three shapes are in use: DRF's ``detail``, the hand-rolled ``error`` that
    the attachments and buttons views return, and a plain field map from
    serializer validation. Anything else falls back to the raw text.
    """
    if isinstance(body, dict):
        for key in ("detail", "error"):
            value = body.get(key)
            if isinstance(value, str) and value:
                return value
        fields = []
        for field, errors in body.items():
            if field == "details":
                continue
            if isinstance(errors, (list, tuple)):
                fields.append(f"{field}: {', '.join(str(e) for e in errors)}")
            else:
                fields.append(f"{field}: {errors}")
        if fields:
            return "; ".join(fields)
    elif isinstance(body, list) and body:
        return "; ".join(str(item) for item in body)

    return (response.text or "").strip()[:500] or "no detail"


def _error_for(response: requests.Response) -> APIError:
    """Map a failed response onto the exception taxonomy.

    Classification is by status code first. That matters because this backend
    frequently raises ``ValidationError({"detail": ...})``, so the presence of
    a ``detail`` key says nothing about which kind of error it is.
    """
    status = response.status_code
    body = _body(response)
    detail = _detail(body, response)
    message = f"{status} {detail}"
    kwargs = {"status_code": status, "detail": detail, "response": body}

    if status == 400:
        errors = body if isinstance(body, dict) else {}
        return ValidationError(message, errors=errors, **kwargs)
    if status == 401:
        # The one 401 that rotating a key will not fix.
        if "subscription" in detail.lower():
            return SubscriptionInactiveError(message, **kwargs)
        return AuthenticationError(message, **kwargs)
    if status == 403:
        return PermissionDeniedError(message, **kwargs)
    if status == 404:
        return NotFoundError(message, **kwargs)
    if status == 405:
        return MethodNotAllowedError(message, **kwargs)
    if status == 429:
        # Ingest is throttled per agent, and every worker in a deployment
        # spends from the same allowance — so this is reachable without the
        # caller having done anything wrong, and `retry_after` is the only
        # part of the answer they can act on.
        return RateLimitError(message, retry_after=retry_after(response), **kwargs)
    if status >= 500:
        return ServerError(message, **kwargs)
    return APIError(message, **kwargs)
