"""Serialization helpers for AgentSight"""

import json
from enum import Enum
from typing import Any

class AgentSightJSONEncoder(json.JSONEncoder):
    """JSON encoder for AgentSight enums."""
    
    def default(self, obj: Any) -> Any:
        if isinstance(obj, Enum):
            return obj.value
        return super().default(obj)
