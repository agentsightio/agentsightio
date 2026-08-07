"""Resource namespaces, one module per group of endpoints."""

from agentsight.api.resources.actions import Actions
from agentsight.api.resources.buttons import Buttons
from agentsight.api.resources.conversations import Conversations
from agentsight.api.resources.feedbacks import Feedbacks

__all__ = ["Actions", "Buttons", "Conversations", "Feedbacks"]
