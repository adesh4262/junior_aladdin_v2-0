"""Unit tests for ``market_story_engine.py`` — Floor 5 Step 5.5.

Tests:
- build_story() with all inputs → full MarketStory
- build_story() with no inputs → sensible defaults
- Regime detection: TREND_UP, TREND_DOWN, RANGE, CHOP, UNCLEAR
- Session phase detection (via SessionPolicy)
- Premium/discount location from SMC/ICT reports
- Key level interaction from head report active_zones
- Directional bias from Floor Summary + head reports
- Summary text construction with all components
- get_market_context() returns dict
- Fallback behavior when Floor Summary is None
- Fallback behavior when specific head reports are missing
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from datetime import datetime, timezone

from junior_aladdin.floor_5_captain.market_story_engine import MarketStoryEngine
from junior_aladdin.floor_5_captain.session_policy import SessionPolicy
from junior_aladdin.floor_5_captain.captain_types import SessionPhase
from junior_aladdin.shared.types import (
    BiasType,
    DataHealth,
    FloorSummary,
    FreshnessTag,
    HeadReport,
    HeadState,
)

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


def make_report(
    name: str,
    bias: BiasType = BiasType.NEUTRAL,
    confidence: float = 0.5,
    zones: list | None = None,
    witness: str = "",
    state: HeadState = HeadState.READY,
    trade_allowed: bool = True,
) -> HeadReport:
    """Create a HeadReport with the given parameters."""
    return HeadReport(
        head_name=name,
        state=state,
        freshness_score=0.8,
        freshness_tag=FreshnessTag.FRESH,
        last_deep_update=datetime.utcnow(),
        bias=bias,
        confidence=confidence,
        dominant_tf="1m",
        timeframe_view="",
        active_zones=zones or [],
        witness_summary=witness,
        trade_allowed=trade_allowed,
    )


def make_floor_summary(
    bias: str = "NEUTRAL",
    confidence: float = 0.5,
    conflict: bool = False,
    ready: int = 5,
    uncertain: int = 0,
    stale: int = 0,
    witnesses: list[str] | None = None,
) -> FloorSummary:
    """Create a FloorSummary with the given parameters."""
    return FloorSummary(
        summary_timestamp=datetime.utcnow(),
        floor_bias_snapshot={"dominant_bias": bias},
        floor_confidence_snapshot={"average_confidence": confidence},
        ready_heads_count=ready,
        uncertain_heads_count=uncertain,
        stale_heads_count=stale,
        conflict_present=conflict,
        summary_witness_lines=witnesses or [],
        data_health_signal=DataHealth.GOOD,
    )


def utc_to_ist_dt(ist_hour: int, ist_minute: int, weekday: int = 0) -> datetime:
    """Create a UTC datetime that corresponds to the given IST time."""
    total_ist_minutes = ist_hour * 60 + ist_minute
    total_utc_minutes = total_ist_minutes - 330
    total_utc_minutes = total_utc_minutes % (24 * 60)
    utc_hour, utc_minute = divmod(total_utc_minutes, 60)
    return datetime(2026, 6, 8 + weekday, utc_hour, utc_minute, tzinfo=timezone.utc)


print("=" * 60)
print("Floor 5 — Market Story Engine Tests")
print("=" * 60)

engine = MarketStoryEngine(SessionPolicy())

# =========================================================================
# 1. Build story with all inputs (golden morning, bullish)
# =========================================================================
print("\n--- 1. build_story() — full inputs ---")

dt_golden = utc_to_ist_dt(10, 0, weekday=0)  # Mon 10:00 IST = GOLDEN_MORNING

reports = {
    "SMC Head": make_report("SMC Head", BiasType.BULLISH, 0.85, zones=[{"label": "FVG retest zone 19550-19580"}]),
    "ICT Head": make_report("ICT Head", BiasType.BULLISH, 0.75),
    "Technical Head": make_report("Technical Head", BiasType.BULLISH, 0.65),
    "Options Head": make_report("Options Head", BiasType.BULLISH, 0.55),
    "Macro Head": make_report("Macro Head", BiasType.NEUTRAL, 0.40),
    "Psychology Head": make_report("Psychology Head", BiasType.NEUTRAL, 0.0, trade_allowed=True),
}

summary = make_floor_summary(
    bias="BULLISH",
    confidence=0.80,
    witnesses=["Strong bullish structure", "All core heads aligned"],
)

story = engine.build_story(
    floor_summary=summary,
    head_reports=reports,
    timestamp=dt_golden,
)

check("1.1 Regime TREND_UP", story.regime == "TREND_UP")
check("1.2 Session GOLDEN_MORNING", story.session_phase == SessionPhase.GOLDEN_MORNING)
check("1.3 Bias BULLISH", story.bias == "BULLISH")
check("1.4 Premium discount mentions Discount", "Discount" in story.premium_discount_location)
check("1.5 Key levels contains FVG", "FVG" in story.key_levels_interaction)
check("1.6 Summary contains Regime", "TREND_UP" in story.summary)
check("1.7 Summary contains session", "Golden Morning" in story.summary)
check("1.8 Summary contains witness", "aligned" in story.summary)
check("1.9 Timestamp set", story.timestamp is not None)

# =========================================================================
# 2. Build story with no inputs (sensible defaults)
# =========================================================================
print("\n--- 2. build_story() — no inputs ---")

story_default = engine.build_story()

check("2.1 Default regime UNCLEAR or RANGE",
      story_default.regime in ("UNCLEAR", "RANGE", "CHOP"))
check("2.2 Default session phase is a SessionPhase",
      isinstance(story_default.session_phase, SessionPhase))
check("2.3 Default bias NEUTRAL", story_default.bias == "NEUTRAL")
check("2.4 Default premium Around Equilibrium",
      "Equilibrium" in story_default.premium_discount_location)
check("2.5 Default key levels mentions No active",
      "No active" in story_default.key_levels_interaction)
check("2.6 Default summary is non-empty", len(story_default.summary) > 0)
check("2.7 Default timestamp set", story_default.timestamp is not None)

# =========================================================================
# 3. Regime detection — TREND_DOWN
# =========================================================================
print("\n--- 3. Regime detection: TREND_DOWN ---")

summary_bear = make_floor_summary(bias="BEARISH", confidence=0.85)
story = engine.build_story(floor_summary=summary_bear, head_reports={}, timestamp=dt_golden)
check("3.1 BEARISH + high confidence -> TREND_DOWN", story.regime == "TREND_DOWN")

summary_bear_weak = make_floor_summary(bias="BEARISH", confidence=0.55)
story = engine.build_story(floor_summary=summary_bear_weak, head_reports={}, timestamp=dt_golden)
check("3.2 BEARISH + medium confidence -> WEAK_DOWN", story.regime == "WEAK_DOWN")

summary_bear_low = make_floor_summary(bias="BEARISH", confidence=0.3)
story = engine.build_story(floor_summary=summary_bear_low, head_reports={}, timestamp=dt_golden)
check("3.3 BEARISH + low confidence -> RANGE", story.regime == "RANGE")

# =========================================================================
# 4. Regime detection — RANGE, CHOP, UNCLEAR
# =========================================================================
print("\n--- 4. Regime: RANGE, CHOP, UNCLEAR ---")

# NEUTRAL + no conflict = RANGE
summary_neutral = make_floor_summary(bias="NEUTRAL", confidence=0.5, conflict=False)
story = engine.build_story(floor_summary=summary_neutral, head_reports={}, timestamp=dt_golden)
check("4.1 NEUTRAL + no conflict -> RANGE", story.regime == "RANGE")

# NEUTRAL + conflict = CHOP
summary_chop = make_floor_summary(bias="NEUTRAL", confidence=0.5, conflict=True)
story = engine.build_story(floor_summary=summary_chop, head_reports={}, timestamp=dt_golden)
check("4.2 NEUTRAL + conflict -> CHOP", story.regime == "CHOP")

# Conflict + low confidence = CHOP
summary_conflict_low = make_floor_summary(bias="BULLISH", confidence=0.2, conflict=True)
story = engine.build_story(floor_summary=summary_conflict_low, head_reports={}, timestamp=dt_golden)
check("4.3 Conflict + low confidence -> CHOP", story.regime == "CHOP")

# Too many stale heads = UNCLEAR
summary_stale = make_floor_summary(bias="BULLISH", confidence=0.8, stale=4, ready=2)
story = engine.build_story(floor_summary=summary_stale, head_reports={}, timestamp=dt_golden)
check("4.4 >50% stale heads -> UNCLEAR", story.regime == "UNCLEAR")

# No floor summary — fallback
story = engine.build_story(floor_summary=None, head_reports={}, timestamp=dt_golden)
check("4.5 No floor summary -> UNCLEAR", story.regime == "UNCLEAR")

# =========================================================================
# 5. Session phase detection
# =========================================================================
print("\n--- 5. Session phase detection ---")

dt_opening = utc_to_ist_dt(9, 30, weekday=0)
story = engine.build_story(timestamp=dt_opening)
check("5.1 9:30 IST -> OPENING", story.session_phase == SessionPhase.OPENING)

dt_lunch = utc_to_ist_dt(12, 0, weekday=0)
story = engine.build_story(timestamp=dt_lunch)
check("5.2 12:00 IST -> LUNCH", story.session_phase == SessionPhase.LUNCH)

dt_closing = utc_to_ist_dt(14, 0, weekday=0)
story = engine.build_story(timestamp=dt_closing)
check("5.3 14:00 IST -> CLOSING", story.session_phase == SessionPhase.CLOSING)

# =========================================================================
# 6. Premium/discount location
# =========================================================================
print("\n--- 6. Premium/discount location ---")

# SMC bullish = Discount
reports_bull = {"SMC Head": make_report("SMC Head", BiasType.BULLISH, 0.8)}
story = engine.build_story(head_reports=reports_bull, timestamp=dt_golden)
check("6.1 SMC bullish -> Discount", "Discount" in story.premium_discount_location)

# ICT bearish = Premium
reports_bear = {"ICT Head": make_report("ICT Head", BiasType.BEARISH, 0.8)}
story = engine.build_story(head_reports=reports_bear, timestamp=dt_golden)
check("6.2 ICT bearish -> Premium", "Premium" in story.premium_discount_location)

# Neutral = Equilibrium
reports_neutral = {"Technical Head": make_report("Technical Head", BiasType.NEUTRAL, 0.5)}
story = engine.build_story(head_reports=reports_neutral, timestamp=dt_golden)
check("6.3 Technical neutral -> Equilibrium", "Equilibrium" in story.premium_discount_location)

# No reports = Equilibrium
story = engine.build_story(head_reports={}, timestamp=dt_golden)
check("6.4 No reports -> Equilibrium", "Equilibrium" in story.premium_discount_location)

# =========================================================================
# 7. Key level interactions
# =========================================================================
print("\n--- 7. Key level interactions ---")

# Reports with zones
reports_with_zones = {
    "SMC Head": make_report("SMC Head", BiasType.BULLISH, 0.8,
                            zones=[{"label": "FVG 19550-19580"}, {"label": "OB 19500"}]),
    "ICT Head": make_report("ICT Head", BiasType.BULLISH, 0.7,
                            zones=[{"label": "PDH 19600"}]),
    "Technical Head": make_report("Technical Head", BiasType.NEUTRAL, 0.5),
}
story = engine.build_story(head_reports=reports_with_zones, timestamp=dt_golden)
check("7.1 Key levels mentions FVG", "FVG" in story.key_levels_interaction)
check("7.2 Key levels mentions PDH", "PDH" in story.key_levels_interaction)
check("7.3 Key levels mentions OB", "OB" in story.key_levels_interaction)

# No zones
reports_no_zones = {
    "Technical Head": make_report("Technical Head", BiasType.NEUTRAL, 0.5),
}
story = engine.build_story(head_reports=reports_no_zones, timestamp=dt_golden)
check("7.4 No zones -> No active key levels", "No active" in story.key_levels_interaction)

# Psychology head zones should be ignored
reports_psych_only = {
    "Psychology Head": make_report("Psychology Head", BiasType.NEUTRAL, 0.0,
                                   zones=[{"label": "Trap zone 19500"}]),
}
story = engine.build_story(head_reports=reports_psych_only, timestamp=dt_golden)
check("7.5 Psychology zones ignored -> No active", "No active" in story.key_levels_interaction)

# =========================================================================
# 8. Directional bias from Floor Summary
# =========================================================================
print("\n--- 8. Directional bias ---")

summary_bull = make_floor_summary(bias="BULLISH", confidence=0.8)
story = engine.build_story(floor_summary=summary_bull, timestamp=dt_golden)
check("8.1 Floor summary BULLISH -> BULLISH", story.bias == "BULLISH")

summary_bear = make_floor_summary(bias="BEARISH", confidence=0.8)
story = engine.build_story(floor_summary=summary_bear, timestamp=dt_golden)
check("8.2 Floor summary BEARISH -> BEARISH", story.bias == "BEARISH")

# No floor summary — fallback to head reports
reports_bullish = {
    "SMC Head": make_report("SMC Head", BiasType.BULLISH, 0.8),
    "ICT Head": make_report("ICT Head", BiasType.BULLISH, 0.7),
    "Technical Head": make_report("Technical Head", BiasType.BEARISH, 0.5),
}
story = engine.build_story(floor_summary=None, head_reports=reports_bullish, timestamp=dt_golden)
check("8.3 Fallback: 2 bullish vs 1 bearish -> BULLISH", story.bias == "BULLISH")

# Equal count → NEUTRAL
reports_tie = {
    "SMC Head": make_report("SMC Head", BiasType.BULLISH, 0.8),
    "ICT Head": make_report("ICT Head", BiasType.BEARISH, 0.7),
    "Technical Head": make_report("Technical Head", BiasType.NEUTRAL, 0.5),
}
story = engine.build_story(floor_summary=None, head_reports=reports_tie, timestamp=dt_golden)
check("8.4 Fallback: 1 bull vs 1 bear + neutral -> NEUTRAL", story.bias == "NEUTRAL")

# No head reports at all
story = engine.build_story(floor_summary=None, head_reports={}, timestamp=dt_golden)
check("8.5 No floor summary, no heads -> NEUTRAL", story.bias == "NEUTRAL")

# =========================================================================
# 9. get_market_context()
# =========================================================================
print("\n--- 9. get_market_context() ---")

context = engine.get_market_context(
    floor_summary=make_floor_summary(bias="BULLISH", confidence=0.8),
    head_reports={
        "SMC Head": make_report("SMC Head", BiasType.BULLISH, 0.85),
    },
    timestamp=dt_golden,
)
check("9.1 Context has regime", context.get("regime") == "TREND_UP")
check("9.2 Context has session_phase", context.get("session_phase") == "GOLDEN_MORNING")
check("9.3 Context has bias", context.get("bias") == "BULLISH")
check("9.4 Context has premium_discount", len(context.get("premium_discount", "")) > 0)
check("9.5 Context has summary", len(context.get("summary", "")) > 0)
check("9.6 Context has timestamp", len(context.get("timestamp", "")) > 0)

# Default context (no args)
context_default = engine.get_market_context()
check("9.7 Default context has all fields",
      all(k in context_default for k in ("regime", "session_phase", "bias",
                                          "premium_discount", "summary", "timestamp")))

# =========================================================================
# 10. Edge: Mixed regimes with witness lines
# =========================================================================
print("\n--- 10. Summary with witness lines ---")

summary_with_witness = make_floor_summary(
    bias="BULLISH",
    confidence=0.75,
    witnesses=["PDH being tested at 19600", "Core head health: all READY"],
)

reports_strong = {
    "SMC Head": make_report("SMC Head", BiasType.BULLISH, 0.9,
                            zones=[{"label": "ORB high 19580"}]),
    "ICT Head": make_report("ICT Head", BiasType.BULLISH, 0.8),
    "Technical Head": make_report("Technical Head", BiasType.NEUTRAL, 0.5),
    "Options Head": make_report("Options Head", BiasType.BULLISH, 0.6),
    "Macro Head": make_report("Macro Head", BiasType.NEUTRAL, 0.4),
    "Psychology Head": make_report("Psychology Head", BiasType.NEUTRAL, 0.0, trade_allowed=True),
}

story = engine.build_story(
    floor_summary=summary_with_witness,
    head_reports=reports_strong,
    timestamp=utc_to_ist_dt(9, 50, weekday=0),
)
check("10.1 All components present in summary",
      all(word in story.summary for word in ["TREND_UP", "Golden", "Morning", "Bullish", "ORB", "PDH"]))
check("10.2 Regime TREND_UP", story.regime == "TREND_UP")
check("10.3 Bias BULLISH", story.bias == "BULLISH")


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
