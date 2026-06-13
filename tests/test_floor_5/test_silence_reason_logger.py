"""Tests for Floor 5 — SilenceReasonLogger (Step 5.17)."""

from __future__ import annotations

from junior_aladdin.floor_5_captain.captain_types import SilenceReason
from junior_aladdin.floor_5_captain.silence_reason_logger import (
    SilenceReasonLogger,
    SilenceRecord,
)


# ── Fixtures ───────────────────────────────────────────────────────────────


def make_logger() -> SilenceReasonLogger:
    return SilenceReasonLogger()


# ── 1. Logging Reasons ────────────────────────────────────────────────────


def test_1_log_single_reason():
    """Log a single reason returns a valid record."""
    logger = make_logger()
    rec = logger.log_reason("WAIT", SilenceReason.INSUFFICIENT_CONFLUENCE, "No alignment")
    assert rec is not None
    assert rec.decision == "WAIT"
    assert rec.reason == SilenceReason.INSUFFICIENT_CONFLUENCE
    assert rec.reason_label == "Insufficient Confluence"
    assert rec.details == "No alignment"


def test_2_log_multiple_reasons():
    """Multiple reasons are all stored."""
    logger = make_logger()
    logger.log_reason("WAIT", SilenceReason.INSUFFICIENT_CONFLUENCE)
    logger.log_reason("WAIT", SilenceReason.TRAP_RISK_HIGH)
    assert logger.get_reason_count() == 2


def test_3_log_with_source():
    """Reason logged with source module name."""
    logger = make_logger()
    rec = logger.log_reason("BLOCKED", SilenceReason.PSYCHOLOGY_BLOCK,
                            details="trade_allowed=False", source="permission_gate")
    assert rec.source == "permission_gate"


# ── 2. All 11 Silence Reasons ─────────────────────────────────────────────


def test_4_all_reasons_loggable():
    """All 11 SilenceReason values can be logged."""
    logger = make_logger()
    for reason in SilenceReason:
        rec = logger.log_reason("WAIT", reason, f"Test for {reason.value}")
        assert rec.reason == reason
        assert rec.reason_label != ""
    assert logger.get_reason_count() == len(SilenceReason)


# ── 3. Primary Reason ─────────────────────────────────────────────────────


def test_5_primary_reason_empty():
    """No records → primary reason is None."""
    logger = make_logger()
    assert logger.get_primary_reason() is None


def test_6_primary_reason_single():
    """Single reason is also the primary reason."""
    logger = make_logger()
    logger.log_reason("WAIT", SilenceReason.WEAK_CONVICTION)
    primary = logger.get_primary_reason()
    assert primary is not None
    assert primary.reason == SilenceReason.WEAK_CONVICTION


def test_7_primary_reason_highest_severity():
    """Psychology block (100) ranks higher than weak conviction (40)."""
    logger = make_logger()
    logger.log_reason("WAIT", SilenceReason.WEAK_CONVICTION)
    logger.log_reason("BLOCKED", SilenceReason.PSYCHOLOGY_BLOCK)
    primary = logger.get_primary_reason()
    assert primary.reason == SilenceReason.PSYCHOLOGY_BLOCK


def test_8_primary_reason_real_mode_lock():
    """Real mode lock (90) ranks higher than active trade (80)."""
    logger = make_logger()
    logger.log_reason("BLOCKED", SilenceReason.ACTIVE_TRADE_EXISTS)
    logger.log_reason("BLOCKED", SilenceReason.REAL_MODE_LOCK)
    primary = logger.get_primary_reason()
    assert primary.reason == SilenceReason.REAL_MODE_LOCK


def test_9_severity_ordering():
    """Verify top 3 severity order: PSYCHOLOGY > REAL_MODE > ACTIVE_TRADE."""
    logger = make_logger()
    logger.log_reason("BLOCKED", SilenceReason.ACTIVE_TRADE_EXISTS)
    logger.log_reason("BLOCKED", SilenceReason.REAL_MODE_LOCK)
    logger.log_reason("BLOCKED", SilenceReason.PSYCHOLOGY_BLOCK)
    primary = logger.get_primary_reason()
    assert primary.reason == SilenceReason.PSYCHOLOGY_BLOCK


# ── 4. Session Management ─────────────────────────────────────────────────


def test_10_get_session_reasons():
    """Session reasons returns all logged records."""
    logger = make_logger()
    logger.log_reason("WAIT", SilenceReason.WEAK_CONVICTION)
    logger.log_reason("BLOCKED", SilenceReason.PSYCHOLOGY_BLOCK)
    reasons = logger.get_session_reasons()
    assert len(reasons) == 2


