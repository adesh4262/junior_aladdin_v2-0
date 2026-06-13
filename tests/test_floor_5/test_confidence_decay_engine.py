"""Tests for Floor 5 — ConfidenceDecayEngine (Step 5.15)."""

from __future__ import annotations

import pytest

from junior_aladdin.floor_5_captain.confidence_decay_engine import (
    ConfidenceDecayEngine,
    DecayResult,
)
from junior_aladdin.shared.types import TradeClass


# ── Fixtures ───────────────────────────────────────────────────────────────


def make_engine() -> ConfidenceDecayEngine:
    """Create a fresh ConfidenceDecayEngine for each test."""
    return ConfidenceDecayEngine()


# ── 1. get_decay_rate ──────────────────────────────────────────────────────


def test_1_get_decay_rate_scalp():
    """SCALP decay rate is 0.30 per candle."""
    engine = make_engine()
    rate = engine.get_decay_rate(TradeClass.SCALP)
    assert rate == 0.30, f"Expected 0.30, got {rate}"


def test_2_get_decay_rate_continuation():
    """CONTINUATION decay rate is 0.10 per candle."""
    engine = make_engine()
    rate = engine.get_decay_rate(TradeClass.CONTINUATION)
    assert rate == 0.10, f"Expected 0.10, got {rate}"


def test_3_get_decay_rate_reversal():
    """REVERSAL decay rate is 0.15 per candle."""
    engine = make_engine()
    rate = engine.get_decay_rate(TradeClass.REVERSAL)
    assert rate == 0.15, f"Expected 0.15, got {rate}"


def test_4_get_decay_rate_liquidity_reclaim():
    """LIQUIDITY_RECLAIM decay rate is 0.05 per candle."""
    engine = make_engine()
    rate = engine.get_decay_rate(TradeClass.LIQUIDITY_RECLAIM)
    assert rate == 0.05, f"Expected 0.05, got {rate}"


def test_5_get_decay_rate_options_pressure():
    """OPTIONS_PRESSURE decay rate is 0.05 per candle."""
    engine = make_engine()
    rate = engine.get_decay_rate(TradeClass.OPTIONS_PRESSURE)
    assert rate == 0.05, f"Expected 0.05, got {rate}"


def test_6_get_decay_rate_none():
    """None trade class returns default decay rate (0.10)."""
    engine = make_engine()
    rate = engine.get_decay_rate(None)
    assert rate == 0.10, f"Expected 0.10, got {rate}"


# ── 2. calculate_decay ─────────────────────────────────────────────────────


def test_7_calculate_decay_zero_candles():
    """0 candles elapsed → factor of 1.0 (no decay)."""
    engine = make_engine()
    factor = engine.calculate_decay(TradeClass.SCALP, 0)
    assert factor == 1.0, f"Expected 1.0, got {factor}"


def test_8_calculate_decay_scalp_one_candle():
    """SCALP at 1 candle: 1.0 - (0.30 × 1) = 0.70."""
    engine = make_engine()
    factor = engine.calculate_decay(TradeClass.SCALP, 1)
    assert factor == 0.70, f"Expected 0.70, got {factor}"


def test_9_calculate_decay_scalp_three_candles():
    """SCALP at 3 candles: 1.0 - (0.30 × 3) = 0.10 (clamped to min)."""
    engine = make_engine()
    factor = engine.calculate_decay(TradeClass.SCALP, 3)
    # 1.0 - 0.90 = 0.10 (handles floating point)
    assert factor == pytest.approx(0.10), f"Expected ~0.10, got {factor}"


def test_10_calculate_decay_scalp_many_candles():
    """SCALP at 10 candles: clamped to min decay factor (0.10)."""
    engine = make_engine()
    factor = engine.calculate_decay(TradeClass.SCALP, 10)
    assert factor == 0.10, f"Expected 0.10, got {factor}"


def test_11_calculate_decay_continuation_three_candles():
    """CONTINUATION at 3 candles: 1.0 - (0.10 × 3) = 0.70."""
    engine = make_engine()
    factor = engine.calculate_decay(TradeClass.CONTINUATION, 3)
    assert factor == 0.70, f"Expected 0.70, got {factor}"


