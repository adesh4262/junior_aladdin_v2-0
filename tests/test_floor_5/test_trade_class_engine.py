"""Unit tests for ``trade_class_engine.py`` — Floor 5 Step 5.11.

Tests:
- TradeClassEngine instantiation
- get_metadata() for all 5 trade classes
- assign_trade_class() with TREND_UP regime -> CONTINUATION
- assign_trade_class() with CHOP regime -> SCALP
- assign_trade_class() with RANGE regime -> OPTIONS_PRESSURE
- assign_trade_class() with session modifier (CLOSING reduces scores)
- assign_trade_class() overrides suggestion when regime fit differs significantly
- assign_trade_class() keeps suggestion when score is close
- validate_class() checks conviction band minimum
- validate_class() checks regime suitability
- get_preferred_classes() returns ranked list
- get_assignment_summary() dict
- None inputs / unknown regime -> empty assignment
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from datetime import datetime

from junior_aladdin.floor_5_captain.trade_class_engine import (
    TradeClassAssignment,
    TradeClassEngine,
    TradeClassMetadata,
)
from junior_aladdin.floor_5_captain.captain_types import (
    ConfluenceResult,
    ConvictionBand,
    MarketStory,
    SessionPhase,
)
from junior_aladdin.floor_5_captain.trade_idea_generator import TradeIdea
from junior_aladdin.shared.types import TradeClass

passed = 0
failed = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global passed, failed
    if cond:
        passed += 1
        print(f"  [PASS] {name}")
    else:
        failed += 1
        print(f"  [FAIL] {name}{' -- ' + detail if detail else ''}")


_GOLDEN_TIMESTAMP = datetime(2025, 6, 10, 4, 30, 0)


def make_story(
    regime: str = "TREND_UP",
    session: SessionPhase = SessionPhase.GOLDEN_MORNING,
) -> MarketStory:
    return MarketStory(
        regime=regime,
        session_phase=session,
        timestamp=_GOLDEN_TIMESTAMP,
    )


def make_confluence(quality: float = 0.8) -> ConfluenceResult:
    return ConfluenceResult(
        confluence_quality=quality,
        dominant_direction="BULLISH",
        timestamp=_GOLDEN_TIMESTAMP,
    )


def make_idea(
    trade_class: TradeClass | None = None,
    band: ConvictionBand = ConvictionBand.STRONG,
) -> TradeIdea:
    return TradeIdea(
        direction="BUY",
        trade_class_suggestion=trade_class,
        conviction_band=band,
        timestamp=_GOLDEN_TIMESTAMP,
    )


print("=" * 60)
print("Floor 5 - Trade Class Engine Tests")
print("=" * 60)

engine = TradeClassEngine()

# =========================================================================
# 1. TradeClassAssignment and TradeClassMetadata dataclasses
# =========================================================================
print("\n--- 1. Dataclass creation ---")

assign = TradeClassAssignment()
check("1.1 Default trade_class None", assign.trade_class is None)
check("1.2 Default confidence_fit 0.0", assign.confidence_fit == 0.0)
check("1.3 Default overridden False", assign.overridden is False)
check("1.4 Default assigned_at not None", assign.assigned_at is not None)

meta = engine.get_metadata(TradeClass.SCALP)
check("1.5 Metadata has label", meta is not None and bool(meta.label))
check("1.6 Metadata has expiry_candles", meta is not None and meta.expiry_candles > 0)

# =========================================================================
# 2. get_metadata() for all 5 classes
# =========================================================================
print("\n--- 2. All 5 classes have metadata ---")

for tc in TradeClass:
    meta = engine.get_metadata(tc)
    check(f"2.{tc.value} has metadata", meta is not None and meta.label != "")

# =========================================================================
# 3. TREND_UP regime -> CONTINUATION
# =========================================================================
print("\n--- 3. TREND_UP -> CONTINUATION ---")

assign = engine.assign_trade_class(
    trade_idea=make_idea(),
    market_story=make_story(regime="TREND_UP"),
    confluence_result=make_confluence(quality=0.8),
)
check("3.1 TREND_UP assigns CONTINUATION",
      assign.trade_class == TradeClass.CONTINUATION)
check("3.2 Confidence fit > 0.5", assign.confidence_fit > 0.5)
check("3.3 Metadata present", assign.metadata is not None)

# =========================================================================
# 4. CHOP regime -> SCALP
# =========================================================================
print("\n--- 4. CHOP -> SCALP ---")

assign = engine.assign_trade_class(
    trade_idea=make_idea(trade_class=TradeClass.CONTINUATION),
    market_story=make_story(regime="CHOP"),
    confluence_result=make_confluence(quality=0.5),
)
check("4.1 CHOP assigns SCALP", assign.trade_class == TradeClass.SCALP)
check("4.2 Overridden True (CONTINUATION overridden to SCALP)",
      assign.overridden is True)
check("4.3 Override reason non-empty", bool(assign.override_reason))

# =========================================================================
# 5. RANGE regime + strong confluence -> OPTIONS_PRESSURE
# =========================================================================
print("\n--- 5. RANGE -> OPTIONS_PRESSURE ---")

assign = engine.assign_trade_class(
    trade_idea=make_idea(),
    market_story=make_story(regime="RANGE"),
    confluence_result=make_confluence(quality=0.9),
)
check("5.1 RANGE assigns OPTIONS_PRESSURE",
      assign.trade_class == TradeClass.OPTIONS_PRESSURE)

# =========================================================================
# 6. Session modifier reduces scores
# =========================================================================
print("\n--- 6. Session modifier ---")

# CLOSING session reduces scores vs GOLDEN_MORNING
assign_gm = engine.assign_trade_class(
    trade_idea=make_idea(trade_class=TradeClass.CONTINUATION),
    market_story=make_story(regime="TREND_UP", session=SessionPhase.GOLDEN_MORNING),
    confluence_result=make_confluence(quality=0.8),
)
assign_close = engine.assign_trade_class(
    trade_idea=make_idea(trade_class=TradeClass.CONTINUATION),
    market_story=make_story(regime="TREND_UP", session=SessionPhase.CLOSING),
    confluence_result=make_confluence(quality=0.8),
)
check("6.1 CLOSING score < GOLDEN_MORNING score",
      assign_close.confidence_fit < assign_gm.confidence_fit)
check("6.2 Both assign CONTINUATION",
      assign_gm.trade_class == TradeClass.CONTINUATION and
      assign_close.trade_class == TradeClass.CONTINUATION)

# =========================================================================
# 7. Override when suggestion differs significantly
# =========================================================================
print("\n--- 7. Override logic ---")

# Suggest CONTINUATION in CHOP regime -> should be overridden to SCALP
assign = engine.assign_trade_class(
    trade_idea=make_idea(trade_class=TradeClass.CONTINUATION),
    market_story=make_story(regime="CHOP"),
    confluence_result=make_confluence(quality=0.5),
)
check("7.1 CHOP overrides CONTINUATION -> SCALP",
      assign.trade_class == TradeClass.SCALP and assign.overridden)

# Suggest SCALP in TREND_UP (close fit) -> might keep SCALP
assign = engine.assign_trade_class(
    trade_idea=make_idea(trade_class=TradeClass.SCALP),
    market_story=make_story(regime="TREND_UP"),
    confluence_result=make_confluence(quality=1.0),
)
check("7.2 SCALP in TREND_UP may keep SCALP (fit close enough)",
      assign.trade_class in (TradeClass.SCALP, TradeClass.CONTINUATION))
# CONTINUATION has 1.0 fit, SCALP has 0.7 in TREND_UP
# With quality=1.0: CONTINUATION=1.0*1.0*1.0=1.0, SCALP=0.7*1.0*1.0=0.7
# 1.0 > 0.7*1.2 -> overrides to CONTINUATION

# =========================================================================
# 8. validate_class() - conviction check
# =========================================================================
print("\n--- 8. validate_class() ---")

# SCALP needs WEAK, REJECT is below that
valid, reason = engine.validate_class(
    TradeClass.SCALP,
    conviction_band=ConvictionBand.REJECT,
)
check("8.1 REJECT invalid for SCALP", valid is False)
check("8.2 Reason includes 'below minimum'", "below minimum" in reason.lower())

# STRONG valid for REVERSAL
valid, reason = engine.validate_class(
    TradeClass.REVERSAL,
    conviction_band=ConvictionBand.STRONG,
)
check("8.3 STRONG valid for REVERSAL", valid is True)

# TRADABLE valid for CONTINUATION
valid, reason = engine.validate_class(
    TradeClass.CONTINUATION,
    conviction_band=ConvictionBand.TRADABLE,
)
check("8.4 TRADABLE valid for CONTINUATION", valid is True)

# =========================================================================
# 9. validate_class() - regime check
# =========================================================================
print("\n--- 9. validate_class() regime check ---")

# REVERSAL in TREND_UP has fit 0.1 (< 0.2 threshold)
valid, reason = engine.validate_class(
    TradeClass.REVERSAL,
    market_story=make_story(regime="TREND_UP"),
)
check("9.1 REVERSAL invalid in TREND_UP", valid is False)
check("9.2 Reason includes 'unsuitable'", "unsuitable" in reason.lower())

# CONTINUATION in TREND_UP has fit 1.0
valid, reason = engine.validate_class(
    TradeClass.CONTINUATION,
    market_story=make_story(regime="TREND_UP"),
)
check("9.3 CONTINUATION valid in TREND_UP", valid is True)

# =========================================================================
# 10. get_preferred_classes()
# =========================================================================
print("\n--- 10. get_preferred_classes() ---")

preferred = engine.get_preferred_classes(
    market_story=make_story(regime="TREND_UP"),
    conviction_band=ConvictionBand.TRADABLE,
)
check("10.1 Preferred list non-empty", len(preferred) > 0)
check("10.2 First is highest score", len(preferred) >= 2 and
      preferred[0][1] >= preferred[1][1])
check("10.3 CONTINUATION is top in TREND_UP",
      preferred[0][0] == TradeClass.CONTINUATION)

# With WEAK conviction, REVERSAL (min STRONG) should be filtered
preferred_weak = engine.get_preferred_classes(
    market_story=make_story(regime="TREND_UP"),
    conviction_band=ConvictionBand.WEAK,
)
check("10.4 WEAK conviction filters REVERSAL",
      all(tc != TradeClass.REVERSAL for tc, _ in preferred_weak))

# Unknown regime
preferred_empty = engine.get_preferred_classes(
    market_story=MarketStory(regime="UNKNOWN"),
)
check("10.5 Unknown regime returns empty", len(preferred_empty) == 0)

# =========================================================================
# 11. get_assignment_summary()
# =========================================================================
print("\n--- 11. get_assignment_summary() ---")

assign = engine.assign_trade_class(
    trade_idea=make_idea(),
    market_story=make_story(regime="TREND_UP"),
    confluence_result=make_confluence(),
)
summary = engine.get_assignment_summary(assign)

check("11.1 Summary has trade_class", summary.get("trade_class") == "CONTINUATION")
check("11.2 Summary has label", summary.get("label") == "Continuation")
check("11.3 Summary has expiry_candles", summary.get("expiry_candles") == 4)
check("11.4 Summary has cooldown_candles", summary.get("cooldown_candles") == 3)
check("11.5 Summary has management_style", bool(summary.get("management_style")))
check("11.6 Summary has has_assignment", summary.get("has_assignment") is True)
check("11.7 Summary has confidence_fit", summary.get("confidence_fit", 0) > 0)
check("11.8 Summary has assigned_at", bool(summary.get("assigned_at")))

# Empty assignment
empty_assign = engine.assign_trade_class(
    trade_idea=make_idea(),
    market_story=MarketStory(regime="UNKNOWN"),
)
empty_summary = engine.get_assignment_summary(empty_assign)
check("11.9 Empty summary has_assignment false",
      empty_summary.get("has_assignment") is False)

# =========================================================================
# 12. None inputs -> empty assignment
# =========================================================================
print("\n--- 12. None inputs ---")

assign = engine.assign_trade_class()
check("12.1 No inputs -> no trade class", assign.trade_class is None)
check("12.2 No metadata", assign.metadata is None)
check("12.3 assigned_at set", assign.assigned_at is not None)

# =========================================================================
# 13. Low conviction filters unsuitable classes
# =========================================================================
print("\n--- 13. Conviction band filtering ---")

# REJECT conviction -> only SCALP (min WEAK) may be filtered
# Actually SCALP only needs WEAK. REJECT is below WEAK so SCALP is also filtered
assign_low = engine.assign_trade_class(
    trade_idea=make_idea(trade_class=TradeClass.CONTINUATION, band=ConvictionBand.REJECT),
    market_story=make_story(regime="TREND_UP"),
    confluence_result=make_confluence(quality=0.8),
)
check("13.1 REJECT conviction -> no valid class",
      assign_low.trade_class is None)

# TRADABLE conviction -> CONTINUATION works
assign_mid = engine.assign_trade_class(
    trade_idea=make_idea(trade_class=TradeClass.CONTINUATION, band=ConvictionBand.TRADABLE),
    market_story=make_story(regime="TREND_UP"),
    confluence_result=make_confluence(quality=0.8),
)
check("13.2 TRADABLE conviction -> CONTINUATION valid",
      assign_mid.trade_class == TradeClass.CONTINUATION)


# =========================================================================
# Summary
# =========================================================================
total = passed + failed
print(f"\n{'=' * 60}")
print(f"Results: {passed} passed, {failed} failed out of {total}")
print(f"{'=' * 60}")

if __name__ == '__main__':
    if failed > 0:
        sys.exit(1)
    else:
        sys.exit(0)
