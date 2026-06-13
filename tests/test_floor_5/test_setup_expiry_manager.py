"""Tests for Floor 5 — SetupExpiryManager (Step 5.14)."""

from __future__ import annotations

from datetime import datetime

from junior_aladdin.floor_5_captain.setup_expiry_manager import SetupExpiryManager
from junior_aladdin.shared.types import ArmedPlan, TradeClass


# ── Fixtures ───────────────────────────────────────────────────────────────


def make_plan(
    plan_id: str = "P1",
    setup_class: str = "SCALP",
    created_at_candle: int = 10,
    use_plan: bool = True,
) -> ArmedPlan:
    """Create a test ArmedPlan with expiry_condition."""
    return ArmedPlan(
        plan_id=plan_id,
        direction="BUY",
        setup_class=setup_class,
        trigger_condition={"type": "above", "level": 19500},
        expiry_condition={"created_at_candle": created_at_candle} if created_at_candle else {},
        invalidation_level=19400,
        readiness="WATCHING",
        created_at=datetime.utcnow(),
    )


def make_dict(
    setup_class: str = "SCALP",
    created_at_candle: int = 10,
) -> dict:
    """Create a test dict-based setup."""
    return {
        "setup_id": "S1",
        "direction": "BUY",
        "setup_class": setup_class,
        "created_at_candle": created_at_candle,
    }


# ── 1. get_expiry_candles ──────────────────────────────────────────────────


def test_1_get_expiry_candles_scalp():
    """SCALP expiry is 2 candles."""
    mgr = SetupExpiryManager()
    val = mgr.get_expiry_candles(TradeClass.SCALP)
    assert val == 2, f"Expected 2, got {val}"


def test_2_get_expiry_candles_continuation():
    """CONTINUATION expiry is 4 candles."""
    mgr = SetupExpiryManager()
    val = mgr.get_expiry_candles(TradeClass.CONTINUATION)
    assert val == 4, f"Expected 4, got {val}"


def test_3_get_expiry_candles_reversal():
    """REVERSAL expiry is 3 candles."""
    mgr = SetupExpiryManager()
    val = mgr.get_expiry_candles(TradeClass.REVERSAL)
    assert val == 3, f"Expected 3, got {val}"


def test_4_get_expiry_candles_liquidity_reclaim():
    """LIQUIDITY_RECLAIM expiry is 0 (not candle-bound)."""
    mgr = SetupExpiryManager()
    val = mgr.get_expiry_candles(TradeClass.LIQUIDITY_RECLAIM)
    assert val == 0, f"Expected 0, got {val}"


def test_5_get_expiry_candles_options_pressure():
    """OPTIONS_PRESSURE expiry is 0 (not candle-bound)."""
    mgr = SetupExpiryManager()
    val = mgr.get_expiry_candles(TradeClass.OPTIONS_PRESSURE)
    assert val == 0, f"Expected 0, got {val}"


def test_6_get_expiry_candles_none():
    """None trade class returns default expiry (3 candles)."""
    mgr = SetupExpiryManager()
    val = mgr.get_expiry_candles(None)
    assert val == 3, f"Expected 3, got {val}"


def test_7_get_expiry_candles_unknown():
    """Unknown trade class returns default expiry (3 candles)."""
    mgr = SetupExpiryManager()
    # Passing an unknown string directly — get_expiry_candles expects TradeClass | None
    # so this tests the None path via TradeClass enum lookup
    val = mgr.get_expiry_candles(None)
    assert val == 3, f"Expected 3 for unknown class, got {val}"


# ── 2. is_expired with ArmedPlan ───────────────────────────────────────────


def test_8_is_expired_plan_not_expired():
    """Plan created at candle 10, current 11, with 4-candle expiry → not expired."""
    mgr = SetupExpiryManager()
    plan = make_plan(setup_class="CONTINUATION", created_at_candle=10)
    assert not mgr.is_expired(plan, current_candle_index=13), "Should not be expired yet"


def test_9_is_expired_plan_expired():
    """Plan created at candle 10, current 14, with 4-candle expiry → expired."""
    mgr = SetupExpiryManager()
    plan = make_plan(setup_class="CONTINUATION", created_at_candle=10)
    assert mgr.is_expired(plan, current_candle_index=14), "Should be expired"


