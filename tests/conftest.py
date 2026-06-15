"""Root conftest — shared fixtures for all test modules."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pytest

from junior_aladdin.shared.config import Config


# ── Helpers ──────────────────────────────────────────────────────────


def _make_config(
    env: str = "test",
    **overrides: Any,
) -> Config:
    """Create a fresh Config instance for testing.

    Args:
        env: Environment name (default: "test").
        **overrides: Additional key=value pairs merged into _data.
    """
    cfg = Config(load_dotenv=False)
    cfg._data["env"] = env
    cfg._data["angel_one"] = {
        "client_id": "TEST001",
        "api_key": "test_api_key_123",
        "pin": "1234",
    }
    for key, value in overrides.items():
        cfg._data[key] = value
    return cfg


# ── Shared fixtures ─────────────────────────────────────────────────


@pytest.fixture(scope="session")
def test_config() -> Config:
    """Session-scoped test Config — shared across all floors.

    Uses load_dotenv=False to prevent .env file interference.
    Tests may override _data as needed.
    """
    return _make_config()


@pytest.fixture(scope="session")
def sample_time() -> datetime:
    """Fixed datetime for reproducible tests (2026-06-15 10:30:00 UTC)."""
    return datetime(2026, 6, 15, 10, 30, 0, 0)


@pytest.fixture(scope="session")
def mock_time() -> datetime:
    """Alias for sample_time."""
    return datetime(2026, 6, 15, 10, 30, 0, 0)
