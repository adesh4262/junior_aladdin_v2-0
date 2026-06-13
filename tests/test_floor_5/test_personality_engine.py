"""Tests for Floor 5 — Personality Engine (Step 5.10).

Tests cover:
- All 5 Captain moods: OBSERVER, PATIENT, AGGRESSIVE, DEFENSIVE, SILENT
- Mood determination from conviction band, session phase, regime
- Active trade effects
- Permission gate effects
- Recent loss effects
- Session phase effects (Golden Morning boosts aggression)
- Regime effects (trend vs chop)
- Edge cases (missing market story, default inputs)
- Utility methods (get_mood_label, get_mood_summary)
"""

from __future__ import annotations

import pytest

from junior_aladdin.floor_5_captain.captain_types import (
    ConvictionBand,
    MarketStory,
    SessionPhase,
)
from junior_aladdin.floor_5_captain.personality_engine import (
    PersonalityEngine,
)
from junior_aladdin.shared.types import CaptainMood


# ── Helpers ──────────────────────────────────────────────────────────────


def make_story(regime: str = "RANGE") -> MarketStory:
    """Create a MarketStory with a specific regime."""
    return MarketStory(regime=regime)


def make_engine() -> PersonalityEngine:
    """Create a fresh PersonalityEngine for testing."""
    return PersonalityEngine()


# =============================================================================
# SECTION 1: AGGRESSIVE Mood
# =============================================================================


class TestAggressive:
    """Tests for AGGRESSIVE mood determination."""

    def test_1_aggressive_strong_conviction_golden_morning_trend(self):
        """AGGRESSIVE when STRONG conviction + Golden Morning + trending."""
        engine = make_engine()
        mood = engine.determine_mood(
            conviction_band=ConvictionBand.STRONG,
            session_phase=SessionPhase.GOLDEN_MORNING,
            market_story=make_story("TREND_UP"),
        )
        assert mood == CaptainMood.AGGRESSIVE

    def test_2_aggressive_elite_conviction_golden_morning_trend(self):
        """AGGRESSIVE when ELITE conviction + Golden Morning + trending."""
        engine = make_engine()
        mood = engine.determine_mood(
            conviction_band=ConvictionBand.ELITE,
            session_phase=SessionPhase.GOLDEN_MORNING,
            market_story=make_story("TREND_DOWN"),
        )
        assert mood == CaptainMood.AGGRESSIVE

    def test_3_aggressive_strong_conviction_opening_trend(self):
        """AGGRESSIVE when STRONG conviction + OPENING + trending."""
        engine = make_engine()
        mood = engine.determine_mood(
            conviction_band=ConvictionBand.STRONG,
            session_phase=SessionPhase.OPENING,
            market_story=make_story("WEAK_UP"),
        )
        assert mood == CaptainMood.AGGRESSIVE

    def test_4_aggressive_strong_conviction_lunch_trend_downgraded(self):
        """STRONG conviction + LUNCH + trending → PATIENT (not AGGRESSIVE)."""
        engine = make_engine()
        mood = engine.determine_mood(
            conviction_band=ConvictionBand.STRONG,
            session_phase=SessionPhase.LUNCH,
            market_story=make_story("TREND_UP"),
        )
        assert mood == CaptainMood.PATIENT

    def test_5_aggressive_elite_closing_trend_downgraded(self):
        """ELITE conviction + CLOSING + trending → PATIENT (not AGGRESSIVE)."""
        engine = make_engine()
        mood = engine.determine_mood(
            conviction_band=ConvictionBand.ELITE,
            session_phase=SessionPhase.CLOSING,
            market_story=make_story("TREND_DOWN"),
        )
        assert mood == CaptainMood.PATIENT

    def test_6_aggressive_strong_chop_becomes_patient(self):
        """STRONG conviction + CHOP regime → PATIENT."""
        engine = make_engine()
        mood = engine.determine_mood(
            conviction_band=ConvictionBand.STRONG,
            session_phase=SessionPhase.GOLDEN_MORNING,
            market_story=make_story("CHOP"),
        )
        assert mood == CaptainMood.PATIENT

    def test_7_aggressive_strong_unclear_becomes_patient(self):
        """STRONG conviction + UNCLEAR regime → PATIENT."""
        engine = make_engine()
        mood = engine.determine_mood(
            conviction_band=ConvictionBand.STRONG,
            session_phase=SessionPhase.GOLDEN_MORNING,
            market_story=make_story("UNCLEAR"),
        )
        assert mood == CaptainMood.PATIENT