def test_11_clear_session():
    """Clear removes all records."""
    logger = make_logger()
    logger.log_reason("WAIT", SilenceReason.WEAK_CONVICTION)
    logger.clear_session()
    assert logger.get_reason_count() == 0
    assert logger.get_primary_reason() is None
    assert not logger.has_reasons()


def test_12_has_reasons_true():
    """has_reasons returns True when records exist."""
    logger = make_logger()
    assert not logger.has_reasons()
    logger.log_reason("WAIT", SilenceReason.WEAK_CONVICTION)
    assert logger.has_reasons()


# ── 5. Reason Counts ──────────────────────────────────────────────────────


def test_13_get_reason_count():
    """Reason count matches number of logged reasons."""
    logger = make_logger()
    assert logger.get_reason_count() == 0
    logger.log_reason("WAIT", SilenceReason.INSUFFICIENT_CONFLUENCE)
    assert logger.get_reason_count() == 1
    logger.log_reason("WAIT", SilenceReason.TRAP_RISK_HIGH)
    assert logger.get_reason_count() == 2


def test_14_reason_count_by_type():
    """Count by type groups identical reasons."""
    logger = make_logger()
    logger.log_reason("WAIT", SilenceReason.WEAK_CONVICTION)
    logger.log_reason("WAIT", SilenceReason.WEAK_CONVICTION)
    logger.log_reason("BLOCKED", SilenceReason.PSYCHOLOGY_BLOCK)
    counts = logger.get_reason_count_by_type()
    assert counts.get("Weak Conviction", 0) == 2
    assert counts.get("Psychology Block", 0) == 1
    assert len(counts) == 2


# ── 6. Filter by Decision ─────────────────────────────────────────────────


def test_15_reasons_by_decision():
    """Filter reasons by decision type."""
    logger = make_logger()
    logger.log_reason("BLOCKED", SilenceReason.PSYCHOLOGY_BLOCK)
    logger.log_reason("WAIT", SilenceReason.WEAK_CONVICTION)
    logger.log_reason("BLOCKED", SilenceReason.REAL_MODE_LOCK)
    blocked = logger.get_reasons_by_decision("BLOCKED")
    assert len(blocked) == 2
    wait = logger.get_reasons_by_decision("WAIT")
    assert len(wait) == 1


# ── 7. Logger Summary ─────────────────────────────────────────────────────


def test_16_logger_summary_empty():
    """Summary with no records shows empty state."""
    logger = make_logger()
    summary = logger.get_logger_summary()
    assert summary["total_reasons"] == 0
    assert summary["primary_reason"] == ""
    assert summary["has_reasons"] is False


def test_17_logger_summary_with_reasons():
    """Summary contains primary reason and breakdown."""
    logger = make_logger()
    logger.log_reason("BLOCKED", SilenceReason.PSYCHOLOGY_BLOCK, source="permission_gate")
    logger.log_reason("WAIT", SilenceReason.WEAK_CONVICTION, source="conviction_engine")
    summary = logger.get_logger_summary()
    assert summary["total_reasons"] == 2
    assert summary["primary_reason"] == "Psychology Block"
    assert summary["primary_decision"] == "BLOCKED"
    assert summary["has_reasons"] is True
    assert len(summary["reason_breakdown"]) == 2


# ── 8. Edge Cases ─────────────────────────────────────────────────────────


def test_18_edge_duplicate_reasons():
    """Duplicate reasons are all stored individually."""
    logger = make_logger()
    logger.log_reason("WAIT", SilenceReason.STALE_SETUP, "First time")
    logger.log_reason("WAIT", SilenceReason.STALE_SETUP, "Second time")
    assert logger.get_reason_count() == 2
    assert logger.get_reason_count_by_type()["Stale Setup"] == 2


def test_19_edge_empty_details():
    """Empty details string is allowed."""
    logger = make_logger()
    rec = logger.log_reason("WAIT", SilenceReason.PLAN_EXPIRED)
    assert rec.details == ""
    assert rec.source == ""


def test_20_edge_clear_then_log():
    """After clear, new logs work correctly."""
    logger = make_logger()
    logger.log_reason("WAIT", SilenceReason.WEAK_CONVICTION)
    logger.clear_session()
    rec = logger.log_reason("BLOCKED", SilenceReason.DEAD_MARKET)
    assert logger.get_reason_count() == 1
    assert rec.reason == SilenceReason.DEAD_MARKET
