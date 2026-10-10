"""Structured logging setup for CloudPrac."""

import logging
from logging.handlers import RotatingFileHandler
from typing import Optional

from cloudprac.utils.paths import ensure_cloudprac_dirs, get_log_file_path

LOGGER_NAME = "cloudprac"
_logger_initialized = False


def setup_logging(verbose: bool = False, log_file: Optional[str] = None) -> logging.Logger:
    """Configure structured logging for CloudPrac."""
    global _logger_initialized
    logger = logging.getLogger(LOGGER_NAME)

    if _logger_initialized:
        if verbose:
            logger.setLevel(logging.DEBUG)
        return logger

    logger.setLevel(logging.DEBUG if verbose else logging.INFO)
    logger.propagate = False

    # Clear existing handlers if any
    logger.handlers.clear()

    # Formatter for file logs (detailed timestamps)
    file_formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] [%(name)s:%(funcName)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    try:
        ensure_cloudprac_dirs()
        target_log_file = log_file or str(get_log_file_path())
        file_handler = RotatingFileHandler(
            target_log_file,
            maxBytes=5 * 1024 * 1024,  # 5 MB
            backupCount=3,
            encoding="utf-8",
        )
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(file_formatter)
        logger.addHandler(file_handler)
    except Exception:
        # Fallback to null handler if filesystem write fails (e.g. read-only env)
        pass

    _logger_initialized = True
    return logger


def get_logger() -> logging.Logger:
    """Get the CloudPrac application logger."""
    return logging.getLogger(LOGGER_NAME)
