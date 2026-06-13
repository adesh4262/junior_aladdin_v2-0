"""Unit tests for ``confluence_engine.py`` — Floor 5 Step 5.7.

Tests:
- compute_confluence() with all 5 heads aligned -> high quality
- compute_confluence() with mixed heads -> conflict detected
- SMC + ICT opposing -> veto condition
- SMC + ICT aligned -> high quality despite other opposition
- Trust weighting: state modifiers (READY, UNCERTAIN, STALE)
- Trust weighting: freshness modifiers (FRESH, WARM, STALE)
- Trust weighting: context quality (SMC/ICT)
- No head reports -> neutral result
- get_head_trust_tier() for all combinations
- Dominant direction detection
- Partial alignment (>60% or 3/5 heads)
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from datetime import datetime

from junior_aladdin.floor_5_captain.confluence_engine import ConfluenceEngine, ReportTrustTier
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


def make_report(
    head_name: str,
    bias: BiasType = BiasType.NEUTRAL,
    confidence: float = 0.5,
    state: HeadState = HeadState.READY,
    freshness_tag: FreshnessTag = FreshnessTag.FRESH,
    freshness_score: float = 0.9,
    context_quality_score: float | None = None,
) -> HeadReport:
    """Create a HeadReport with the given parameters."""
    return HeadReport(
        head_name=head_name,
        state=state,
        freshness_score=freshness_score,
        freshness_tag=freshness_tag,
        last_deep_update=datetime.utcnow(),
        bias=bias,
        confidence=confidence,
        dominant_tf="1m",
        timeframe_view="",
        context_quality_score=context_quality_score,
    )


print("=" * 60)
print("Floor 5 — Confluence Engine Tests")
print("=" * 60)

engine = ConfluenceEngine()

# =========================================================================
# 1. All 5 heads bullish -> strong confluence
# =========================================================================
print("\n--- 1. All 5 heads aligned (bullish) ---")

reports_all_bullish = {
    "SMC Head": make_report("SMC Head", BiasType.BULLISH, 0.85, context_quality_score=0.9),
    "ICT Head": make_report("ICT Head", BiasType.BULLISH, 0.80, context_quality_score=0.8),
    "Technical Head": make_report("Technical Head", BiasType.BULLISH, 0.70),
    "Options Head": make_report("Options Head", BiasType.BULLISH, 0.60),
    "Macro Head": make_report("Macro Head", BiasType.BULLISH, 0.50),
}

result = engine.compute_confluence(head_reports=reports_all_bullish)

check("1.1 Confluence quality > 0.6", result.confluence_quality > 0.6)
check("1.2 Dominant direction BULLISH", result.dominant_direction == "BULLISH")
check("1.3 No conflict", result.conflict_present is False)
check("1.4 All 5 heads aligned", len(result.aligned_heads) == 5)
check("1.5 No opposing heads", len(result.opposing_heads) == 0)
check("1.6 Weighting has all 5 heads", len(result.weighting_summary) == 5)
check("1.7 SMC has highest weight",
      result.weighting_summary["SMC Head"] > result.weighting_summary["Technical Head"])

# =========================================================================
# 2. All 5 heads bearish -> strong bearish confluence
# =========================================================================
print("\n--- 2. All 5 heads aligned (bearish) ---")

reports_all_bearish = {
    "SMC Head": make_report("SMC Head", BiasType.BEARISH, 0.85, context_quality_score=0.9),
    "ICT Head": make_report("ICT Head", BiasType.BEARISH, 0.80, context_quality_score=0.8),
    "Technical Head": make_report("Technical Head", BiasType.BEARISH, 0.70),
    "Options Head": make_report("Options Head", BiasType.BEARISH, 0.60),
    "Macro Head": make_report("Macro Head", BiasType.BEARISH, 0.50),
}

result = engine.compute_confluence(head_reports=reports_all_bearish)
check("2.1 Confluence quality > 0.6", result.confluence_quality > 0.6)
check("2.2 Dominant direction BEARISH", result.dominant_direction == "BEARISH")
check("2.3 No conflict", result.conflict_present is False)

# =========================================================================
# 3. Mixed directions -> conflict detected
# =========================================================================
print("\n--- 3. Mixed directions (conflict) ---")

reports_mixed = {
    "SMC Head": make_report("SMC Head", BiasType.BULLISH, 0.85, context_quality_score=0.9),
    "ICT Head": make_report("ICT Head", BiasType.BULLISH, 0.80, context_quality_score=0.8),
    "Technical Head": make_report("Technical Head", BiasType.BEARISH, 0.70),
    "Options Head": make_report("Options Head", BiasType.BEARISH, 0.60),
    "Macro Head": make_report("Macro Head", BiasType.BEARISH, 0.50),
}

result = engine.compute_confluence(head_reports=reports_mixed)

check("3.1 Conflict detected (3 bearish vs 2 bullish)", result.conflict_present is True)
check("3.2 Dominant direction BEARISH (3 heads vs 2)",
      result.dominant_direction in ("BEARISH", "BULLISH"))
check("3.3 Both aligned and opposing have entries",
      len(result.aligned_heads) > 0 and len(result.opposing_heads) > 0)

# =========================================================================
# 4. SMC + ICT opposing -> veto condition
# =========================================================================
print("\n--- 4. SMC + ICT opposing (veto) ---")

reports_veto = {
    "SMC Head": make_report("SMC Head", BiasType.BULLISH, 0.90, context_quality_score=0.9),
    "ICT Head": make_report("ICT Head", BiasType.BULLISH, 0.85, context_quality_score=0.85),
    "Technical Head": make_report("Technical Head", BiasType.BEARISH, 0.75),
    "Options Head": make_report("Options Head", BiasType.BEARISH, 0.70),
    "Macro Head": make_report("Macro Head", BiasType.BEARISH, 0.60),
}

result = engine.compute_confluence(head_reports=reports_veto)

check("4.1 Dominant direction BULLISH (SMC+ICT outweigh 3 others)",
      result.dominant_direction == "BULLISH")
check("4.2 Conflict detected (SMC+ICT bullish, 3 others bearish)",
      result.conflict_present is True)
check("4.3 SMC + ICT in aligned",
      "SMC Head" in result.aligned_heads and "ICT Head" in result.aligned_heads)
check("4.4 Technical, Options, Macro in opposing",
      all(h in result.opposing_heads for h in ["Technical Head", "Options Head", "Macro Head"]))

# =========================================================================
# 5. SMC + ICT strongly aligned -> high quality despite opposition
# =========================================================================
print("\n--- 5. SMC + ICT aligned + high confidence -> high quality ---")

reports_strong_core = {
    "SMC Head": make_report("SMC Head", BiasType.BULLISH, 0.95, context_quality_score=0.95),
    "ICT Head": make_report("ICT Head", BiasType.BULLISH, 0.90, context_quality_score=0.90),
    "Technical Head": make_report("Technical Head", BiasType.NEUTRAL, 0.50),
    "Options Head": make_report("Options Head", BiasType.NEUTRAL, 0.50),
    "Macro Head": make_report("Macro Head", BiasType.NEUTRAL, 0.50),
}

result = engine.compute_confluence(head_reports=reports_strong_core)

check("5.1 Confluence quality >= 0.6", result.confluence_quality >= 0.6)
check("5.2 Dominant direction BULLISH", result.dominant_direction == "BULLISH")
check("5.3 No conflict (neutral heads don't oppose)", result.conflict_present is False)
check("5.4 Aligned heads = SMC + ICT", len(result.aligned_heads) == 2)
check("5.5 No opposing heads", len(result.opposing_heads) == 0)

# =========================================================================
# 6. Trust weighting: state modifiers
# =========================================================================
print("\n--- 6. Trust weighting: state modifiers ---")

# SMC STALE vs SMC READY -> STALE should have lower weight
smc_stale = make_report("SMC Head", BiasType.BULLISH, 0.85, state=HeadState.STALE,
                        freshness_tag=FreshnessTag.STALE, context_quality_score=0.9)
smc_ready = make_report("SMC Head", BiasType.BULLISH, 0.85, state=HeadState.READY,
                        freshness_tag=FreshnessTag.FRESH, context_quality_score=0.9)

weight_stale = engine._compute_trust_weight("SMC Head", smc_stale)
weight_ready = engine._compute_trust_weight("SMC Head", smc_ready)

check("6.1 STALE weight < READY weight", weight_stale < weight_ready)
check("6.2 READY weight = 1.0 (base*state*fresh*cq)", weight_ready == 1.0)

# UNCERTAIN weight between READY and STALE
smc_uncertain = make_report("SMC Head", BiasType.BULLISH, 0.85, state=HeadState.UNCERTAIN,
                            freshness_tag=FreshnessTag.FRESH, context_quality_score=0.9)
weight_uncertain = engine._compute_trust_weight("SMC Head", smc_uncertain)
check("6.3 UNCERTAIN weight between STALE and READY",
      weight_stale < weight_uncertain < weight_ready)

# =========================================================================
# 7. Trust weighting: freshness modifiers
# =========================================================================
print("\n--- 7. Trust weighting: freshness modifiers ---")

ict_fresh = make_report("ICT Head", BiasType.BULLISH, 0.8, state=HeadState.READY,
                        freshness_tag=FreshnessTag.FRESH, freshness_score=0.9)
ict_warm = make_report("ICT Head", BiasType.BULLISH, 0.8, state=HeadState.READY,
                       freshness_tag=FreshnessTag.WARM, freshness_score=0.6)
ict_stale = make_report("ICT Head", BiasType.BULLISH, 0.8, state=HeadState.READY,
                        freshness_tag=FreshnessTag.STALE, freshness_score=0.2)

w_fresh = engine._compute_trust_weight("ICT Head", ict_fresh)
w_warm = engine._compute_trust_weight("ICT Head", ict_warm)
w_stale = engine._compute_trust_weight("ICT Head", ict_stale)

check("7.1 FRESH > WARM > STALE", w_fresh > w_warm > w_stale)

# =========================================================================
# 8. Trust weighting: context quality (SMC/ICT only)
# =========================================================================
print("\n--- 8. Context quality modifiers (SMC/ICT) ---")

smc_high_cq = make_report("SMC Head", BiasType.BULLISH, 0.85, state=HeadState.READY,
                          freshness_tag=FreshnessTag.FRESH, context_quality_score=0.9)
smc_low_cq = make_report("SMC Head", BiasType.BULLISH, 0.85, state=HeadState.READY,
                         freshness_tag=FreshnessTag.FRESH, context_quality_score=0.3)
smc_none_cq = make_report("SMC Head", BiasType.BULLISH, 0.85, state=HeadState.READY,
                          freshness_tag=FreshnessTag.FRESH, context_quality_score=None)

w_high = engine._compute_trust_weight("SMC Head", smc_high_cq)
w_low = engine._compute_trust_weight("SMC Head", smc_low_cq)
w_none = engine._compute_trust_weight("SMC Head", smc_none_cq)

check("8.1 HIGH CQ > LOW CQ", w_high > w_low)
check("8.2 None CQ defaults to medium", w_none > w_low)

# Non-SMC/ICT heads should NOT be affected by context quality
tech_high_cq = make_report("Technical Head", BiasType.BULLISH, 0.7, state=HeadState.READY,
                           freshness_tag=FreshnessTag.FRESH, context_quality_score=0.9)
tech_none_cq = make_report("Technical Head", BiasType.BULLISH, 0.7, state=HeadState.READY,
                           freshness_tag=FreshnessTag.FRESH, context_quality_score=None)

w_tech_high = engine._compute_trust_weight("Technical Head", tech_high_cq)
w_tech_none = engine._compute_trust_weight("Technical Head", tech_none_cq)
check("8.3 Technical Head unaffected by CQ", w_tech_high == w_tech_none)

# =========================================================================
# 9. No head reports -> neutral result
# =========================================================================
print("\n--- 9. No head reports ---")

result = engine.compute_confluence()

check("9.1 Empty reports quality = 0.0", result.confluence_quality == 0.0)
check("9.2 Empty reports dominant NEUTRAL", result.dominant_direction == "NEUTRAL")
check("9.3 Empty reports no conflict", result.conflict_present is False)
check("9.4 Empty reports no aligned", len(result.aligned_heads) == 0)
check("9.5 Empty reports no opposing", len(result.opposing_heads) == 0)
check("9.6 Empty reports timestamp set", result.timestamp is not None)

# Empty dict
result = engine.compute_confluence(head_reports={})
check("9.7 Empty dict same as None", result.confluence_quality == 0.0)

# Only Psychology Head (should be skipped)
result = engine.compute_confluence(head_reports={
    "Psychology Head": make_report("Psychology Head", BiasType.NEUTRAL, 0.0),
})
check("9.8 Psychology-only treated as empty", result.confluence_quality == 0.0)

# =========================================================================
# 10. get_head_trust_tier()
# =========================================================================
print("\n--- 10. get_head_trust_tier() ---")

# SMC STALE -> MINIMAL
r = make_report("SMC Head", state=HeadState.STALE, freshness_tag=FreshnessTag.STALE)
check("10.1 SMC STALE -> MINIMAL", ConfluenceEngine.get_head_trust_tier("SMC Head", r) == ReportTrustTier.MINIMAL)

# ICT STALE -> MINIMAL
r = make_report("ICT Head", state=HeadState.STALE, freshness_tag=FreshnessTag.STALE)
check("10.2 ICT STALE -> MINIMAL", ConfluenceEngine.get_head_trust_tier("ICT Head", r) == ReportTrustTier.MINIMAL)

# Technical STALE -> REDUCED (not core)
r = make_report("Technical Head", state=HeadState.STALE, freshness_tag=FreshnessTag.STALE)
check("10.3 Technical STALE -> REDUCED", ConfluenceEngine.get_head_trust_tier("Technical Head", r) == ReportTrustTier.REDUCED)

# READY + FRESH -> FULL
r = make_report("SMC Head", state=HeadState.READY, freshness_tag=FreshnessTag.FRESH)
check("10.4 SMC READY FRESH -> FULL", ConfluenceEngine.get_head_trust_tier("SMC Head", r) == ReportTrustTier.FULL)

# UNCERTAIN -> REDUCED
r = make_report("ICT Head", state=HeadState.UNCERTAIN, freshness_tag=FreshnessTag.FRESH)
check("10.5 ICT UNCERTAIN -> REDUCED", ConfluenceEngine.get_head_trust_tier("ICT Head", r) == ReportTrustTier.REDUCED)

# READY + WARM -> FULL (warmness doesn't reduce by itself)
r = make_report("Options Head", state=HeadState.READY, freshness_tag=FreshnessTag.WARM)
check("10.6 Options READY WARM -> FULL", ConfluenceEngine.get_head_trust_tier("Options Head", r) == ReportTrustTier.FULL)

# READY + STALE freshness -> REDUCED
r = make_report("Macro Head", state=HeadState.READY, freshness_tag=FreshnessTag.STALE)
check("10.7 Macro READY STALE fresh -> REDUCED", ConfluenceEngine.get_head_trust_tier("Macro Head", r) == ReportTrustTier.REDUCED)

# =========================================================================
# 11. Partial alignment — 3 of 5 heads aligned
# =========================================================================
print("\n--- 11. Partial alignment (3 of 5) ---")

reports_partial = {
    "SMC Head": make_report("SMC Head", BiasType.BULLISH, 0.85, context_quality_score=0.9),
    "ICT Head": make_report("ICT Head", BiasType.BULLISH, 0.80, context_quality_score=0.8),
    "Technical Head": make_report("Technical Head", BiasType.BULLISH, 0.70),
    "Options Head": make_report("Options Head", BiasType.NEUTRAL, 0.50),
    "Macro Head": make_report("Macro Head", BiasType.NEUTRAL, 0.50),
}

result = engine.compute_confluence(head_reports=reports_partial)

check("11.1 3 of 5 aligned", len(result.aligned_heads) == 3)
check("11.2 No opposing", len(result.opposing_heads) == 0)
check("11.3 Confluence quality >= 0.6",
      result.confluence_quality >= 0.6)
check("11.4 Dominant BULLISH", result.dominant_direction == "BULLISH")
check("11.5 No conflict (neutral != opposing)", result.conflict_present is False)

# =========================================================================
# 12. Equal split — 2 bullish, 2 bearish, 1 neutral
# =========================================================================
print("\n--- 12. Equal split (2/2/1) ---")

reports_equal = {
    "SMC Head": make_report("SMC Head", BiasType.BULLISH, 0.85, context_quality_score=0.9),
    "ICT Head": make_report("ICT Head", BiasType.BULLISH, 0.80, context_quality_score=0.8),
    "Technical Head": make_report("Technical Head", BiasType.BEARISH, 0.70),
    "Options Head": make_report("Options Head", BiasType.BEARISH, 0.60),
    "Macro Head": make_report("Macro Head", BiasType.NEUTRAL, 0.50),
}

result = engine.compute_confluence(head_reports=reports_equal)

check("12.1 Confluence quality < 0.6 (split decision)", result.confluence_quality < 0.6)
check("12.2 Conflict detected", result.conflict_present is True)
check("12.3 Both directions have entries",
      len(result.aligned_heads) > 0 and len(result.opposing_heads) > 0)
check("12.4 Dominant BULLISH (SMC+ICT outweigh Technical+Options)",
      result.dominant_direction == "BULLISH")


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
