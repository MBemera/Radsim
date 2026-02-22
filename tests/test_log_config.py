"""Tests for the logging configuration module."""

import logging

from radsim.log_config import configure_logging


class TestConfigureLogging:
    """Test logging setup."""

    def test_creates_log_directory(self, tmp_path):
        log_dir = tmp_path / "logs"
        configure_logging(log_dir=log_dir)
        assert log_dir.exists()

    def test_creates_log_file(self, tmp_path):
        log_dir = tmp_path / "logs"
        configure_logging(log_dir=log_dir)

        logger = logging.getLogger("radsim")
        logger.info("test message")

        log_file = log_dir / "radsim.log"
        assert log_file.exists()

    def test_nested_log_directory(self, tmp_path):
        log_dir = tmp_path / "deep" / "nested" / "logs"
        configure_logging(log_dir=log_dir)
        assert log_dir.exists()

    def test_logger_level_set(self, tmp_path):
        log_dir = tmp_path / "logs"
        configure_logging(level=logging.DEBUG, log_dir=log_dir)

        logger = logging.getLogger("radsim")
        assert logger.level == logging.DEBUG
