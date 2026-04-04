"""Logging configuration for RadSim."""

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

FILE_HANDLER_NAME = "radsim_file"
CONSOLE_HANDLER_NAME = "radsim_console"


def _find_named_handler(logger, handler_name):
    """Return an existing handler by name when present."""
    for handler in logger.handlers:
        if handler.get_name() == handler_name:
            return handler
    return None


def configure_logging(level=logging.INFO, log_dir=None):
    """Set up logging with file rotation and console output."""
    if log_dir is None:
        log_dir = Path.home() / ".radsim" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    log_file = log_dir / "radsim.log"
    root_logger = logging.getLogger("radsim")
    root_logger.setLevel(level)
    root_logger.propagate = False

    file_handler = _find_named_handler(root_logger, FILE_HANDLER_NAME)
    if file_handler is not None and Path(file_handler.baseFilename) != log_file:
        root_logger.removeHandler(file_handler)
        file_handler.close()
        file_handler = None

    if file_handler is None:
        file_handler = RotatingFileHandler(log_file, maxBytes=5_000_000, backupCount=3)
        file_handler.set_name(FILE_HANDLER_NAME)
        root_logger.addHandler(file_handler)

    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    )

    console_handler = _find_named_handler(root_logger, CONSOLE_HANDLER_NAME)
    if console_handler is None:
        console_handler = logging.StreamHandler()
        console_handler.set_name(CONSOLE_HANDLER_NAME)
        root_logger.addHandler(console_handler)

    console_handler.setLevel(logging.WARNING)
    console_handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
