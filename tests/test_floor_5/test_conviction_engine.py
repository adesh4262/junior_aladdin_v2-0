"""Unit tests for ``conviction_engine.py`` — Floor 5 Step 5.9.

Tests:
- compute_scores() with all inputs high → high scores
- Permission score: gate passes, confluence quality, session phase, psychology
- Permission score: gate blocked → low score
- Conviction score: confluence, opposite case reduction, regime, psychology, session
- Conviction score: strong opposite (>0.7) → >10% reduction
- No-trade score: opposite case, conflict, psychology, unclear regime
- Conviction bands: all 5 bands mapped correctly
- get_conviction_summary() dict
- None inputs → defaults
- Psychology caution/cooldown impacts
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from datetime import datetime

# Fixed timestamp for deterministic session phase (4:30 UTC = 10:00 IST = GOLDEN_MORNING)
_GOLDEN_TIMESTAMP = datetime(2025, 6, 10, 4, 30, 0)

from junior_aladdin.floor_5_captain.conviction_engine import ConvictionEngine, ConvictionBand
from junior_aladdin.floor_5_captain.captain_types import (
    ConfluenceResult,
    ConvictionScore,
    MarketStory,
    OppositeCase,
    PermissionResult,
    SessionPhase,
)
from junior_aladdin.floor_5_captain.session_policy import SessionPolicy
from junior_aladdin.shared.types import (
    BiasType,
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


def make_psych_report(
    trade_allowed: bool = True,
    caution_level: float = 0.0,
    cooldown_active: bool = False,
    trap_pressure: bool = False,
    repeated_mistake: bool = False,
) -> HeadReport:
    return HeadReport(
        head_name="Psychology Head",
        state=HeadState.READY,
        freshness_score=0.9,
        freshness_tag=FreshnessTag.FRESH,
        last_deep_update=datetime.utcnow(),
        bias=BiasType.NEUTRAL,
        confidence=0.0,
        dominant_tf="1m",
        timeframe_view="",
        trade_allowed=trade_allowed,
        caution_level=caution_level,
        cooldown_active=cooldown_active,
        trap_pressure=trap_pressure,
        repeated_mistake_flag=repeated_mistake,
    )


def make_default_perm_result(allowed: bool = True) -> PermissionResult:
    return PermissionResult(
        allowed=allowed,
        block_reason="" if allowed else "Test block",
        blocked_by=[] if allowed else ["test_check"],
    )


def make_default_confluence(quality: float = 0.85, conflict: bool = False) -> ConfluenceResult:
    return ConfluenceResult(
        confluence_quality=quality,
        conflict_present=conflict,
        aligned_heads=["SMC", "ICT", "Technical"],
        opposing_heads=[] if not conflict else ["Options", "Macro"],
        dominant_direction="BULLISH",
    )


def make_default_opposite(strength: float = 0.0, exists: bool = False) -> OppositeCase:
    return OppositeCase(
        exists=exists,
        strength=strength,
        reasons=["Test reason"] if exists else [],
    )


def make_default_story(regime: str = "TREND_UP") -> MarketStory:
    return MarketStory(regime=regime, session_phase=SessionPhase.GOLDEN_MORNING)


print("=" * 60)
print("Floor 5 — Conviction Engine Tests")
print("=" * 60)

engine = ConvictionEngine()
policy = SessionPolicy()

# =========================================================================
# 1. All inputs high -> strong conviction
# =========================================================================
print("\n--- 1. All inputs high (ideal conditions) ---")

scores = engine.compute_scores(
    permission_result=make_default_perm_result(allowed=True),
    confluence_result=make_default_confluence(quality=0.9),
    opposite_case=make_default_opposite(strength=0.0, exists=False),
    market_story=make_default_story(regime="TREND_UP"),
    psychology_report=make_psych_report(trade_allowed=True, caution_level=0.1),
    session_policy=policy,
    timestamp=_GOLDEN_TIMESTAMP,
)

check("1.1 Permission score > 70", scores.permission_score > 70)
check("1.2 Conviction score > 60", scores.conviction_score > 60)
check("1.3 No-trade score < 30", scores.no_trade_score < 30)
check("1.4 Conviction band is STRONG or ELITE",
      scores.conviction_band in (ConvictionBand.STRONG, ConvictionBand.ELITE))
check("1.5 Timestamp set", scores.timestamp is not None)

# =========================================================================
# 2. Permission blocked -> low permission score
# =========================================================================
print("\n--- 2. Permission blocked ---")

scores = engine.compute_scores(
    permission_result=make_default_perm_result(allowed=False),
    confluence_result=make_default_confluence(quality=0.9),
    opposite_case=make_default_opposite(),
    market_story=make_default_story(),
    psychology_report=make_psych_report(),
    session_policy=policy,
    timestamp=_GOLDEN_TIMESTAMP,
)

check("2.1 Permission score < 20 when blocked", scores.permission_score < 20)
check("2.2 Permission score is lowest when blocked",
      scores.permission_score < 10)
check("2.3 Conviction band is independent of permission",
      scores.conviction_band is not None)  # Band computed even when blocked

# =========================================================================
# 3. Strong opposite case -> conviction reduced
# =========================================================================
print("\n--- 3. Strong opposite case ---")

# With strong opposite
scores_with_opposite = engine.compute_scores(
    permission_result=make_default_perm_result(allowed=True),
    confluence_result=make_default_confluence(quality=0.85),
    opposite_case=make_default_opposite(strength=0.8, exists=True),
    market_story=make_default_story(regime="TREND_UP"),
    psychology_report=make_psych_report(),
    session_policy=policy,
    timestamp=_GOLDEN_TIMESTAMP,
)

# Without opposite
scores_without = engine.compute_scores(
    permission_result=make_default_perm_result(allowed=True),
    confluence_result=make_default_confluence(quality=0.85),
    opposite_case=make_default_opposite(strength=0.0, exists=False),
    market_story=make_default_story(regime="TREND_UP"),
    psychology_report=make_psych_report(),
    session_policy=policy,
    timestamp=_GOLDEN_TIMESTAMP,
)

check("3.1 Opposite reduces conviction score",
      scores_with_opposite.conviction_score < scores_without.conviction_score)
check("3.2 Strong opposite -> >10% reduction",
      scores_with_opposite.conviction_score < scores_without.conviction_score * 0.90)

# =========================================================================
# 4. Weak opposite case -> mild reduction
# =========================================================================
print("\n--- 4. Weak opposite case ---")

scores_mild = engine.compute_scores(
    permission_result=make_default_perm_result(allowed=True),
    confluence_result=make_default_confluence(quality=0.85),
    opposite_case=make_default_opposite(strength=0.3, exists=True),
    market_story=make_default_story(regime="TREND_UP"),
    psychology_report=make_psych_report(),
    session_policy=policy,
    timestamp=_GOLDEN_TIMESTAMP,
)

check("4.1 Mild opposite reduces conviction < strong opposite",
      scores_mild.conviction_score > scores_with_opposite.conviction_score)
check("4.2 Mild opposite reduces conviction vs no opposite",
      scores_mild.conviction_score < scores_without.conviction_score)

# =========================================================================
# 5. No-trade score from opposite + conflict
# =========================================================================
print("\n--- 5. No-trade score ---")

scores_high_notrade = engine.compute_scores(
    permission_result=make_default_perm_result(allowed=True),
    confluence_result=make_default_confluence(quality=0.3, conflict=True),
    opposite_case=make_default_opposite(strength=0.8, exists=True),
    market_story=make_default_story(regime="CHOP"),
    psychology_report=make_psych_report(trade_allowed=False),
    session_policy=policy,
    timestamp=_GOLDEN_TIMESTAMP,
)

check("5.1 High no-trade when everything opposes", scores_high_notrade.no_trade_score > 50)
check("5.2 Band is REJECT when no-trade high",
      scores_high_notrade.conviction_band == ConvictionBand.REJECT)

# =========================================================================
# 6. Conviction bands — all 5
# =========================================================================
print("\n--- 6. Conviction bands ---")

# REJECT (very poor conditions)
scores = engine.compute_scores(
    permission_result=make_default_perm_result(allowed=True),
    confluence_result=make_default_confluence(quality=0.1),
    opposite_case=make_default_opposite(strength=0.9, exists=True),
    market_story=make_default_story(regime="CHOP"),
    psychology_report=make_psych_report(trade_allowed=False),
    session_policy=policy,
    timestamp=_GOLDEN_TIMESTAMP,
)
check("6.1 Very poor -> REJECT", scores.conviction_band == ConvictionBand.REJECT)

# TRADABLE (moderate conditions)
scores = engine.compute_scores(
    permission_result=make_default_perm_result(allowed=True),
    confluence_result=make_default_confluence(quality=0.65),
    opposite_case=make_default_opposite(strength=0.4, exists=True),
    market_story=make_default_story(regime="WEAK_UP"),
    psychology_report=make_psych_report(trade_allowed=True, caution_level=0.3),
    session_policy=policy,
    timestamp=_GOLDEN_TIMESTAMP,
)
check("6.2 Moderate -> at least WEAK",
      scores.conviction_band in (ConvictionBand.WEAK, ConvictionBand.TRADABLE))

# STRONG (good conditions)
scores = engine.compute_scores(
    permission_result=make_default_perm_result(allowed=True),
    confluence_result=make_default_confluence(quality=0.85),
    opposite_case=make_default_opposite(strength=0.0, exists=False),
    market_story=make_default_story(regime="TREND_UP"),
    psychology_report=make_psych_report(trade_allowed=True, caution_level=0.0),
    session_policy=policy,
    timestamp=_GOLDEN_TIMESTAMP,
)
check("6.3 Good conditions -> STRONG or ELITE",
      scores.conviction_band in (ConvictionBand.STRONG, ConvictionBand.ELITE))

# =========================================================================
# 7. Psychology impacts
# =========================================================================
print("\n--- 7. Psychology impacts ---")

# Psychology with caution reduces permission
scores_high_caution = engine.compute_scores(
    permission_result=make_default_perm_result(allowed=True),
    confluence_result=make_default_confluence(quality=0.85),
    opposite_case=make_default_opposite(),
    market_story=make_default_story(),
    psychology_report=make_psych_report(trade_allowed=True, caution_level=0.9),
    session_policy=policy,
    timestamp=_GOLDEN_TIMESTAMP,
)

scores_low_caution = engine.compute_scores(
    permission_result=make_default_perm_result(allowed=True),
    confluence_result=make_default_confluence(quality=0.85),
    opposite_case=make_default_opposite(),
    market_story=make_default_story(),
    psychology_report=make_psych_report(trade_allowed=True, caution_level=0.1),
    session_policy=policy,
    timestamp=_GOLDEN_TIMESTAMP,
)

check("7.1 High caution reduces permission", scores_high_caution.permission_score < scores_low_caution.permission_score)
check("7.2 High caution reduces conviction", scores_high_caution.conviction_score < scores_low_caution.conviction_score)
check("7.3 High caution increases no-trade", scores_high_caution.no_trade_score > scores_low_caution.no_trade_score)

# Cooldown active
scores_cooldown = engine.compute_scores(
    permission_result=make_default_perm_result(allowed=True),
    confluence_result=make_default_confluence(quality=0.85),
    opposite_case=make_default_opposite(),
    market_story=make_default_story(),
    psychology_report=make_psych_report(trade_allowed=True, caution_level=0.1, cooldown_active=True),
    session_policy=policy,
    timestamp=_GOLDEN_TIMESTAMP,
)
check("7.4 Cooldown reduces permission vs no cooldown",
      scores_cooldown.permission_score < scores_low_caution.permission_score)

# Psychology blocks
scores_blocked = engine.compute_scores(
    permission_result=make_default_perm_result(allowed=True),
    confluence_result=make_default_confluence(quality=0.85),
    opposite_case=make_default_opposite(),
    market_story=make_default_story(),
    psychology_report=make_psych_report(trade_allowed=False),
    session_policy=policy,
    timestamp=_GOLDEN_TIMESTAMP,
)
check("7.5 Psychology block -> no-trade > 20",
      scores_blocked.no_trade_score > 20)

# =========================================================================
# 8. Regime impacts on conviction
# =========================================================================
print("\n--- 8. Regime impacts ---")

# TREND_UP should give highest conviction
trend_up = engine._compute_conviction_score(
    confluence_result=make_default_confluence(quality=0.5),
    opposite_case=None,
    market_story=make_default_story(regime="TREND_UP"),
    psychology_report=make_psych_report(),
    session_policy=policy,
    dt=_GOLDEN_TIMESTAMP,
)
chop = engine._compute_conviction_score(
    confluence_result=make_default_confluence(quality=0.5),
    opposite_case=None,
    market_story=make_default_story(regime="CHOP"),
    psychology_report=make_psych_report(),
    session_policy=policy,
    dt=_GOLDEN_TIMESTAMP,
)
check("8.1 TREND_UP conviction > CHOP conviction", trend_up > chop)
check("8.2 TREND_UP conviction > RANGE conviction", trend_up > engine._compute_conviction_score(
    confluence_result=make_default_confluence(quality=0.5),
    opposite_case=None,
    market_story=make_default_story(regime="RANGE"),
    psychology_report=make_psych_report(),
    session_policy=policy,
    dt=_GOLDEN_TIMESTAMP,
))

# =========================================================================
# 9. Regime impacts on no-trade
# =========================================================================
print("\n--- 9. Regime impacts on no-trade ---")

chop_notrade = engine._compute_no_trade_score(
    confluence_result=make_default_confluence(quality=0.5),
    opposite_case=None,
    market_story=make_default_story(regime="CHOP"),
    psychology_report=None,
)
trend_notrade = engine._compute_no_trade_score(
    confluence_result=make_default_confluence(quality=0.5),
    opposite_case=None,
    market_story=make_default_story(regime="TREND_UP"),
    psychology_report=None,
)
check("9.1 CHOP no-trade > TREND_UP no-trade", chop_notrade > trend_notrade)

# =========================================================================
# 10. None inputs -> defaults
# =========================================================================
print("\n--- 10. None inputs ---")

scores = engine.compute_scores()
check("10.1 Default permission 0", scores.permission_score == 0.0)
check("10.2 Default conviction 0", scores.conviction_score == 0.0)
check("10.3 Default no-trade 0", scores.no_trade_score == 0.0)
check("10.4 Default band REJECT", scores.conviction_band == ConvictionBand.REJECT)
check("10.5 Default timestamp not None", scores.timestamp is not None)

# =========================================================================
# 11. get_conviction_summary()
# =========================================================================
print("\n--- 11. get_conviction_summary() ---")

scores = engine.compute_scores(
    permission_result=make_default_perm_result(allowed=True),
    confluence_result=make_default_confluence(quality=0.85),
    opposite_case=make_default_opposite(),
    market_story=make_default_story(),
    psychology_report=make_psych_report(),
    session_policy=policy,
    timestamp=_GOLDEN_TIMESTAMP,
)
summary = engine.get_conviction_summary(scores)

check("11.1 Summary has permission_score", summary.get("permission_score") is not None)
check("11.2 Summary has conviction_score", summary.get("conviction_score") is not None)
check("11.3 Summary has no_trade_score", summary.get("no_trade_score") is not None)
check("11.4 Summary has conviction_band", summary.get("conviction_band") is not None)
check("11.5 Summary has trade_viable", summary.get("trade_viable") is not None)
check("11.6 Summary has needs_confirmation", "needs_confirmation" in summary)
check("11.7 Summary has timestamp", summary.get("timestamp") is not None)

# Trade viable for STRONG band
check("11.8 Trade viable for high scores", summary.get("trade_viable") is True)

# Not trade viable for reject
scores_low = engine.compute_scores(
    permission_result=make_default_perm_result(allowed=True),
    confluence_result=make_default_confluence(quality=0.1),
    opposite_case=make_default_opposite(strength=0.9, exists=True),
    market_story=make_default_story(regime="CHOP"),
    psychology_report=make_psych_report(trade_allowed=False),
    session_policy=policy,
    timestamp=_GOLDEN_TIMESTAMP,
)
summary_low = engine.get_conviction_summary(scores_low)
check("11.9 Not trade viable for low scores", summary_low.get("trade_viable") is False)


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