# =============================================================================
# SECTION 2: PATIENT Mood
# =============================================================================


class TestPatient:
    """Tests for PATIENT mood determination."""

    def test_8_patient_tradable_golden_morning_trend(self):
        """PATIENT when TRADABLE conviction + Golden Morning + trending."""
        engine = make_engine()
        mood = engine.determine_mood(
            conviction_band=ConvictionBand.TRADABLE,
            session_phase=SessionPhase.GOLDEN_MORNING,
            market_story=make_story("TREND_UP"),
        )
        assert mood == CaptainMood.PATIENT

    def test_9_patient_tradable_opening_trend(self):
        """PATIENT when TRADABLE + OPENING + trending."""
        engine = make_engine()
        mood = engine.determine_mood(
            conviction_band=ConvictionBand.TRADABLE,
            session_phase=SessionPhase.OPENING,
            market_story=make_story("TREND_DOWN"),
        )
        assert mood == CaptainMood.PATIENT

    def test_10_patient_tradable_closing_trend_becomes_observer(self):
        """TRADABLE + CLOSING + trending → OBSERVER (too late)."""
        engine = make_engine()
        mood = engine.determine_mood(
            conviction_band=ConvictionBand.TRADABLE,
            session_phase=SessionPhase.CLOSING,
            market_story=make_story("WEAK_UP"),
        )
        assert mood == CaptainMood.OBSERVER

    def test_11_patient_tradable_chop_becomes_observer(self):
        """TRADABLE + CHOP → OBSERVER."""
        engine = make_engine()
        mood = engine.determine_mood(
            conviction_band=ConvictionBand.TRADABLE,
            session_phase=SessionPhase.GOLDEN_MORNING,
            market_story=make_story("CHOP"),
        )
        assert mood == CaptainMood.OBSERVER


# =============================================================================
# SECTION 3: DEFENSIVE Mood
# =============================================================================


class TestDefensive:
    """Tests for DEFENSIVE mood determination."""

    def test_12_defensive_active_trade(self):
        """DEFENSIVE when an active trade exists."""
        engine = make_engine()
        mood = engine.determine_mood(
            conviction_band=ConvictionBand.STRONG,
            active_trade_exists=True,
        )
        assert mood == CaptainMood.DEFENSIVE

    def test_13_defensive_active_trade_overrides_aggressive(self):
        """DEFENSIVE takes priority over AGGRESSIVE when trade exists."""
        engine = make_engine()
        mood = engine.determine_mood(
            conviction_band=ConvictionBand.ELITE,
            session_phase=SessionPhase.GOLDEN_MORNING,
            market_story=make_story("TREND_UP"),
            active_trade_exists=True,
        )
        assert mood == CaptainMood.DEFENSIVE

    def test_14_defensive_recent_loss_and_active_trade(self):
        """DEFENSIVE when recent loss + active trade."""
        engine = make_engine()
        mood = engine.determine_mood(
            conviction_band=ConvictionBand.WEAK,
            active_trade_exists=True,
            recent_loss=True,
        )
        assert mood == CaptainMood.DEFENSIVE

    def test_15_defensive_active_trade_chop(self):
        """DEFENSIVE when active trade + CHOP regime."""
        engine = make_engine()
        mood = engine.determine_mood(
            conviction_band=ConvictionBand.STRONG,
            active_trade_exists=True,
            market_story=make_story("CHOP"),
        )
        assert mood == CaptainMood.DEFENSIVE

    def test_16_defensive_takes_priority_over_silent(self):
        """DEFENSIVE takes priority even when permission failed + active trade."""
        engine = make_engine()
        mood = engine.determine_mood(
            conviction_band=ConvictionBand.REJECT,
            active_trade_exists=True,
            permission_allowed=False,
        )
        assert mood == CaptainMood.DEFENSIVE


