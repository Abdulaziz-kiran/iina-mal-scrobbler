"""Logging configuration and sensitive token redaction for iina-mal-scrobbler."""

from __future__ import annotations

import logging
import re
import sys
from typing import Optional

from core.config import LOG_FILE, ensure_directories

# Regex patterns for detecting and masking tokens/secrets
_TOKEN_PATTERNS = [
    re.compile(r"(Bearer\s+)[A-Za-z0-9_\-\.]{15,}", re.IGNORECASE),
    re.compile(r"(access_token[\"':\s=]+)[A-Za-z0-9_\-\.]{15,}", re.IGNORECASE),
    re.compile(r"(refresh_token[\"':\s=]+)[A-Za-z0-9_\-\.]{15,}", re.IGNORECASE),
    re.compile(r"(code_verifier[\"':\s=]+)[A-Za-z0-9_\-\.~]{15,}", re.IGNORECASE),
    re.compile(r"(code[\"':\s=]+)[A-Za-z0-9_\-\.]{15,}", re.IGNORECASE),
]


def redact_secrets(message: str) -> str:
    """Mask any OAuth token, code, or secret in string message."""
    redacted = message
    for pattern in _TOKEN_PATTERNS:
        redacted = pattern.sub(r"\1<REDACTED>", redacted)
    return redacted


class RedactingFormatter(logging.Formatter):
    """Logging formatter that redacts authentication secrets from logs."""

    def format(self, record: logging.LogRecord) -> str:
        original = super().format(record)
        return redact_secrets(original)


_configured = False


def setup_logging(debug: bool = False) -> logging.Logger:
    """Set up application logging. Quiet on console by default, logging to file."""
    global _configured
    logger = logging.getLogger("mal_scrobbler")

    if _configured:
        if debug:
            logger.setLevel(logging.DEBUG)
        return logger

    logger.setLevel(logging.DEBUG if debug else logging.INFO)
    logger.propagate = False

    formatter = RedactingFormatter(
        fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Console handler (stderr only; stdout is reserved for machine-readable JSON)
    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setLevel(logging.DEBUG if debug else logging.WARNING)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # File handler
    try:
        ensure_directories()
        file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    except Exception:
        # If filesystem logging fails (e.g. read-only system), don't crash
        pass

    _configured = True
    return logger


def get_logger() -> logging.Logger:
    """Retrieve logger instance."""
    return logging.getLogger("mal_scrobbler")
