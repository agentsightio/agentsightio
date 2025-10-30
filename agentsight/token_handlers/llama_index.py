from agentsight.logging import logger
from agentsight.enums import LogLevel

def set_llamaindex_token_handler(log_level:LogLevel):
    # LlamaIndex
    try:
        from llama_index.core.callbacks.base import CallbackManager
        from llama_index.core.callbacks.token_counting import TokenCountingHandler

        is_verbose = True if log_level == LogLevel.DEBUG else False

        # print("is_verbose:; ", is_verbose)

        # Instantiate handler and manager
        tch = TokenCountingHandler(
            verbose=is_verbose
        )

        manager = CallbackManager(
            handlers=[tch]
        )

        # Replace the default global manager (for new LlamaIndex queries)
        from llama_index.core import Settings
        Settings.callback_manager = manager

        return tch
    except ImportError:
        logger.debug("llama-index not installed; skipping setting token handler.")
