"""The AgentSight data plane — read and manage what tracking recorded.

Separate from the tracking surface on purpose. ``import agentsight`` starts
telemetry; this is the client you reach for when you want the data back out::

    from agentsight.api import AgentSight

    ags = AgentSight()                       # reads AGENTSIGHT_API_KEY

    for conversation in ags.conversations.list(has_feedback=True):
        print(conversation["conversation_id"], conversation["name"])

    ags.conversations.rename("wa-3859", "Refund — resolved")
    ags.feedbacks.create_for_conversation("wa-3859", "positive")

Hold as many clients as you have keys — staging and production, or two agents,
in one process.

There is also a module-level default for scripts that only ever need one::

    from agentsight.api import client

    client.conversations.list()

It is built on first use, never at import, so importing this module (or the
package) neither reads your environment nor opens a connection.
"""

from agentsight.api._client import AgentSight
from agentsight.api._pagination import Page, PageIterator

__all__ = ["AgentSight", "Page", "PageIterator", "client"]

_default = None


def __getattr__(name):
    """Build the module-level ``client`` the first time it is touched.

    PEP 562. This is what keeps ``import agentsight`` free of side effects:
    the 0.0.x clients constructed themselves at import and raised when no API
    key was set, so the package could not be imported at all by anyone using
    the file exporter or their own span exporter.
    """
    if name == "client":
        global _default
        if _default is None:
            _default = AgentSight()
        return _default
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__():
    return sorted(__all__)
