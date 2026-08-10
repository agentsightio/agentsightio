"""Every exception the SDK raises.

Two rules govern what belongs here:

* The tracking surface never raises into user code (design §10). Nothing in
  ``sdk/`` outside :mod:`agentsight.sdk.uploads` should be constructing these.
* The data plane always raises, because it moves customer data and returns
  answers the caller is going to act on. Silence would be the bug.

The hierarchy is deliberately shallow — status code first, message second —
so ``except APIError`` catches everything the backend can say and the
narrower classes exist only where callers genuinely branch.
"""

from typing import Any, Dict, Optional


class AgentSightError(Exception):
    """Base class for everything this package raises."""


# --------------------------------------------------------------------------
# Configuration — raised before a request is ever attempted
# --------------------------------------------------------------------------


class ConfigurationError(AgentSightError):
    """The client cannot be built from what it was given."""


class MissingApiKeyError(ConfigurationError):
    """No API key was passed and none is in the environment."""

    def __init__(self, message: Optional[str] = None, app_url: Optional[str] = None):
        if message is None:
            from agentsight._settings import resolve_app_url

            where = app_url or resolve_app_url()
            message = (
                "No AgentSight API key. Pass api_key= or set AGENTSIGHT_API_KEY."
                f"\n\t    Find your API key at {where}/settings"
            )
        super().__init__(message)


class InvalidApiKeyError(ConfigurationError):
    """The key is present but not shaped like an AgentSight key.

    Checked locally against ``_settings.API_KEY_PATTERN`` so an obvious typo
    fails at construction rather than as a confusing 401 later. A key that
    passes this check can still be rejected by the backend — that surfaces as
    :class:`AuthenticationError`.
    """

    def __init__(self, api_key: Optional[str] = None, app_url: Optional[str] = None):
        from agentsight._settings import resolve_app_url

        where = app_url or resolve_app_url()
        super().__init__(
            f"API key is malformed: {api_key!r}. Expected the form "
            f"ags_<32 hex>_<6 hex>."
            f"\n\t    Find your API key at {where}/settings"
        )
        self.api_key = api_key


# --------------------------------------------------------------------------
# HTTP — raised from a response the backend actually sent
# --------------------------------------------------------------------------


class APIError(AgentSightError):
    """The backend answered, and the answer was an error.

    ``detail`` is the backend's own words where it gave any. Backend error
    bodies are not uniform — some carry ``detail``, some ``error``, some a DRF
    field map — so the transport normalises them into this one attribute and
    keeps the parsed body on ``response``.
    """

    def __init__(
        self,
        message: str,
        *,
        status_code: Optional[int] = None,
        detail: Optional[str] = None,
        response: Any = None,
    ):
        super().__init__(message)
        self.status_code = status_code
        self.detail = detail
        self.response = response


class AuthenticationError(APIError):
    """401. The credential was rejected.

    The backend distinguishes four cases in the message text — unknown key,
    inactive/expired/revoked key, key not linked to an agent, and no active
    subscription. Only the last gets its own class; the rest are told apart by
    reading ``detail``.
    """


class SubscriptionInactiveError(AuthenticationError):
    """401, but nothing is wrong with the key — the agent is not paid up.

    Separated because it is the one 401 that rotating a key will not fix.
    """


class PermissionDeniedError(APIError):
    """403. The key authenticated but is not allowed to do this.

    Most often a ``read``-role key attempting a write. ``AgentSight().me()``
    reports the key's own role, so this no longer has to be how a caller finds
    out — but it is still what a write attempt raises.
    """


class NotFoundError(APIError):
    """404, or a filter lookup that matched nothing."""


class ValidationError(APIError):
    """400. The request body or query was rejected.

    ``errors`` holds the DRF field map when the backend sent one. Note that
    this backend frequently raises ``ValidationError({"detail": ...})``, so a
    400 carrying only ``detail`` is still one of these — classification is by
    status code, never by the shape of the body.
    """

    def __init__(self, message: str, *, errors: Optional[Dict[str, Any]] = None, **kwargs):
        super().__init__(message, **kwargs)
        self.errors = errors or {}


class MethodNotAllowedError(APIError):
    """405. Several routes here disable verbs a router would otherwise expose."""


class RateLimitError(APIError):
    """429. Too many requests, and the right response is to wait.

    Separate from the rest of the 4xx family because it is the only one where
    the request was *fine* — nothing about retrying the identical call is
    wrong, which is the opposite of every other client error here.

    ``retry_after`` is the server's own pacing in seconds where it sent a
    ``Retry-After`` header, and ``None`` where it did not. It is already
    normalised: the header's HTTP-date form is converted to a duration, and a
    time in the past reads as ``0.0``.
    """

    def __init__(self, message: str, *, retry_after: Optional[float] = None, **kwargs):
        super().__init__(message, **kwargs)
        self.retry_after = retry_after


class ServerError(APIError):
    """5xx, raised only once retries are exhausted."""


class NetworkError(AgentSightError):
    """The request never got an answer — DNS, connection, timeout, TLS."""


# --------------------------------------------------------------------------
# Data plane
# --------------------------------------------------------------------------


class UploadError(AgentSightError):
    """The backend refused an upload, or the network failed getting there.

    Raised by ``agentsight.upload_attachments`` — the one call in the tracking
    namespace allowed to raise, because it moves customer data rather than
    telemetry.
    """

    def __init__(
        self,
        message: str,
        status_code: Optional[int] = None,
        response: Any = None,
    ):
        super().__init__(message)
        self.status_code = status_code
        self.response = response


class ToolFailure(Exception):
    """LangChain has already turned the tool's exception into a string.

    ``end_tool_span`` records an exception rather than a message, so what
    reaches it has to be one. This carries the text the framework kept and
    invents nothing else.

    Not an :class:`AgentSightError`: it stands in for *user* code that failed,
    and is only ever recorded on a span, never raised at a caller.
    """
