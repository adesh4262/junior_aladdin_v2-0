"""Unit tests for ``head_report_schema.py`` — Floor 4 Step 4.2.

Tests the 7 contract validation rules enforced by ``ReportValidator``:

1. Invalidation mandatory (never None/empty)
2. SMC/ICT -> context_quality_score mandatory
3. Macro/Psychology -> primary_setup must be None
4. Macro/Psychology -> backup_setup must be None
5. State must be valid HeadState
6. Freshness_score must be 0.0–1.0
7. Confidence must be 0.0–1.0

Also tests:
- Unknown head_name rejection
- validate_report_contract() convenience wrapper
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from datetime import datetime
from junior_aladdin.shared.types import (
    BiasType,
    FreshnessTag,
    HeadReport,
    HeadState,
)
from junior_aladdin.floor_4_heads.head_report_schema import (
    HEAD_SMC,
    HEAD_ICT,
    HEAD_TECHNICAL,
    HEAD_OPTIONS,
    HEAD_MACRO,
    HEAD_PSYCHOLOGY,
    ReportValidationResult,
    ReportValidator,
    validate_report_contract,
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
    head_name: str = HEAD_SMC,
    state: HeadState = HeadState.READY,
    freshness_score: float = 0.9,
    freshness_tag: FreshnessTag = FreshnessTag.FRESH,
    bias: BiasType = BiasType.BULLISH,
    confidence: float = 0.75,
    primary_setup: str | None = "FVG Retest",
    backup_setup: str | None = "Order Block Bounce",
    invalidation: dict | None = None,
    context_quality_score: float | None = 0.7,
) -> HeadReport:
    """Helper to build a HeadReport with sensible defaults."""
    if invalidation is None:
        invalidation = {
            "rules": [
                {
                    "condition": "Structure breaks below support",
                    "price_level": 19500.0,
                    "reason": "Bullish structure invalidated",
                }
            ],
            "summary": "Structure breaks below support",
        }
    return HeadReport(
        head_name=head_name,
        state=state,
        freshness_score=freshness_score,
        freshness_tag=freshness_tag,
        last_deep_update=datetime.utcnow(),
        bias=bias,
        confidence=confidence,
        dominant_tf="1m",
        timeframe_view="Test view",
        primary_setup=primary_setup,
        backup_setup=backup_setup,
        active_zones=[
            {"zone_type": "FVG", "price_level": 19600.0, "direction": "bullish"},
        ],
        armed_triggers=[
            {"trigger_type": "zone_touch", "condition": "Price retests FVG at 19600"},
        ],
        invalidation=invalidation,
        bull_case="Bullish case",
        bear_case="Bearish case",
        confluence_note="Test confluence",
        witness_summary="Test witness",
        context_quality_score=context_quality_score,
    )


# =========================================================================
# Tests
# =========================================================================

print("=" * 60)
print("Floor 4 — Head Report Schema Tests")
print("=" * 60)

validator = ReportValidator()

# ── 1. Valid reports pass ──────────────────────────────────────────────
print("\n--- 1. Valid reports ---")

# 1.1 SMC Head with all fields
r = validator.validate(make_report(head_name=HEAD_SMC))
check("1.1 SMC valid report passes", r.valid)

# 1.2 ICT Head with all fields
r = validator.validate(make_report(head_name=HEAD_ICT))
check("1.2 ICT valid report passes", r.valid)

# 1.3 Technical Head (no context_quality_score needed)
r = validator.validate(make_report(
    head_name=HEAD_TECHNICAL, context_quality_score=None,
))
check("1.3 Technical Head valid (no context_quality_score needed)", r.valid)

# 1.4 Options Head (no context_quality_score needed)
r = validator.validate(make_report(
    head_name=HEAD_OPTIONS, context_quality_score=None,
))
check("1.4 Options Head valid", r.valid)

# ── 2. Invalidation tests ──────────────────────────────────────────────
print("\n--- 2. Invalidation mandatory ---")

# 2.1 Empty invalidation dict
r = validator.validate(make_report(invalidation={}))
check("2.1 Empty invalidation -> HALT", not r.valid)
check("2.1 reason mentions 'invalidation'", any("invalidation" in reason.lower() for reason in r.reasons))

# 2.2 Invalidation with no rules key
r = validator.validate(make_report(invalidation={"summary": "no rules"}))
check("2.2 Invalidation without rules -> HALT", not r.valid)

# 2.3 Invalidation with empty rules list
r = validator.validate(make_report(invalidation={"rules": []}))
check("2.3 Empty rules list -> HALT", not r.valid)

# ── 3. SMC/ICT context_quality_score mandatory ─────────────────────────
print("\n--- 3. SMC/ICT context_quality_score mandatory ---")

# 3.1 SMC missing context_quality_score
r = validator.validate(make_report(head_name=HEAD_SMC, context_quality_score=None))
check("3.1 SMC missing context_quality_score -> HALT", not r.valid)

# 3.2 ICT missing context_quality_score
r = validator.validate(make_report(head_name=HEAD_ICT, context_quality_score=None))
check("3.2 ICT missing context_quality_score -> HALT", not r.valid)

# 3.3 SMC context_quality_score out of range
r = validator.validate(make_report(head_name=HEAD_SMC, context_quality_score=1.5))
check("3.3 SMC context_quality_score > 1.0 -> HALT", not r.valid)

# 3.4 SMC context_quality_score negative
r = validator.validate(make_report(head_name=HEAD_SMC, context_quality_score=-0.1))
check("3.4 SMC context_quality_score < 0.0 -> HALT", not r.valid)

# ── 4. Macro NO primary_setup ──────────────────────────────────────────
print("\n--- 4. Macro/Psychology: NO primary_setup ---")

# 4.1 Macro with primary_setup -> HALT
r = validator.validate(make_report(
    head_name=HEAD_MACRO, primary_setup="Some Setup",
    context_quality_score=None,
))
check("4.1 Macro with primary_setup -> HALT", not r.valid)

# 4.2 Macro with None primary_setup -> passes
r = validator.validate(make_report(
    head_name=HEAD_MACRO, primary_setup=None, backup_setup=None,
    context_quality_score=None,
    invalidation={"rules": [{"condition": "Event passed", "price_level": 0, "reason": "Gate closed"}]},
))
check("4.2 Macro with no setups -> passes", r.valid)

# 4.3 Psychology with primary_setup -> HALT
r = validator.validate(make_report(
    head_name=HEAD_PSYCHOLOGY, primary_setup="Some Setup",
    context_quality_score=None,
))
check("4.3 Psychology with primary_setup -> HALT", not r.valid)

# 4.4 Psychology with None primary_setup -> passes
r = validator.validate(make_report(
    head_name=HEAD_PSYCHOLOGY, primary_setup=None, backup_setup=None,
    context_quality_score=None,
    invalidation={"rules": [{"condition": "Cooldown completed", "price_level": 0, "reason": "Brake lifted"}]},
))
check("4.4 Psychology with no setups -> passes", r.valid)

# ── 5. Macro/Psychology NO backup_setup ────────────────────────────────
print("\n--- 5. Macro/Psychology: NO backup_setup ---")

# 5.1 Macro with backup_setup -> HALT
r = validator.validate(make_report(
    head_name=HEAD_MACRO, primary_setup=None, backup_setup="Backup Plan",
    context_quality_score=None,
    invalidation={"rules": [{"condition": "Event risk cleared", "price_level": 0, "reason": "Gate closed"}]},
))
check("5.1 Macro with backup_setup -> HALT", not r.valid)

# 5.2 Psychology with backup_setup -> HALT
r = validator.validate(make_report(
    head_name=HEAD_PSYCHOLOGY, primary_setup=None, backup_setup="Backup Plan",
    context_quality_score=None,
    invalidation={"rules": [{"condition": "Cooldown completed", "price_level": 0, "reason": "Brake lifted"}]},
))
check("5.2 Psychology with backup_setup -> HALT", not r.valid)

# ── 6. Unknown head_name ───────────────────────────────────────────────
print("\n--- 6. Unknown head_name ---")

r = validator.validate(make_report(head_name="Unknown Head", context_quality_score=None, invalidation={"rules": [{"condition": "Test", "price_level": 0, "reason": "Test"}]}))
check("6.1 Unknown head_name -> HALT", not r.valid)
check("6.1 reason mentions 'unknown'", any("unknown" in reason.lower() for reason in r.reasons))

# ── 7. Invalid state ──────────────────────────────────────────────────
print("\n--- 7. State validation ---")

# 7.1 Invalid state string
r = validator.validate(make_report(state="INVALID_STATE"))  # type: ignore
check("7.1 Invalid state string -> HALT", not r.valid)

# ── 8. Freshness/confidence bounds ────────────────────────────────────
print("\n--- 8. Freshness & confidence bounds ---")

# 8.1 Negative freshness
r = validator.validate(make_report(freshness_score=-0.5))
check("8.1 Negative freshness_score -> HALT", not r.valid)

# 8.2 Over-range freshness
r = validator.validate(make_report(freshness_score=1.5))
check("8.2 freshness_score > 1.0 -> HALT", not r.valid)

# 8.3 Negative confidence
r = validator.validate(make_report(confidence=-0.1))
check("8.3 Negative confidence -> HALT", not r.valid)

# 8.4 Over-range confidence
r = validator.validate(make_report(confidence=1.5))
check("8.4 confidence > 1.0 -> HALT", not r.valid)

# ── 9. validate_report_contract() convenience ─────────────────────────
print("\n--- 9. Convenience function ---")

# 9.1 Valid report
r = validate_report_contract(make_report(head_name=HEAD_SMC))
check("9.1 validate_report_contract() with valid report passes", r.valid)

# 9.2 Invalid report (missing invalidation)
r = validate_report_contract(make_report(invalidation={}))
check("9.2 validate_report_contract() with invalid report -> HALT", not r.valid)

# ── 10. Multiple violations at once ────────────────────────────────────
print("\n--- 10. Multiple violations ---")

# 10.1 SMC with missing context_quality_score AND missing invalidation
r = validator.validate(make_report(
    head_name=HEAD_SMC,
    context_quality_score=None,
    invalidation={},
))
check("10.1 Multiple violations -> not valid", not r.valid)
check("10.1 context_quality_score in errors",
      r.field_errors.get("context_quality_score") is not None)
check("10.1 invalidation in errors",
      r.field_errors.get("invalidation") is not None)

# ── 11. ReportValidationResult API ─────────────────────────────────────
print("\n--- 11. ReportValidationResult API ---")

result = ReportValidationResult()
check("11.1 Default valid=True", result.valid)
check("11.2 Default empty reasons", len(result.reasons) == 0)

result.fail("Something wrong", field="test")
check("11.3 fail() sets valid=False", not result.valid)
check("11.4 fail() adds reason", "Something wrong" in result.reasons)
check("11.5 fail() adds field error", result.field_errors.get("test") == "Something wrong")

# =========================================================================
# Summary
# =========================================================================
print(f"\n{'=' * 60}")
print(f"Results: {passed} passed, {failed} failed")
print(f"{'=' * 60}")

if failed > 0:
    sys.exit(1)
else:
    sys.exit(0)
