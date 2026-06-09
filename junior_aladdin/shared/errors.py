"""Error hierarchy for Junior Aladdin system.

All custom exceptions inherit from JuniorAladdinError base class.
Every module should raise these typed exceptions for consistent error handling.
"""

from typing import Any


class JuniorAladdinError(Exception):
    """Base exception for all Junior Aladdin errors."""

    def __init__(
        self,
        message: str,
        details: dict[str, Any] | None = None,
        original_exception: Exception | None = None,
    ) -> None:
        self.message = message
        self.details = details or {}
        self.original_exception = original_exception
        super().__init__(self.message)

    def __str__(self) -> str:
        parts = [self.message]
        if self.details:
            parts.append(f" | details: {self.details}")
        if self.original_exception:
            parts.append(f" | caused by: {self.original_exception}")
        return "".join(parts)


class ConnectionError(JuniorAladdinError):
    """Source/connectivity failures (Floor 1)."""


class ValidationError(JuniorAladdinError):
    """Data validation failures (Floor 2)."""


class ConfigurationError(JuniorAladdinError):
    """Configuration loading failures (Phase 0)."""


class ExecutionError(JuniorAladdinError):
    """Trade execution failures (Side A)."""


class MemoryError(JuniorAladdinError):
    """Side C storage or retrieval failures."""


class ContractViolationError(JuniorAladdinError):
    """Contract mismatch detection (cross-floor boundary)."""