# =============================================================================
# SECTION 4: SILENT Mood
# =============================================================================


class TestSilent:
    """Tests for SILENT mood determination."""

    def test_17_silent_permission_blocked_no_setups(self):
        """SILENT when permission blocked and no setups."""
        engine = make_engine()
        mood = engine.determine_mood(
            conviction_band=ConvictionBand.REJECT,
            permission_allowed=False,
            has_setups=False,
        )
        assert mood == CaptainMood.SILENT

    def test_18_silent_permission_blocked_recent_loss(self):
        """SILENT when permission blocked and recent loss."""
        engine = make_engine()
        mood = engine.determine_mood(
            conviction_band=ConvictionBand.REJECT,
            permission_allowed=False,
            recent_loss=True,
        )
        assert mood == CaptainMood.SILENT

    def test_19_reject_conviction_no_setups_observer(self):
        """OBSERVER when REJECT conviction + no setups (permission allowed)."""
        engine = make_engine()
        mood = engine.determine_mood(
            conviction_band=ConvictionBand.REJECT,
            has_setups=False,
        )
        assert mood == CaptainMood.OBSERVER

    def test_20_silent_weak_conviction_no_setups(self):
        """SILENT when WEAK conviction + no setups."""
        engine = make_engine()
        mood = engine.determine_mood(
            conviction_band=ConvictionBand.WEAK,
            has_setups=False,
            permission_allowed=False,
        )
        assert mood == CaptainMood.SILENT


# =============================================================================
# SECTION 5: OBSERVER Mood
# =============================================================================


class TestObserver:
    """Tests for OBSERVER mood determination (default)."""

    def test_21_observer_default(self):
        """OBSERVER is the default mood with no inputs."""
        engine = make_engine()
        mood = engine.determine_mood()
        assert mood == CaptainMood.OBSERVER

    def test_22_observer_reject_with_setups(self):
        """OBSERVER when REJECT conviction but setups exist."""
        engine = make_engine()
        mood = engine.determine_mood(
            conviction_band=ConvictionBand.REJECT,
            has_setups=True,
            permission_allowed=True,
        )
        assert mood == CaptainMood.OBSERVER

    def test_23_observer_weak_conviction_setups_allowed(self):
        """OBSERVER when WEAK conviction + setups + permission allowed."""
        engine = make_engine()
        mood = engine.determine_mood(
            conviction_band=ConvictionBand.WEAK,
            has_setups=True,
            permission_allowed=True,
        )
        assert mood == CaptainMood.OBSERVER

    def test_24_observer_tradable_closing_trend(self):
        """OBSERVER when TRADABLE + CLOSING (too late to trade)."""
        engine = make_engine()
        mood = engine.determine_mood(
            conviction_band=ConvictionBand.TRADABLE,
            session_phase=SessionPhase.CLOSING,
            market_story=make_story("TREND_UP"),
        )
        assert mood == CaptainMood.OBSERVER

    def test_25_observer_no_market_story(self):
        """OBSERVER when no market story provided."""
        engine = make_engine()
        mood = engine.determine_mood(
            conviction_band=ConvictionBand.TRADABLE,
            session_phase=SessionPhase.OPENING,
            market_story=None,
        )
        assert mood == CaptainMood.OBSERVER  # No regime info → observer


# =============================================================================
# SECTION 6: Utility Methods
# =============================================================================