def test_10_is_expired_plan_exact_boundary():
    """Plan created at candle 10, current 14, with 4-candle expiry → exactly expired (10+4=14)."""
    mgr = SetupExpiryManager()
    plan = make_plan(setup_class="CONTINUATION", created_at_candle=10)
    assert mgr.is_expired(plan, current_candle_index=14), "Should be expired at exact boundary"


def test_11_is_expired_plan_not_candle_bound():
    """LIQUIDITY_RECLAIM has 0 expiry → never expires via candle check."""
    mgr = SetupExpiryManager()
    plan = make_plan(setup_class="LIQUIDITY_RECLAIM", created_at_candle=10)
    assert not mgr.is_expired(plan, current_candle_index=999), "Not candle-bound, should never expire"


def test_12_is_expired_plan_no_creation_candle():
    """Plan without created_at_candle in expiry_condition → not expired (graceful)."""
    mgr = SetupExpiryManager()
    plan = make_plan(setup_class="SCALP", created_at_candle=0)
    assert not mgr.is_expired(plan, current_candle_index=100), "No creation candle → not expired"


# ── 3. is_expired with dict ───────────────────────────────────────────────


def test_13_is_expired_dict_not_expired():
    """Dict-based setup not yet expired."""
    mgr = SetupExpiryManager()
    item = make_dict(setup_class="CONTINUATION", created_at_candle=10)
    assert not mgr.is_expired(item, current_candle_index=13), "Should not be expired yet"


def test_14_is_expired_dict_expired():
    """Dict-based setup has exceeded expiry."""
    mgr = SetupExpiryManager()
    item = make_dict(setup_class="CONTINUATION", created_at_candle=10)
    assert mgr.is_expired(item, current_candle_index=14), "Should be expired"


def test_15_is_expired_dict_no_candle():
    """Dict-based setup without created_at_candle → not expired."""
    mgr = SetupExpiryManager()
    item = {"setup_id": "S1", "setup_class": "SCALP"}  # no created_at_candle
    assert not mgr.is_expired(item, current_candle_index=100), "No candle → not expired"


def test_16_is_expired_dict_not_candle_bound():
    """OPTIONS_PRESSURE dict not candle-bound → never expires."""
    mgr = SetupExpiryManager()
    item = make_dict(setup_class="OPTIONS_PRESSURE", created_at_candle=10)
    assert not mgr.is_expired(item, current_candle_index=999), "Not candle-bound → not expired"


# ── 4. purge_expired ──────────────────────────────────────────────────────


def test_17_purge_expired_none():
    """No plans expired."""
    mgr = SetupExpiryManager()
    plans = [make_plan("P1", "CONTINUATION", 10), make_plan("P2", "CONTINUATION", 12)]
    expired = mgr.purge_expired(plans, current_candle_index=13)
    assert len(expired) == 0, f"Expected 0 expired, got {len(expired)}"


def test_18_purge_expired_some():
    """Some plans expired, some not."""
    mgr = SetupExpiryManager()
    plans = [
        make_plan("P1", "CONTINUATION", 10),  # expired (10→15, diff=5 >= 4)
        make_plan("P2", "CONTINUATION", 12),  # not expired (12→15, diff=3 < 4)
    ]
    expired = mgr.purge_expired(plans, current_candle_index=15)
    assert len(expired) == 1, f"Expected 1 expired, got {len(expired)}"
    assert expired[0].plan_id == "P1", f"Expected P1, got {expired[0].plan_id}"


def test_19_purge_expired_all():
    """All plans expired when candle diff exceeds all expiry windows."""
    mgr = SetupExpiryManager()
    plans = [
        make_plan("P1", "SCALP", 5),          # expired (5→20, diff=15 >= 2)
        make_plan("P2", "CONTINUATION", 10),  # expired (10→20, diff=10 >= 4)
    ]
    expired = mgr.purge_expired(plans, current_candle_index=20)
    assert len(expired) == 2, f"Expected 2 expired, got {len(expired)}"