def test_12_calculate_decay_continuation_ten_candles():
    """CONTINUATION at 10 candles: 1.0 - (0.10 × 10) = 0.10 (clamped)."""
    engine = make_engine()
    factor = engine.calculate_decay(TradeClass.CONTINUATION, 10)
    assert factor == 0.10, f"Expected 0.10, got {factor}"


def test_13_calculate_decay_reversal_two_candles():
    """REVERSAL at 2 candles: 1.0 - (0.15 × 2) = 0.70."""
    engine = make_engine()
    factor = engine.calculate_decay(TradeClass.REVERSAL, 2)
    assert factor == 0.70, f"Expected 0.70, got {factor}"


def test_14_calculate_decay_liquidity_reclaim_five_candles():
    """LIQUIDITY_RECLAIM at 5 candles: 1.0 - (0.05 × 5) = 0.75."""
    engine = make_engine()
    factor = engine.calculate_decay(TradeClass.LIQUIDITY_RECLAIM, 5)
    assert factor == 0.75, f"Expected 0.75, got {factor}"


def test_15_calculate_decay_options_pressure_eight_candles():
    """OPTIONS_PRESSURE at 8 candles: 1.0 - (0.05 × 8) = 0.60."""
    engine = make_engine()
    factor = engine.calculate_decay(TradeClass.OPTIONS_PRESSURE, 8)
    assert factor == 0.60, f"Expected 0.60, got {factor}"


def test_16_calculate_decay_default_rate():
    """None trade class uses default rate 0.10."""
    engine = make_engine()
    factor = engine.calculate_decay(None, 5)
    assert factor == 0.50, f"Expected 0.50, got {factor}"


# ── 3. apply_decay ─────────────────────────────────────────────────────────


def test_17_apply_decay_no_candles():
    """No candles elapsed → score unchanged."""
    engine = make_engine()
    result = engine.apply_decay(conviction_score=80.0, trade_class=TradeClass.CONTINUATION, elapsed_candles=0)
    assert result.original_score == 80.0
    assert result.decayed_score == 80.0
    assert result.decay_factor == 1.0
    assert not result.band_downgraded


def test_18_apply_decay_scalp_moderate_decay():
    """SCALP, 75.0 score, 1 candle elapsed: 75 × 0.70 = 52.5."""
    result = make_engine().apply_decay(conviction_score=75.0, trade_class=TradeClass.SCALP, elapsed_candles=1)
    assert result.decayed_score == 52.5, f"Expected 52.5, got {result.decayed_score}"
    assert result.decay_factor == 0.70
    assert result.band_downgraded  # STRONG (75) → WEAK (52.5)
    assert result.original_band == "STRONG"
    assert result.new_band == "WEAK"


def test_19_apply_decay_scalp_full_decay():
    """SCALP, 80.0 score, 3 candles: 80 × 0.10 = 8.0."""
    result = make_engine().apply_decay(conviction_score=80.0, trade_class=TradeClass.SCALP, elapsed_candles=3)
    assert result.decayed_score == 8.0, f"Expected 8.0, got {result.decayed_score}"
    assert result.decay_factor == 0.10
    assert result.band_downgraded  # STRONG → REJECT


def test_20_apply_decay_continuation_light_decay():
    """CONTINUATION, 65.0 score, 2 candles: 65 × 0.80 = 52.0 drops to WEAK."""
    result = make_engine().apply_decay(conviction_score=65.0, trade_class=TradeClass.CONTINUATION, elapsed_candles=2)
    assert result.decayed_score == pytest.approx(52.0), f"Expected ~52.0, got {result.decayed_score}"
    assert result.decay_factor == 0.80
    assert result.band_downgraded, "65→52 drops from TRADABLE to WEAK"


