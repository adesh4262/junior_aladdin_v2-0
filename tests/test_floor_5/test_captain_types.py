"""Unit tests for ``captain_types.py`` — Floor 5 Step 5.1.

Tests:
- DecisionState enum (4 members)
- ConvictionBand enum (5 members + score mapping)
- ArmedPlanState enum (5 members)
- SilenceReason enum (11 members)
- InterventionSeverity enum (3 members)
- SessionPhase enum (4 members)
- ReportTrustTier enum (3 members)
- CaptainInput dataclass
- CaptainState dataclass
- PermissionResult dataclass
- MarketStory dataclass
- NarrativeTimelineEvent + NarrativeTimeline dataclasses
- ConfluenceResult dataclass
- OppositeCase dataclass
- ConvictionScore dataclass + conviction_score_to_band()
- get_session_phase_from_time() helper
- get_aggression_modifier() helper
- get_permission_strictness() helper
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from datetime import datetime
from dataclasses import fields

from junior_aladdin.floor_5_captain.captain_types import (
    DecisionState,
    ConvictionBand,
    ArmedPlanState,
    SilenceReason,
    InterventionSeverity,
    SessionPhase,
    ReportTrustTier,
    CaptainInput,
    CaptainState,
    PermissionResult,
    MarketStory,
    NarrativeTimelineEvent,
    NarrativeTimeline,
    ConfluenceResult,
    OppositeCase,
    ConvictionScore,
    conviction_score_to_band,
    get_session_phase_from_time,
    get_aggression_modifier,
    get_permission_strictness,
)
from junior_aladdin.shared.types import CaptainMood, FloorSummary, HeadReport, HeadState, BiasType, FreshnessTag

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


print("=" * 60)
print("Floor 5 — Captain Types Tests")
print("=" * 60)

# =========================================================================
# 1. DecisionState enum
# =========================================================================
print("\n--- 1. DecisionState enum ---")

check("1.1 Has TRADE", DecisionState.TRADE.value == "TRADE")
check("1.2 Has WAIT", DecisionState.WAIT.value == "WAIT")
check("1.3 Has BLOCKED", DecisionState.BLOCKED.value == "BLOCKED")
check("1.4 Has PREPARED", DecisionState.PREPARED.value == "PREPARED")
check("1.5 Total 4 members", len(list(DecisionState)) == 4)

# =========================================================================
# 2. ConvictionBand enum
# =========================================================================
print("\n--- 2. ConvictionBand enum ---")

check("2.1 Has REJECT", ConvictionBand.REJECT.value == "REJECT")
check("2.2 Has WEAK", ConvictionBand.WEAK.value == "WEAK")
check("2.3 Has TRADABLE", ConvictionBand.TRADABLE.value == "TRADABLE")
check("2.4 Has STRONG", ConvictionBand.STRONG.value == "STRONG")
check("2.5 Has ELITE", ConvictionBand.ELITE.value == "ELITE")
check("2.6 Total 5 members", len(list(ConvictionBand)) == 5)

# =========================================================================
# 3. ArmedPlanState enum
# =========================================================================
print("\n--- 3. ArmedPlanState enum ---")

check("3.1 Has WATCHING", ArmedPlanState.WATCHING.value == "WATCHING")
check("3.2 Has TRIGGERED", ArmedPlanState.TRIGGERED.value == "TRIGGERED")
check("3.3 Has EXPIRED", ArmedPlanState.EXPIRED.value == "EXPIRED")
check("3.4 Has INVALIDATED", ArmedPlanState.INVALIDATED.value == "INVALIDATED")
check("3.5 Has CANCELLED", ArmedPlanState.CANCELLED.value == "CANCELLED")
check("3.6 Total 5 members", len(list(ArmedPlanState)) == 5)

# =========================================================================
# 4. SilenceReason enum
# =========================================================================
print("\n--- 4. SilenceReason enum ---")

check("4.1 Has INSUFFICIENT_CONFLUENCE", SilenceReason.INSUFFICIENT_CONFLUENCE.value == "INSUFFICIENT_CONFLUENCE")
check("4.2 Has PSYCHOLOGY_BLOCK", SilenceReason.PSYCHOLOGY_BLOCK.value == "PSYCHOLOGY_BLOCK")
check("4.3 Has ACTIVE_TRADE_EXISTS", SilenceReason.ACTIVE_TRADE_EXISTS.value == "ACTIVE_TRADE_EXISTS")
check("4.4 Has DEAD_MARKET", SilenceReason.DEAD_MARKET.value == "DEAD_MARKET")
check("4.5 Has TRAP_RISK_HIGH", SilenceReason.TRAP_RISK_HIGH.value == "TRAP_RISK_HIGH")
check("4.6 Has STALE_SETUP", SilenceReason.STALE_SETUP.value == "STALE_SETUP")
check("4.7 Has PLAN_EXPIRED", SilenceReason.PLAN_EXPIRED.value == "PLAN_EXPIRED")
check("4.8 Has NARRATIVE_SHIFT", SilenceReason.NARRATIVE_SHIFT.value == "NARRATIVE_SHIFT")
check("4.9 Has CAPITAL_MISMATCH", SilenceReason.CAPITAL_MISMATCH.value == "CAPITAL_MISMATCH")
check("4.10 Has REAL_MODE_LOCK", SilenceReason.REAL_MODE_LOCK.value == "REAL_MODE_LOCK")
check("4.11 Has WEAK_CONVICTION", SilenceReason.WEAK_CONVICTION.value == "WEAK_CONVICTION")
check("4.12 Total 11 members", len(list(SilenceReason)) == 11)

# =========================================================================
# 5. InterventionSeverity enum
# =========================================================================
print("\n--- 5. InterventionSeverity enum ---")

check("5.1 Has NORMAL", InterventionSeverity.NORMAL.value == "NORMAL")
check("5.2 Has CAUTION", InterventionSeverity.CAUTION.value == "CAUTION")
check("5.3 Has EMERGENCY_OVERRIDE", InterventionSeverity.EMERGENCY_OVERRIDE.value == "EMERGENCY_OVERRIDE")
check("5.4 Total 3 members", len(list(InterventionSeverity)) == 3)

# =========================================================================
# 6. SessionPhase enum
# =========================================================================
print("\n--- 6. SessionPhase enum ---")

check("6.1 Has OPENING", SessionPhase.OPENING.value == "OPENING")
check("6.2 Has GOLDEN_MORNING", SessionPhase.GOLDEN_MORNING.value == "GOLDEN_MORNING")
check("6.3 Has LUNCH", SessionPhase.LUNCH.value == "LUNCH")
check("6.4 Has CLOSING", SessionPhase.CLOSING.value == "CLOSING")
check("6.5 Total 4 members", len(list(SessionPhase)) == 4)

# =========================================================================
# 7. ReportTrustTier enum
# =========================================================================
print("\n--- 7. ReportTrustTier enum ---")

check("7.1 Has FULL", ReportTrustTier.FULL.value == "FULL")
check("7.2 Has REDUCED", ReportTrustTier.REDUCED.value == "REDUCED")
check("7.3 Has MINIMAL", ReportTrustTier.MINIMAL.value == "MINIMAL")
check("7.4 Total 3 members", len(list(ReportTrustTier)) == 3)

# =========================================================================
# 8. CaptainInput dataclass
# =========================================================================
print("\n--- 8. CaptainInput dataclass ---")

ci_default = CaptainInput()
check("8.1 Default floor_summary has summary_timestamp", ci_default.floor_summary.summary_timestamp is not None)
check("8.2 Default head_reports empty", len(ci_default.head_reports) == 0)
check("8.3 Default system_context empty", len(ci_default.system_context) == 0)
check("8.4 Total 3 fields", len(fields(CaptainInput)) == 3)

ci_custom = CaptainInput(
    floor_summary=FloorSummary(summary_timestamp=datetime.utcnow()),
    head_reports={
        "SMC Head": HeadReport(
            head_name="SMC Head",
            state=HeadState.READY,
            freshness_score=0.9,
            freshness_tag=FreshnessTag.FRESH,
            last_deep_update=datetime.utcnow(),
            bias=BiasType.BULLISH,
            confidence=0.75,
            dominant_tf="1m",
            timeframe_view="Bullish structure intact",
        ),
    },
    system_context={"mode": "PAPER", "capital": 50000},
)
check("8.5 Custom floor_summary set", ci_custom.floor_summary is not None)
check("8.6 Custom head_reports has SMC Head", "SMC Head" in ci_custom.head_reports)
check("8.7 Custom system_context has mode", ci_custom.system_context.get("mode") == "PAPER")

# =========================================================================
# 9. CaptainState dataclass
# =========================================================================
print("\n--- 9. CaptainState dataclass ---")

cs_default = CaptainState()
check("9.1 Default mood OBSERVER", cs_default.mood == CaptainMood.OBSERVER)
check("9.2 Default active_trade False", cs_default.active_trade is False)
check("9.3 Default decision_state WAIT", cs_default.decision_state == DecisionState.WAIT)
check("9.4 Default conviction_band REJECT", cs_default.conviction_band == ConvictionBand.REJECT)
check("9.5 Default session_phase OPENING", cs_default.session_phase == SessionPhase.OPENING)
check("9.6 Default real_mode_locked False", cs_default.real_mode_locked is False)
check("9.7 Total 8 fields", len(fields(CaptainState)) == 8)

cs_custom = CaptainState(
    mood=CaptainMood.AGGRESSIVE,
    active_trade=True,
    decision_state=DecisionState.TRADE,
    conviction_band=ConvictionBand.STRONG,
    market_story_summary="Strong bullish day",
    silence_reason="",
    session_phase=SessionPhase.GOLDEN_MORNING,
    real_mode_locked=False,
)
check("9.8 Custom mood", cs_custom.mood == CaptainMood.AGGRESSIVE)
check("9.9 Custom active_trade", cs_custom.active_trade is True)
check("9.10 Custom decision_state", cs_custom.decision_state == DecisionState.TRADE)

# =========================================================================
# 10. PermissionResult dataclass
# =========================================================================
print("\n--- 10. PermissionResult dataclass ---")

pr_default = PermissionResult()
check("10.1 Default allowed True", pr_default.allowed is True)
check("10.2 Default block_reason empty", pr_default.block_reason == "")
check("10.3 Default blocked_by empty", len(pr_default.blocked_by) == 0)
check("10.4 Total 4 fields", len(fields(PermissionResult)) == 4)

pr_blocked = PermissionResult(
    allowed=False,
    block_reason="Psychology block active",
    blocked_by=["psychology_block"],
)
check("10.5 Blocked allowed False", pr_blocked.allowed is False)
check("10.6 Blocked reason set", "Psychology" in pr_blocked.block_reason)
check("10.7 Blocked blocked_by has psychology_block", "psychology_block" in pr_blocked.blocked_by)

# =========================================================================
# 11. MarketStory dataclass
# =========================================================================
print("\n--- 11. MarketStory dataclass ---")

ms_default = MarketStory()
check("11.1 Default regime empty", ms_default.regime == "")
check("11.2 Default session_phase OPENING", ms_default.session_phase == SessionPhase.OPENING)
check("11.3 Default bias NEUTRAL", ms_default.bias == "NEUTRAL")
check("11.4 Total 7 fields", len(fields(MarketStory)) == 7)

ms_custom = MarketStory(
    regime="TREND_UP",
    session_phase=SessionPhase.GOLDEN_MORNING,
    premium_discount_location="Premium",
    key_levels_interaction="Above PDH",
    bias="BULLISH",
    summary="Strong trend day with institutional buying",
)
check("11.5 Custom regime", ms_custom.regime == "TREND_UP")
check("11.6 Custom summary", "institutional buying" in ms_custom.summary)

# =========================================================================
# 12. NarrativeTimelineEvent + NarrativeTimeline
# =========================================================================
print("\n--- 12. NarrativeTimeline ---")

nte_default = NarrativeTimelineEvent()
check("12.1 Default event_type empty", nte_default.event_type == "")
check("12.2 Default price_level 0.0", nte_default.price_level == 0.0)
check("12.3 Total 4 fields", len(fields(NarrativeTimelineEvent)) == 4)

nte_custom = NarrativeTimelineEvent(
    event_type="liquidity_sweep",
    details="PDH sweep at 19650",
    price_level=19650.0,
)
check("12.4 Custom event_type", nte_custom.event_type == "liquidity_sweep")
check("12.5 Custom price_level", nte_custom.price_level == 19650.0)

nt_default = NarrativeTimeline()
check("12.6 Default events empty", len(nt_default.events) == 0)
check("12.7 Default event_count 0", nt_default.event_count == 0)
check("12.8 Total 3 fields", len(fields(NarrativeTimeline)) == 3)

nt_with_events = NarrativeTimeline(
    events=[nte_custom],
    event_count=1,
)
check("12.9 Custom events count", len(nt_with_events.events) == 1)
check("12.10 Custom event_count", nt_with_events.event_count == 1)

# =========================================================================
# 13. ConfluenceResult dataclass
# =========================================================================
print("\n--- 13. ConfluenceResult dataclass ---")

cr_default = ConfluenceResult()
check("13.1 Default confluence_quality 0.0", cr_default.confluence_quality == 0.0)
check("13.2 Default conflict_present False", cr_default.conflict_present is False)
check("13.3 Default dominant_direction NEUTRAL", cr_default.dominant_direction == "NEUTRAL")
check("13.4 Total 7 fields", len(fields(ConfluenceResult)) == 7)

cr_custom = ConfluenceResult(
    confluence_quality=0.85,
    conflict_present=False,
    aligned_heads=["SMC Head", "ICT Head", "Technical Head"],
    opposing_heads=["Macro Head"],
    dominant_direction="BULLISH",
    weighting_summary={"SMC Head": 1.0, "ICT Head": 0.9, "Technical Head": 0.7, "Macro Head": 0.3},
)
check("13.5 Custom quality", cr_custom.confluence_quality == 0.85)
check("13.6 Custom aligned 3 heads", len(cr_custom.aligned_heads) == 3)
check("13.7 Custom dominant BULLISH", cr_custom.dominant_direction == "BULLISH")

# =========================================================================
# 14. OppositeCase dataclass
# =========================================================================
print("\n--- 14. OppositeCase dataclass ---")

oc_default = OppositeCase()
check("14.1 Default exists False", oc_default.exists is False)
check("14.2 Default strength 0.0", oc_default.strength == 0.0)
check("14.3 Default reasons empty", len(oc_default.reasons) == 0)
check("14.4 Total 4 fields", len(fields(OppositeCase)) == 4)

oc_custom = OppositeCase(
    exists=True,
    strength=0.6,
    reasons=["Nearby resistance at 19700", "Bearish RSI divergence"],
    mitigating_factors=["Strong volume supporting breakout"],
)
check("14.5 Custom exists True", oc_custom.exists is True)
check("14.6 Custom strength", oc_custom.strength == 0.6)
check("14.7 Custom 2 reasons", len(oc_custom.reasons) == 2)
check("14.8 Custom 1 mitigating factor", len(oc_custom.mitigating_factors) == 1)

# =========================================================================
# 15. ConvictionScore dataclass + conviction_score_to_band()
# =========================================================================
print("\n--- 15. ConvictionScore + conviction_score_to_band() ---")

cs_default = ConvictionScore()
check("15.1 Default scores 0.0", cs_default.permission_score == 0.0 and cs_default.conviction_score == 0.0)
check("15.2 Default band REJECT", cs_default.conviction_band == ConvictionBand.REJECT)
check("15.3 Total 5 fields", len(fields(ConvictionScore)) == 5)

# Test conviction_score_to_band boundaries
check("15.4 Score 0 -> REJECT", conviction_score_to_band(0) == ConvictionBand.REJECT)
check("15.5 Score 30 -> REJECT", conviction_score_to_band(30) == ConvictionBand.REJECT)
check("15.6 Score 39 -> REJECT", conviction_score_to_band(39) == ConvictionBand.REJECT)
check("15.7 Score 40 -> WEAK", conviction_score_to_band(40) == ConvictionBand.WEAK)
check("15.8 Score 55 -> WEAK", conviction_score_to_band(55) == ConvictionBand.WEAK)
check("15.9 Score 59 -> WEAK", conviction_score_to_band(59) == ConvictionBand.WEAK)
check("15.10 Score 60 -> TRADABLE", conviction_score_to_band(60) == ConvictionBand.TRADABLE)
check("15.11 Score 70 -> TRADABLE", conviction_score_to_band(70) == ConvictionBand.TRADABLE)
check("15.12 Score 74 -> TRADABLE", conviction_score_to_band(74) == ConvictionBand.TRADABLE)
check("15.13 Score 75 -> STRONG", conviction_score_to_band(75) == ConvictionBand.STRONG)
check("15.14 Score 80 -> STRONG", conviction_score_to_band(80) == ConvictionBand.STRONG)
check("15.15 Score 89 -> STRONG", conviction_score_to_band(89) == ConvictionBand.STRONG)
check("15.16 Score 90 -> ELITE", conviction_score_to_band(90) == ConvictionBand.ELITE)
check("15.17 Score 95 -> ELITE", conviction_score_to_band(95) == ConvictionBand.ELITE)
check("15.18 Score 100 -> ELITE", conviction_score_to_band(100) == ConvictionBand.ELITE)
check("15.19 Negative score -> REJECT", conviction_score_to_band(-5) == ConvictionBand.REJECT)

cs_custom = ConvictionScore(
    permission_score=85.0,
    conviction_score=78.0,
    no_trade_score=15.0,
    conviction_band=ConvictionBand.STRONG,
)
check("15.20 Custom scores", cs_custom.permission_score == 85.0 and cs_custom.conviction_score == 78.0)
check("15.21 Custom band", cs_custom.conviction_band == ConvictionBand.STRONG)

# =========================================================================
# 16. get_session_phase_from_time()
# =========================================================================
print("\n--- 16. get_session_phase_from_time() ---")

check("16.1 9:15 -> OPENING", get_session_phase_from_time(9, 15) == SessionPhase.OPENING)
check("16.2 9:30 -> OPENING", get_session_phase_from_time(9, 30) == SessionPhase.OPENING)
check("16.3 9:44 -> OPENING", get_session_phase_from_time(9, 44) == SessionPhase.OPENING)
check("16.4 9:45 -> GOLDEN_MORNING", get_session_phase_from_time(9, 45) == SessionPhase.GOLDEN_MORNING)
check("16.5 10:00 -> GOLDEN_MORNING", get_session_phase_from_time(10, 0) == SessionPhase.GOLDEN_MORNING)
check("16.6 10:59 -> GOLDEN_MORNING", get_session_phase_from_time(10, 59) == SessionPhase.GOLDEN_MORNING)
check("16.7 11:00 -> LUNCH", get_session_phase_from_time(11, 0) == SessionPhase.LUNCH)
check("16.8 12:00 -> LUNCH", get_session_phase_from_time(12, 0) == SessionPhase.LUNCH)
check("16.9 12:59 -> LUNCH", get_session_phase_from_time(12, 59) == SessionPhase.LUNCH)
check("16.10 13:00 -> CLOSING", get_session_phase_from_time(13, 0) == SessionPhase.CLOSING)
check("16.11 14:00 -> CLOSING", get_session_phase_from_time(14, 0) == SessionPhase.CLOSING)
check("16.12 15:00 -> CLOSING", get_session_phase_from_time(15, 0) == SessionPhase.CLOSING)
check("16.13 15:30 -> CLOSING", get_session_phase_from_time(15, 30) == SessionPhase.CLOSING)
check("16.14 8:00 (pre-market) -> OPENING", get_session_phase_from_time(8, 0) == SessionPhase.OPENING)
check("16.15 16:00 (post-market) -> OPENING", get_session_phase_from_time(16, 0) == SessionPhase.OPENING)

# =========================================================================
# 17. get_aggression_modifier()
# =========================================================================
print("\n--- 17. get_aggression_modifier() ---")

check("17.1 OPENING modifier -0.2", get_aggression_modifier(SessionPhase.OPENING) == -0.2)
check("17.2 GOLDEN_MORNING modifier +0.1", get_aggression_modifier(SessionPhase.GOLDEN_MORNING) == 0.1)
check("17.3 LUNCH modifier -0.1", get_aggression_modifier(SessionPhase.LUNCH) == -0.1)
check("17.4 CLOSING modifier -0.2", get_aggression_modifier(SessionPhase.CLOSING) == -0.2)

# =========================================================================
# 18. get_permission_strictness()
# =========================================================================
print("\n--- 18. get_permission_strictness() ---")

check("18.1 OPENING -> HIGH", get_permission_strictness(SessionPhase.OPENING) == "HIGH")
check("18.2 GOLDEN_MORNING -> NORMAL", get_permission_strictness(SessionPhase.GOLDEN_MORNING) == "NORMAL")
check("18.3 LUNCH -> HIGH", get_permission_strictness(SessionPhase.LUNCH) == "HIGH")
check("18.4 CLOSING -> VERY_HIGH", get_permission_strictness(SessionPhase.CLOSING) == "VERY_HIGH")


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