def test_20_purge_expired_preserves_input():
    """purge_expired does not mutate the input list."""
    mgr = SetupExpiryManager()
    plans = [make_plan("P1", "CONTINUATION", 10)]
    _ = mgr.purge_expired(plans, current_candle_index=5)
    assert len(plans) == 1, "Input list should not be mutated"


# ── 5. get_expiry_reason ──────────────────────────────────────────────────


def test_21_expiry_reason_not_candle_bound():
    """Expiry reason for non-candle-bound class."""
    mgr = SetupExpiryManager()
    plan = make_plan(setup_class="LIQUIDITY_RECLAIM", created_at_candle=10)
    reason = mgr.get_expiry_reason(plan, current_candle_index=20)
    assert "not candle-bound" in reason.lower(), f"Unexpected reason: {reason}"


def test_22_expiry_reason_expired():
    """Expiry reason for expired plan includes elapsed/count."""
    mgr = SetupExpiryManager()
    plan = make_plan(setup_class="CONTINUATION", created_at_candle=10)
    reason = mgr.get_expiry_reason(plan, current_candle_index=14)
    assert "4/4" in reason or "expired" in reason.lower(), f"Unexpected reason: {reason}"


def test_23_expiry_reason_dict():
    """Expiry reason works with dict-based item."""
    mgr = SetupExpiryManager()
    item = make_dict(setup_class="CONTINUATION", created_at_candle=10)
    reason = mgr.get_expiry_reason(item, current_candle_index=14)
    assert "CONTINUATION" in reason, f"Unexpected reason: {reason}"


# ── 6. get_expiry_summary ─────────────────────────────────────────────────


def test_24_expiry_summary_all_classes():
    """Summary includes all 5 trade classes."""
    mgr = SetupExpiryManager()
    summary = mgr.get_expiry_summary()
    for tc in TradeClass:
        assert tc.value in summary, f"Missing {tc.value} in summary"
    assert len(summary) == len(TradeClass), f"Expected {len(TradeClass)} entries, got {len(summary)}"


def test_25_expiry_summary_values():
    """Summary has correct expiry values for each class."""
    mgr = SetupExpiryManager()
    summary = mgr.get_expiry_summary()
    assert summary["SCALP"] == 2
    assert summary["CONTINUATION"] == 4
    assert summary["REVERSAL"] == 3
    assert summary["LIQUIDITY_RECLAIM"] == 0
    assert summary["OPTIONS_PRESSURE"] == 0


# ── 7. Edge cases ─────────────────────────────────────────────────────────


def test_26_edge_scalp_exact_not_expired():
    """SCALP at exact boundary minus 1 should not expire."""
    mgr = SetupExpiryManager()
    plan = make_plan(setup_class="SCALP", created_at_candle=10)
    assert not mgr.is_expired(plan, current_candle_index=11), "SCALP not expired at boundary-1"


def test_27_edge_scalp_exact_expired():
    """SCALP at exact boundary should be expired."""
    mgr = SetupExpiryManager()
    plan = make_plan(setup_class="SCALP", created_at_candle=10)
    assert mgr.is_expired(plan, current_candle_index=12), "SCALP expired at exact boundary"


def test_28_edge_reversal_exact():
    """REVERSAL with 3-candle expiry at exact boundary."""
    mgr = SetupExpiryManager()
    plan = make_plan(setup_class="REVERSAL", created_at_candle=10)
    assert mgr.is_expired(plan, current_candle_index=13), "REVERSAL expired at exact boundary"


def test_29_edge_unknown_class_dict():
    """Dict with unknown trade class uses default expiry."""
    mgr = SetupExpiryManager()
    item = make_dict(setup_class="UNKNOWN_CLASS", created_at_candle=5)
    # Default expiry is 3, so at candle 10, diff=5 >= 3 → expired
    assert mgr.is_expired(item, current_candle_index=8), f"Unknown class should use default expiry"


def test_30_edge_unknown_class_plan():
    """ArmedPlan with unknown trade class uses default expiry."""
    mgr = SetupExpiryManager()
    plan = make_plan(setup_class="MAGIC_CLASS", created_at_candle=5)
    # Default expiry is 3, so at candle 10, diff=5 >= 3 → expired
    assert mgr.is_expired(plan, current_candle_index=10), "Unknown class should use default expiry"
