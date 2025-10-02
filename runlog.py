import logging
from logging.handlers import RotatingFileHandler


def setup_app_logger(log_file: str, *, level: int = logging.INFO, max_bytes: int = 1_048_576, backup_count: int = 3, add_console: bool = False) -> logging.Logger:
    """
    Configure root logger with a rotating file handler, always reconfiguring handlers to ensure logging works.
    - log_file: path to log file
    - level: logging level (default INFO)
    - max_bytes: rotate after this many bytes (~1MB)
    - backup_count: keep this many rotated files
    - add_console: also log to console if True
    Returns the app logger.
    """
    logger = logging.getLogger()  # root

    # Always reconfigure handlers to avoid being blocked by prior/basicConfig
    for h in list(logger.handlers):
        logger.removeHandler(h)

    logger.setLevel(level)

    # Rotating file handler (no delay to write immediately)
    fh = RotatingFileHandler(log_file, maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8", delay=False)
    fh.setLevel(level)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s - %(message)s")
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    if add_console:
        ch = logging.StreamHandler()
        ch.setLevel(level)
        ch.setFormatter(fmt)
        logger.addHandler(ch)

    # Avoid double logging if any library adds handlers
    logger.propagate = False

    return logging.getLogger("novel_reader")