class TestUtility:
    """Tests for utility methods."""

    def test_26_get_mood_label_all_moods(self):
        """get_mood_label returns labels for all moods."""
        engine = make_engine()
        for mood in CaptainMood:
            label = engine.get_mood_label(mood)
            assert isinstance(label, str)
            assert len(label) > 0

    def test_27_get_mood_label_aggressive(self):
        """get_mood_label for AGGRESSIVE contains high confidence."""
        label = make_engine().get_mood_label(CaptainMood.AGGRESSIVE)
        assert "high confidence" in label.lower()

    def test_28_get_mood_summary_has_keys(self):
        """get_mood_summary returns dict with all expected keys."""
        engine = make_engine()
        mood = engine.determine_mood(
            conviction_band=ConvictionBand.STRONG,
            session_phase=SessionPhase.GOLDEN_MORNING,
            market_story=make_story("TREND_UP"),
        )
        summary = engine.get_mood_summary(mood)
        assert "mood" in summary
        assert "label" in summary
        assert "context" in summary
        assert summary["mood"] == "AGGRESSIVE"

    def test_29_get_mood_summary_with_context(self):
        """get_mood_summary includes provided context."""
        engine = make_engine()
        summary = engine.get_mood_summary(
            CaptainMood.PATIENT,
            context={"conviction_band": "TRADABLE", "regime": "TREND_UP"},
        )
        assert summary["context"]["conviction_band"] == "TRADABLE"
        assert summary["context"]["regime"] == "TREND_UP"


# =============================================================================
# SECTION 7: Edge Cases
# =============================================================================


class TestEdgeCases:
    """Tests for edge cases and boundary conditions."""

    def test_30_active_trade_no_conviction(self):
        """DEFENSIVE when active trade + REJECT conviction."""
        engine = make_engine()
        mood = engine.determine_mood(
            conviction_band=ConvictionBand.REJECT,
            active_trade_exists=True,
        )
        assert mood == CaptainMood.DEFENSIVE

    def test_31_permission_blocked_setups_exist(self):
        """SILENT when permission blocked even if setups exist."""
        engine = make_engine()
        mood = engine.determine_mood(
            conviction_band=ConvictionBand.WEAK,
            permission_allowed=False,
            has_setups=True,
        )
        assert mood == CaptainMood.SILENT

    def test_32_all_negative_factors(self):
        """All negative factors produce DEFENSIVE (active trade wins priority)."""
        engine = make_engine()
        mood = engine.determine_mood(
            conviction_band=ConvictionBand.REJECT,
            session_phase=SessionPhase.CLOSING,
            market_story=make_story("CHOP"),
            active_trade_exists=True,
            permission_allowed=False,
            has_setups=False,
            recent_loss=True,
        )
        assert mood == CaptainMood.DEFENSIVE  # Active trade takes top priority

    def test_33_recent_loss_no_active_trade(self):
        """Recent loss without active trade → SILENT."""
        engine = make_engine()
        mood = engine.determine_mood(
            conviction_band=ConvictionBand.WEAK,
            permission_allowed=False,
            recent_loss=True,
            has_setups=False,
        )
        assert mood == CaptainMood.SILENT

    def test_34_default_market_story_no_regime(self):
        """Empty regime in market story defaults to OBSERVER for TRADABLE."""
        engine = make_engine()
        mood = engine.determine_mood(
            conviction_band=ConvictionBand.TRADABLE,
            session_phase=SessionPhase.OPENING,
            market_story=MarketStory(),
        )
        assert mood == CaptainMood.OBSERVER  # Empty regime → no aggressive signal

    def test_35_mood_independent_of_conviction_when_active_trade(self):
        """Active trade always produces DEFENSIVE regardless of conviction."""
        engine = make_engine()
        for band in ConvictionBand:
            mood = engine.determine_mood(
                conviction_band=band,
                active_trade_exists=True,
            )
            assert mood == CaptainMood.DEFENSIVE, f"Failed for {band}"
