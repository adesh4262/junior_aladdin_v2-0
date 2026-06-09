"""Shared utilities for Floor 1 modules.

Provides ID generation, retry logic, health checks, and serialization
used by multiple Floor 1 modules.

Floor 1 rule: ONLY imports from shared/. No floor_2+ imports.
"""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import Callable
from typing import Any

from junior_aladdin.shared.logging import get_logger

logger = get_logger("shared_utils")


def generate_connection_id() -> str:
    """Generate a unique connection identifier.

    Returns:
        A UUID4 hex string prefixed with 'conn_'.
        Example: 'conn_a1b2c3d4e5f6...'
    """
    return f"conn_{uuid.uuid4().hex}"


def generate_packet_id() -> str:
    """Generate a unique packet identifier.

    Returns:
        A UUID4 hex string prefixed with 'pkt_'.
        Example: 'pkt_f6e5d4c3b2a1...'
    """
    return f"pkt_{uuid.uuid4().hex}"


def retry_with_backoff(
    func: Callable[[], Any],
    max_retries: int = 3,
    base_delay: float = 1.0,
    backoff_factor: float = 2.0,
) -> Any:
    """Execute a function with exponential backoff retry.

    Retries the function up to `max_retries` times if it raises an exception.
    Delay between retries doubles each time: base_delay * (backoff_factor ^ attempt).

    Args:
        func: A zero-argument callable to retry.
        max_retries: Maximum number of retry attempts (default 3).
        base_delay: Initial delay in seconds before first retry (default 1.0).
        backoff_factor: Multiplier for delay each retry (default 2.0).

    Returns:
        The return value of func if it succeeds.

    Raises:
        The last exception raised by func if all retries are exhausted.
    """
    last_exception: Exception | None = None

    for attempt in range(max_retries + 1):
        try:
            return func()
        except Exception as e:
            last_exception = e
            if attempt < max_retries:
                delay = base_delay * (backoff_factor**attempt)
                logger.warning(
                    "Retry attempt %d/%d failed, retrying in %.1fs",
                    attempt + 1,
                    max_retries,
                    delay,
                    extra={
                        "error": str(e),
                    },
                )
                time.sleep(delay)

    logger.error(
        "All %d retry attempts exhausted",
        extra={"max_retries": max_retries, "last_error": str(last_exception)},
    )
    raise last_exception  # type: ignore[misc]


def is_websocket_healthy(ws: Any) -> bool:
    """Check if a WebSocket connection appears healthy.

    Args:
        ws: A WebSocket object (expected to have a ``ping`` or ``closed``
            attribute, depending on the implementation).

    Returns:
        True if the WebSocket appears connected, False otherwise.
    """
    if ws is None:
        return False
    try:
        # Standard WebSocket attribute checks
        if hasattr(ws, "closed"):
            return not ws.closed
        if hasattr(ws, "ping"):
            ws.ping()
            return True
        # Fallback: assume connected
        return True
    except Exception:
        return False


def serialize_for_handoff(data: dict[str, Any]) -> str:
    """Serialize a dict to JSON for Floor 2 handoff.

    Args:
        data: Dictionary to serialize (must be JSON-serializable).

    Returns:
        JSON string representation of the data.

    Raises:
        ValueError: If the data cannot be serialized to JSON.
    """
    try:
        return json.dumps(data, default=str)
    except (TypeError, ValueError) as e:
        raise ValueError(
            "Failed to serialize handoff data to JSON",
        ) from e
