"""Centralized logging framework for Junior Aladdin.

Provides structured JSON logging with per-module log levels,
sensitive data redaction, and log rotation.
"""

from __future__ import annotations

import json
import logging
import logging.handlers
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from junior_aladdin.shared.types import Severity

# Sensitive field patterns to redact
SENSITIVE_PATTERNS = [
    "key",
    "token",
    "password",
    "secret",
    "credential",
    "auth",
    "pin",
]

# Module-level logger cache
_loggers: dict[str, logging.Logger] = {}


class SensitiveDataFilter(logging.Filter):
    """Filter that redacts sensitive fields from log records."""

    def filter(self, record: logging.LogRecord) -> bool:
        if hasattr(record, "msg") and isinstance(record.msg, str):
            for pattern in SENSITIVE_PATTERNS:
                if pattern in record.msg.lower():
                    record.msg = self._redact_message(record.msg)
        return True

    @staticmethod
    def _redact_message(message: str) -> str:
        """Replace sensitive values in log messages."""
        import re
        for pattern in SENSITIVE_PATTERNS:
            message = re.sub(
                rf'({pattern}["\']?\s*[:=]\s*["\']?)[^"\',\s}}]+',
                r'\1[REDACTED]',
                message,
                flags=re.IGNORECASE,
            )
        return message


class JsonFormatter(logging.Formatter):
    """Format log records as structured JSON."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "module": record.name,
            "message": record.getMessage(),
        }
        if hasattr(record, "extra") and record.extra:
            log_entry["extra"] = record.extra
        if record.exc_info and record.exc_info[0]:
            log_entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_entry, default=str)


def get_logger(name: str, level: str | None = None) -> logging.Logger:
    """Get a configured logger for a module.

    Args:
        name: Logger name (typically __name__ of the module)
        level: Optional override log level (e.g., 'DEBUG', 'INFO')

    Returns:
        Configured Logger instance
    """
    if name in _loggers:
        return _loggers[name]

    logger = logging.getLogger(name)

    # Set level from parameter or default to INFO
    log_level = (level or "INFO").upper()
    logger.setLevel(getattr(logging, log_level, logging.INFO))

    # Add JSON handler if none exists
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(JsonFormatter())
        handler.addFilter(SensitiveDataFilter())
        logger.addHandler(handler)

    # Prevent propagation to root logger
    logger.propagate = False

    _loggers[name] = logger
    return logger


def setup_file_logging(log_dir: str | Path = "logs", level: str = "INFO") -> None:
    """Add file-based logging with rotation.

    Args:
        log_dir: Directory for log files
        level: Log level for file output
    """
    log_path = Path(log_dir)
    log_path.mkdir(parents=True, exist_ok=True)

    file_handler = logging.handlers.TimedRotatingFileHandler(
        filename=log_path / "junior_aladdin.log",
        when="midnight",
        interval=1,
        backup_count=30,
        encoding="utf-8",
    )
    file_handler.setLevel(getattr(logging, level.upper(), logging.INFO))
    file_handler.setFormatter(JsonFormatter())
    file_handler.addFilter(SensitiveDataFilter())

    root_logger = logging.getLogger()
    root_logger.addHandler(file_handler)


def severity_to_log_level(severity: Severity) -> int:
    """Map Severity enum to Python logging level."""
    mapping = {
        Severity.INFO: logging.INFO,
        Severity.CAUTION: logging.WARNING,
        Severity.SEVERE: logging.ERROR,
        Severity.CRITICAL: logging.CRITICAL,
    }
    return mapping.get(severity, logging.INFO)
