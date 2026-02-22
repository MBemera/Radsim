"""Logging configuration for RadSim."""

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path


def configure_logging(level=logging.INFO, log_dir=None):
    """Set up logging with file rotation and console output."""
    if log_dir is None:
        log_dir = Path.home() / ".radsim" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    log_file = log_dir / "radsim.log"

    file_handler = RotatingFileHandler(log_file, maxBytes=5_000_000, backupCount=3)
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    )

    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.WARNING)
    console_handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))

    root_logger = logging.getLogger("radsim")
    root_logger.setLevel(level)
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)
