import logging
import os

from agentsight.logging.formatters import AgentSightLogFormatter

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    # dotenv not installed, continue without it
    pass

# Create the logger at module level
logger = logging.getLogger("agentsight")
logger.propagate = False
logger.setLevel(logging.INFO)

def configure_logging(config=None):  # Remove type hint temporarily to avoid circular import
    """Configure the AgentSight logger with console logging.

    Args:
        config: Optional Config instance. If not provided, a new Config instance will be created.
    """
    # Defer the Config import to avoid circular dependency
    if config is None:
        from agentsight.config import Config
        config = Config()

    # Use env var as override if present, otherwise use config
    log_level_env = os.environ.get("AGENTSIGHT_LOG_LEVEL", "").upper()
    if log_level_env and hasattr(logging, log_level_env):
        log_level = getattr(logging, log_level_env)
    else:
        if isinstance(config.log_level, str):
            log_level_str = config.log_level.upper()
            log_level = getattr(logging, log_level_str, logging.INFO)
        else:
            log_level = config.log_level if isinstance(config.log_level, int) else logging.INFO

    logger.setLevel(log_level)

    # Remove existing handlers
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)

    # Configure console logging
    stream_handler = logging.StreamHandler()
    stream_handler.setLevel(log_level)
    stream_handler.setFormatter(AgentSightLogFormatter())
    logger.addHandler(stream_handler)

    return logger

