import logging


class AgentSightLogFormatter(logging.Formatter):
    """Formatter for console logging with colors and prefix."""

    blue = "\x1b[34m"
    bold_red = "\x1b[31;1m"
    reset = "\x1b[0m"
    prefix = "AgentSight: "

    FORMATS = {
        logging.DEBUG: f"(DEBUG) {prefix}%(message)s",
        logging.INFO: f"{prefix}%(message)s",
        logging.WARNING: f"{prefix}%(message)s",
        logging.ERROR: f"{bold_red}{prefix}%(message)s{reset}",
        logging.CRITICAL: f"{bold_red}{prefix}%(message)s{reset}",
    }

    def format(self, record):
        log_fmt = self.FORMATS.get(record.levelno, self.FORMATS[logging.INFO])
        formatter = logging.Formatter(log_fmt)
        return formatter.format(record)
