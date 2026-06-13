"""Tests for intent_fingerprint — fingerprint generation, registration, duplicate detection, TTL expiry."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from junior_aladdin.shared.types import ExecutionIntent, ExecutionMode, TradeClass
from junior_aladdin.side_a_execution.intent_fingerprint import (
    DEFAULT_FINGERPRINT_TTL_SECONDS,
    DEFAULT_TIMESTAMP_WINDOW_SECONDS,
    IntentFingerprintStore,
    generate_fingerprint,
    generate_fingerprint_from_intent,
)


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def sample_intent() -> ExecutionIntent:
    """A sample ExecutionIntent for fingerprint tests."""
    return ExecutionIntent(
        trade_id="trade_snap_001",
        action="BUY",
        option_side="CE",
        selected_strike="19500",
        trade_class=TradeClass.CONTINUATION,
        intent_fingerprint="",
    )


@pytest.fixture
def store() -> IntentFingerprintStore:
    """A fresh IntentFingerprintStore."""
    return IntentFingerprintStore()


# =============================================================================
# Tests: generate_fingerprint
# =============================================================================


def test_generate_fingerprint_returns_hex() -> None:
    """Fingerprint is a 32-character hex string."""
    fp = generate_fingerprint("trade_001", "BUY", "19500", datetime.utcnow())
    assert len(fp) == 32
    assert all(c in "0123456789abcdef" for c in fp)


def test_generate_fingerprint_deterministic() -> None:
    """Same inputs produce same fingerprint."""
    now = datetime.utcnow()
    fp1 = generate_fingerprint("trade_001", "BUY", "19500", now)
    fp2 = generate_fingerprint("trade_001", "BUY", "19500", now)
    assert fp1 == fp2


def test_generate_fingerprint_different_trade_id() -> None:
    """Different trade_id produces different fingerprint."""
    now = datetime.utcnow()
    fp1 = generate_fingerprint("trade_001", "BUY", "19500", now)
    fp2 = generate_fingerprint("trade_002", "BUY", "19500", now)
    assert fp1 != fp2


def test_generate_fingerprint_different_action() -> None:
    """Different action produces different fingerprint."""
    now = datetime.utcnow()
    fp1 = generate_fingerprint("trade_001", "BUY", "19500", now)
    fp2 = generate_fingerprint("trade_001", "SELL", "19500", now)
    assert fp1 != fp2


def test_generate_fingerprint_different_strike() -> None:
    """Different strike produces different fingerprint."""
    now = datetime.utcnow()
    fp1 = generate_fingerprint("trade_001", "BUY", "19500", now)
    fp2 = generate_fingerprint("trade_001", "BUY", "19400", now)
    assert fp1 != fp2


def test_generate_fingerprint_same_window() -> None:
    """Timestamps within the same time window produce the same fingerprint."""
    base = datetime(2024, 1, 15, 10, 30, 0)  # 10:30:00
    later = datetime(2024, 1, 15, 10, 30, 3)  # 10:30:03 (within 5s window)
    fp1 = generate_fingerprint("trade_001", "BUY", "19500", base)
    fp2 = generate_fingerprint("trade_001", "BUY", "19500", later)
    assert fp1 == fp2


def test_generate_fingerprint_different_window() -> None:
    """Timestamps in different time windows produce different fingerprints."""
    base = datetime(2024, 1, 15, 10, 30, 0)  # 10:30:00
    later = datetime(2024, 1, 15, 10, 30, 6)  # 10:30:06 (next 5s window)
    fp1 = generate_fingerprint("trade_001", "BUY", "19500", base)
    fp2 = generate_fingerprint("trade_001", "BUY", "19500", later)
    assert fp1 != fp2


def test_generate_fingerprint_custom_window() -> None:
    """Custom window_seconds parameter works."""
    base = datetime(2024, 1, 15, 10, 30, 0)
    later = datetime(2024, 1, 15, 10, 30, 4)  # within 10s window
    fp1 = generate_fingerprint("trade_001", "BUY", "19500", base, window_seconds=10)
    fp2 = generate_fingerprint("trade_001", "BUY", "19500", later, window_seconds=10)
    assert fp1 == fp2


# =============================================================================
# Tests: generate_fingerprint_from_intent
# =============================================================================


def test_generate_fingerprint_from_intent(sample_intent: ExecutionIntent) -> None:
    """Fingerprint generated from intent matches direct generation."""
    direct = generate_fingerprint(
        trade_id=sample_intent.trade_id,
        action=sample_intent.action,
        strike=sample_intent.selected_strike,
        timestamp=sample_intent.timestamp,
    )
    from_intent = generate_fingerprint_from_intent(sample_intent)
    assert direct == from_intent


# =============================================================================
# Tests: register_fingerprint
# =============================================================================


def test_register_new_fingerprint(store: IntentFingerprintStore) -> None:
    """Registering a new fingerprint returns True."""
    fp = generate_fingerprint("trade_001", "BUY", "19500", datetime.utcnow())
    assert store.register_fingerprint(fp) is True


def test_register_duplicate_fingerprint(store: IntentFingerprintStore) -> None:
    """Registering the same fingerprint twice returns False."""
    fp = generate_fingerprint("trade_001", "BUY", "19500", datetime.utcnow())
    assert store.register_fingerprint(fp) is True  # First time
    assert store.register_fingerprint(fp) is False  # Duplicate


def test_register_different_fingerprints(store: IntentFingerprintStore) -> None:
    """Different fingerprints can both be registered."""
    now = datetime.utcnow()
    fp1 = generate_fingerprint("trade_001", "BUY", "19500", now)
    fp2 = generate_fingerprint("trade_002", "SELL", "19400", now)
    assert store.register_fingerprint(fp1) is True
    assert store.register_fingerprint(fp2) is True


# =============================================================================
# Tests: is_duplicate
# =============================================================================


def test_is_duplicate_returns_false_for_new(store: IntentFingerprintStore) -> None:
    """A new fingerprint is not a duplicate."""
    fp = generate_fingerprint("trade_001", "BUY", "19500", datetime.utcnow())
    assert store.is_duplicate(fp) is False


def test_is_duplicate_returns_true_for_registered(store: IntentFingerprintStore) -> None:
    """A registered fingerprint is a duplicate."""
    fp = generate_fingerprint("trade_001", "BUY", "19500", datetime.utcnow())
    store.register_fingerprint(fp)
    assert store.is_duplicate(fp) is True


# =============================================================================
# Tests: TTL expiry
# =============================================================================


def test_fingerprint_expires_after_ttl() -> None:
    """A fingerprint expires after the TTL period."""
    store = IntentFingerprintStore(ttl_seconds=1)
    fp = generate_fingerprint("trade_001", "BUY", "19500", datetime.utcnow())
    store.register_fingerprint(fp)

    # Should be a duplicate immediately
    assert store.is_duplicate(fp) is True

    # After TTL + small margin, should have expired
    import time
    time.sleep(1.1)

    assert store.is_duplicate(fp) is False


def test_expired_fingerprint_can_be_re_registered() -> None:
    """An expired fingerprint can be registered again."""
    store = IntentFingerprintStore(ttl_seconds=1)
    fp = generate_fingerprint("trade_001", "BUY", "19500", datetime.utcnow())
    assert store.register_fingerprint(fp) is True

    import time
    time.sleep(1.1)

    # Should be registerable again after expiry
    assert store.register_fingerprint(fp) is True


def test_get_active_count_evicts_expired() -> None:
    """get_active_count evicts expired fingerprints."""
    store = IntentFingerprintStore(ttl_seconds=1)
    fp = generate_fingerprint("trade_001", "BUY", "19500", datetime.utcnow())
    store.register_fingerprint(fp)
    assert store.get_active_count() == 1  # Fresh entry is counted

    import time
    time.sleep(1.1)

    assert store.get_active_count() == 0  # Expired entry evicted


# =============================================================================
# Tests: clear_session
# =============================================================================


def test_clear_session_removes_all(store: IntentFingerprintStore) -> None:
    """clear_session removes all registered fingerprints."""
    now = datetime.utcnow()
    fp1 = generate_fingerprint("trade_001", "BUY", "19500", now)
    fp2 = generate_fingerprint("trade_002", "SELL", "19400", now)
    store.register_fingerprint(fp1)
    store.register_fingerprint(fp2)
    assert store.get_active_count() == 2

    count = store.clear_session()
    assert count == 2
    assert store.get_active_count() == 0
    assert store.is_duplicate(fp1) is False


def test_clear_session_empty_store(store: IntentFingerprintStore) -> None:
    """Clearing an empty store returns 0."""
    count = store.clear_session()
    assert count == 0


# =============================================================================
# Tests: get_fingerprint_timestamp
# =============================================================================


def test_get_fingerprint_timestamp(store: IntentFingerprintStore) -> None:
    """get_fingerprint_timestamp returns registration timestamp."""
    fp = generate_fingerprint("trade_001", "BUY", "19500", datetime.utcnow())
    store.register_fingerprint(fp)
    ts = store.get_fingerprint_timestamp(fp)
    assert ts is not None
    assert isinstance(ts, datetime)


def test_get_fingerprint_timestamp_not_found(store: IntentFingerprintStore) -> None:
    """get_fingerprint_timestamp returns None for unknown fingerprint."""
    assert store.get_fingerprint_timestamp("unknown") is None


# =============================================================================
# Tests: TTL property
# =============================================================================


def test_default_ttl() -> None:
    """Default TTL is 60 seconds."""
    store = IntentFingerprintStore()
    assert store.ttl_seconds == DEFAULT_FINGERPRINT_TTL_SECONDS


def test_custom_ttl() -> None:
    """Custom TTL is stored."""
    store = IntentFingerprintStore(ttl_seconds=300)
    assert store.ttl_seconds == 300


def test_ttl_setter(store: IntentFingerprintStore) -> None:
    """Setting TTL updates the value."""
    store.ttl_seconds = 120
    assert store.ttl_seconds == 120


def test_ttl_setter_raises_on_zero(store: IntentFingerprintStore) -> None:
    """Setting TTL to zero raises ValueError."""
    with pytest.raises(ValueError, match="positive"):
        store.ttl_seconds = 0


def test_ttl_setter_raises_on_negative(store: IntentFingerprintStore) -> None:
    """Setting TTL to negative raises ValueError."""
    with pytest.raises(ValueError, match="positive"):
        store.ttl_seconds = -1


# =============================================================================
# Tests: integration-style
# =============================================================================


def test_full_fingerprint_flow(store: IntentFingerprintStore) -> None:
    """Full flow: generate → register → check duplicate → clear."""
    now = datetime.utcnow()
    fp = generate_fingerprint("trade_001", "BUY", "19500", now)

    # Not a duplicate initially
    assert store.is_duplicate(fp) is False

    # Register
    assert store.register_fingerprint(fp) is True

    # Now it's a duplicate
    assert store.is_duplicate(fp) is True
    assert store.get_active_count() == 1

    # Register same again should fail
    assert store.register_fingerprint(fp) is False

    # Clear session
    store.clear_session()
    assert store.is_duplicate(fp) is False
    assert store.get_active_count() == 0


def test_different_intents_not_duplicates(store: IntentFingerprintStore) -> None:
    """Different intents produce different fingerprints and are not duplicates."""
    now = datetime.utcnow()
    fp1 = generate_fingerprint("trade_001", "BUY", "19500", now)
    fp2 = generate_fingerprint("trade_002", "SELL", "19400", now)

    store.register_fingerprint(fp1)
    assert store.is_duplicate(fp2) is False


def test_same_trade_within_window_is_duplicate(store: IntentFingerprintStore) -> None:
    """Same trade within the time window is detected as duplicate.

    Uses a known timestamp NOT near a window boundary (10:30:07 is in
    the [5-10) window for a 5-second granularity).
    """
    base_ts = datetime(2024, 1, 15, 10, 30, 7)  # In the [5-10) window
    fp1 = generate_fingerprint("trade_001", "BUY", "19500", base_ts)

    # Intent at a slightly later time but within same window
    later_ts = datetime(2024, 1, 15, 10, 30, 9)  # Still in [5-10) window
    fp2 = generate_fingerprint("trade_001", "BUY", "19500", later_ts)

    # Both fingerprints should be the same (same window)
    assert fp1 == fp2, f"Expected same fingerprint, got {fp1} != {fp2}"

    # Register first
    store.register_fingerprint(fp1)
    # Second should be duplicate
    assert store.is_duplicate(fp2) is True