def test_21_apply_decay_no_downgrade():
    """72.0 score, 1 candle, LIQUIDITY_RECLAIM: 72 × 0.95 = 68.4 (same band)."""
    result = make_engine().apply_decay(conviction_score=72.0, trade_class=TradeClass.LIQUIDITY_RECLAIM, elapsed_candles=1)
    # 72 * 0.95 = 68.4, both in TRADABLE range (60-74)
    assert result.band_downgraded is False, "72→68.4 should stay in TRADABLE"
    assert result.original_band == "TRADABLE"
    assert result.new_band == "TRADABLE"


def test_22_apply_decay_edge_band_boundary():
    """Score at exact band boundary with small decay can cause drop."""
    # 75.0 (STRONG lower bound) × 0.80 = 60.0 (still TRADABLE upper bound)
    result = make_engine().apply_decay(conviction_score=75.0, trade_class=TradeClass.CONTINUATION, elapsed_candles=2)
    assert result.decayed_score == 60.0, f"Expected 60.0, got {result.decayed_score}"
    assert result.band_downgraded  # STRONG → TRADABLE
    assert result.new_band == "TRADABLE"


def test_23_apply_decay_result_metadata():
    """Result metadata fields populated correctly."""
    result = make_engine().apply_decay(conviction_score=50.0, trade_class=TradeClass.REVERSAL, elapsed_candles=2)
    assert result.trade_class == "REVERSAL"
    assert result.decay_rate == 0.15
    assert result.elapsed_candles == 2
    assert result.original_band == "WEAK"
    assert result.decayed_score == pytest.approx(50.0 * 0.70)


# ── 4. get_decay_summary ───────────────────────────────────────────────────


def test_24_get_decay_summary_all_classes():
    """Summary includes all 5 trade classes."""
    engine = make_engine()
    summary = engine.get_decay_summary()
    for tc in TradeClass:
        assert tc.value in summary, f"Missing {tc.value} in summary"
    assert len(summary) == len(TradeClass), f"Expected {len(TradeClass)} entries, got {len(summary)}"


def test_25_get_decay_summary_values():
    """Summary has correct decay rate values."""
    engine = make_engine()
    summary = engine.get_decay_summary()
    assert summary["SCALP"] == 0.30
    assert summary["CONTINUATION"] == 0.10
    assert summary["REVERSAL"] == 0.15
    assert summary["LIQUIDITY_RECLAIM"] == 0.05
    assert summary["OPTIONS_PRESSURE"] == 0.05


# ── 5. Edge cases ──────────────────────────────────────────────────────────


def test_26_edge_negative_candles():
    """Negative elapsed candles treated as 0 → factor = 1.0."""
    engine = make_engine()
    factor = engine.calculate_decay(TradeClass.SCALP, -5)
    assert factor == 1.0, f"Expected 1.0, got {factor}"


def test_27_edge_very_low_conviction():
    """Low conviction score stays in REJECT band even after decay."""
    engine = make_engine()
    result = engine.apply_decay(conviction_score=10.0, trade_class=TradeClass.SCALP, elapsed_candles=5)
    assert result.original_band == "REJECT"
    assert result.new_band == "REJECT"
    assert not result.band_downgraded


def test_28_edge_unknown_trade_class():
    """Unknown trade class uses default rate (0.10)."""
    engine = make_engine()
    factor = engine.calculate_decay(None, 3)
    assert factor == 0.70, f"Expected 0.70, got {factor}"


def test_29_edge_elite_score_decay():
    """ELITE score (95) with small decay stays ELITE."""
    engine = make_engine()
    result = engine.apply_decay(conviction_score=95.0, trade_class=TradeClass.OPTIONS_PRESSURE, elapsed_candles=1)
    # 95 * 0.95 = 90.25, still ≥ 90 = ELITE
    assert result.original_band == "ELITE"
    assert result.new_band == "ELITE"
    assert not result.band_downgraded


def test_30_edge_elite_score_heavy_decay():
    """ELITE score (95) with heavy decay drops to TRADABLE."""
    engine = make_engine()
    result = engine.apply_decay(conviction_score=95.0, trade_class=TradeClass.SCALP, elapsed_candles=3)
    # 95 * 0.10 = 9.5 → REJECT
    assert result.new_band == "REJECT"
    assert result.band_downgraded
