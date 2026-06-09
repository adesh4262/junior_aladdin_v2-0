"""pytest configuration and shared fixtures for Junior Aladdin tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from junior_aladdin.shared.config import Config
from junior_aladdin.shared.logging import get_logger
from junior_aladdin.shared.testing import (
    generate_mock_candle,
    generate_mock_captain_decision,
    generate_mock_execution_intent,
    generate_mock_floor_summary,
    generate_mock_head_report,
    generate_mock_memory_event,
    generate_mock_tick,
    seed_1min_candles,
)


@pytest.fixture(scope="session")
def test_config() -> Config:
    """Provide a test Config instance (no .env loading)."""
    config_dir = Path(__file__).resolve().parent.parent / "config"
    return Config(env="test", config_dir=config_dir, load_dotenv=False)


@pytest.fixture(scope="session")
def test_config_development() -> Config:
    """Provide a development Config instance (no .env loading)."""
    config_dir = Path(__file__).resolve().parent.parent / "config"
    return Config(env="development", config_dir=config_dir, load_dotenv=False)


@pytest.fixture
def test_logger():
    """Provide a test logger."""
    return get_logger("test")


@pytest.fixture
def mock_tick_generator():
    """Provide a callable that produces mock ticks."""
    return generate_mock_tick


@pytest.fixture
def mock_candle_generator():
    """Provide a callable that produces mock candles."""
    return generate_mock_candle


@pytest.fixture
def mock_head_report_generator():
    """Provide a callable that produces mock head reports."""
    return generate_mock_head_report


@pytest.fixture
def mock_floor_summary_generator():
    """Provide a callable that produces mock floor summaries."""
    return generate_mock_floor_summary


@pytest.fixture
def mock_captain_decision_generator():
    """Provide a callable that produces mock captain decisions."""
    return generate_mock_captain_decision


@pytest.fixture
def mock_execution_intent_generator():
    """Provide a callable that produces mock execution intents."""
    return generate_mock_execution_intent


@pytest.fixture
def mock_memory_event_generator():
    """Provide a callable that produces mock memory events."""
    return generate_mock_memory_event


@pytest.fixture
def seed_candles():
    """Provide seeded 1-minute candle data."""
    return seed_1min_candles(60)


@pytest.fixture
def test_data_dir(tmp_path: Path) -> Path:
    """Provide a temporary test data directory."""
    return tmp_path / "test_data"
