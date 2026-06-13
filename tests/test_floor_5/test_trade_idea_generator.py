"""Unit tests for ``trade_idea_generator.py`` — Floor 5 Step 5.10.

Tests:
- TradeIdea dataclass instantiation
- generate_idea() with BULLISH confluence -> BUY direction
- generate_idea() with BEARISH confluence -> SELL direction
- generate_idea() with NEUTRAL/no confluence -> empty idea
- Trade class suggestion from regime (TREND_UP -> CONTINUATION)
- Trade class suggestion from session override (CLOSING -> SCALP)
- Trade class with low quality + SCALP available -> SCALP
- Supporting/opposing heads extracted correctly
- Setup source identification (SMC priority)
- Psychology caution in opposing heads
- get_idea_summary() dict
- None inputs -> empty idea
- Reasoning text includes key context
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from datetime import datetime

from junior_aladdin.floor_5_captain.trade_idea_generator import (
    TradeIdea,
    TradeIdeaGenerator,
)
from junior_aladdin.floor_5_captain.captain_types import (
    ConfluenceResult,
    ConvictionBand,
    ConvictionScore,
    MarketStory,
    SessionPhase,
    get_aggression_modifier,
)
from junior_aladdin.shared.types import (
    BiasType,
    FreshnessTag,
    HeadReport,
    HeadState,
    TradeClass,
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


_GOLDEN_TIMESTAMP = datetime(2025, 6, 10, 4, 30, 0)


def make_confluence(
    direction: str = "BULLISH",
    quality: float = 0.8,
    conflict: bool = False,
    aligned: list[str] | None = None,
    opposing: list[str] | None = None,
) -> ConfluenceResult:
    return ConfluenceResult(
        confluence_quality=quality,
        conflict_present=conflict,
        aligned_heads=aligned if aligned is not None else ["SMC Head", "ICT Head", "Technical Head"],
        opposing_heads=opposing if opposing is not None else [],
        dominant_direction=direction,
        timestamp=_GOLDEN_TIMESTAMP,
    )


def make_story(
    regime: str = "TREND_UP",
    bias: str = "BULLISH",
    session: SessionPhase = SessionPhase.GOLDEN_MORNING,
) -> MarketStory:
    return MarketStory(
        regime=regime,
        session_phase=session,
        bias=bias,
        timestamp=_GOLDEN_TIMESTAMP,
    )


def make_conviction(
    permission: float = 80,
    conviction: float = 75,
    no_trade: float = 10,
    band: ConvictionBand = ConvictionBand.STRONG,
) -> ConvictionScore:
    return ConvictionScore(
        permission_score=permission,
        conviction_score=conviction,
        no_trade_score=no_trade,
        conviction_band=band,
        timestamp=_GOLDEN_TIMESTAMP,
    )


def make_psych_report(
    trade_allowed: bool = True,
    caution_level: float = 0.0,
    trap_pressure: bool = False,
) -> HeadReport:
    return HeadReport(
        head_name="Psychology Head",
        state=HeadState.READY,
        freshness_score=0.9,
        freshness_tag=FreshnessTag.FRESH,
        last_deep_update=_GOLDEN_TIMESTAMP,
        bias=BiasType.NEUTRAL,
        confidence=0.0,
        dominant_tf="1m",
        timeframe_view="",
        trade_allowed=trade_allowed,
        caution_level=caution_level,
        trap_pressure=trap_pressure,
    )


print("=" * 60)
print("Floor 5 — Trade Idea Generator Tests")
print("=" * 60)

generator = TradeIdeaGenerator()

# =========================================================================
# 1. TradeIdea dataclass creation
# =========================================================================
print("\n--- 1. TradeIdea dataclass ---")

idea = TradeIdea(direction="BUY", reasoning="Test idea")
check("1.1 Direction set", idea.direction == "BUY")
check("1.2 Reasoning set", idea.reasoning == "Test idea")
check("1.3 Default band REJECT", idea.conviction_band == ConvictionBand.REJECT)
check("1.4 Default phase OPENING", idea.session_phase == SessionPhase.OPENING)
check("1.5 Default timestamp not None", idea.timestamp is not None)

# =========================================================================
# 2. BULLISH confluence -> BUY
# =========================================================================
print("\n--- 2. BULLISH confluence -> BUY ---")

idea = generator.generate_idea(
    confluence_result=make_confluence(direction="BULLISH"),
    market_story=make_story(),
    conviction_score=make_conviction(),
    timestamp=_GOLDEN_TIMESTAMP,
)

check("2.1 Direction is BUY", idea.direction == "BUY")
check("2.2 Trade class suggested", idea.trade_class_suggestion is not None)
check("2.3 Reasoning non-empty", bool(idea.reasoning))
check("2.4 Supporting heads present", len(idea.supporting_heads) > 0)
check("2.5 Conviction band carried over", idea.conviction_band == ConvictionBand.STRONG)
check("2.6 Session phase carried over", idea.session_phase == SessionPhase.GOLDEN_MORNING)

# =========================================================================
# 3. BEARISH confluence -> SELL
# =========================================================================
print("\n--- 3. BEARISH confluence -> SELL ---")

idea = generator.generate_idea(
    confluence_result=make_confluence(direction="BEARISH"),
    market_story=make_story(regime="TREND_DOWN", bias="BEARISH"),
    conviction_score=make_conviction(),
    timestamp=_GOLDEN_TIMESTAMP,
)

check("3.1 Direction is SELL", idea.direction == "SELL")
check("3.2 Trade class suggested for TREND_DOWN",
      idea.trade_class_suggestion in (TradeClass.CONTINUATION, TradeClass.SCALP))

# =========================================================================
# 4. NEUTRAL confluence -> empty idea
# =========================================================================
print("\n--- 4. NEUTRAL confluence -> empty idea ---")

idea = generator.generate_idea(
    confluence_result=make_confluence(direction="NEUTRAL"),
    market_story=make_story(),
    conviction_score=make_conviction(),
    timestamp=_GOLDEN_TIMESTAMP,
)

check("4.1 Direction empty when NEUTRAL", idea.direction == "")
check("4.2 No trade class", idea.trade_class_suggestion is None)
check("4.3 Reasoning includes 'No trade idea'", "No trade idea" in idea.reasoning)
check("4.4 Has_idea false via summary",
      generator.get_idea_summary(idea).get("has_idea") is False)

# =========================================================================
# 5. None confluence -> empty idea
# =========================================================================
print("\n--- 5. None confluence -> empty idea ---")

idea = generator.generate_idea(
    confluence_result=None,
    market_story=make_story(),
    conviction_score=make_conviction(),
    timestamp=_GOLDEN_TIMESTAMP,
)

check("5.1 Direction empty", idea.direction == "")
check("5.2 Reasoning includes 'No confluence data'", "No confluence data" in idea.reasoning)

# =========================================================================
# 6. Trade class from regime
# =========================================================================
print("\n--- 6. Trade class by regime ---")

# TREND_UP -> CONTINUATION
idea = generator.generate_idea(
    confluence_result=make_confluence(direction="BULLISH"),
    market_story=make_story(regime="TREND_UP"),
    conviction_score=make_conviction(),
    timestamp=_GOLDEN_TIMESTAMP,
)
check("6.1 TREND_UP -> CONTINUATION",
      idea.trade_class_suggestion == TradeClass.CONTINUATION)

# CHOP -> SCALP
idea = generator.generate_idea(
    confluence_result=make_confluence(direction="BULLISH", quality=0.5),
    market_story=make_story(regime="CHOP"),
    conviction_score=make_conviction(),
    timestamp=_GOLDEN_TIMESTAMP,
)
check("6.2 CHOP -> SCALP", idea.trade_class_suggestion == TradeClass.SCALP)

# RANGE -> OPTIONS_PRESSURE
idea = generator.generate_idea(
    confluence_result=make_confluence(direction="BULLISH"),
    market_story=make_story(regime="RANGE"),
    conviction_score=make_conviction(),
    timestamp=_GOLDEN_TIMESTAMP,
)
check("6.3 RANGE -> OPTIONS_PRESSURE",
      idea.trade_class_suggestion == TradeClass.OPTIONS_PRESSURE)

# =========================================================================
# 7. Session override for trade class
# =========================================================================
print("\n--- 7. Session override ---")

# CLOSING -> SCALP
idea = generator.generate_idea(
    confluence_result=make_confluence(direction="BULLISH"),
    market_story=make_story(regime="TREND_UP", session=SessionPhase.CLOSING),
    conviction_score=make_conviction(),
    timestamp=_GOLDEN_TIMESTAMP,
)
check("7.1 CLOSING overrides to SCALP", idea.trade_class_suggestion == TradeClass.SCALP)

# OPENING -> LIQUIDITY_RECLAIM
idea = generator.generate_idea(
    confluence_result=make_confluence(direction="BULLISH"),
    market_story=make_story(regime="TREND_UP", session=SessionPhase.OPENING),
    conviction_score=make_conviction(),
    timestamp=_GOLDEN_TIMESTAMP,
)
check("7.2 OPENING -> LIQUIDITY_RECLAIM",
      idea.trade_class_suggestion == TradeClass.LIQUIDITY_RECLAIM)

# LUNCH -> REVERSAL
idea = generator.generate_idea(
    confluence_result=make_confluence(direction="BULLISH"),
    market_story=make_story(regime="TREND_UP", session=SessionPhase.LUNCH),
    conviction_score=make_conviction(),
    timestamp=_GOLDEN_TIMESTAMP,
)
check("7.3 LUNCH -> REVERSAL", idea.trade_class_suggestion == TradeClass.REVERSAL)

# GOLDEN_MORNING uses regime default
idea = generator.generate_idea(
    confluence_result=make_confluence(direction="BULLISH"),
    market_story=make_story(regime="TREND_UP", session=SessionPhase.GOLDEN_MORNING),
    conviction_score=make_conviction(),
    timestamp=_GOLDEN_TIMESTAMP,
)
check("7.4 GOLDEN_MORNING uses regime default (CONTINUATION)",
      idea.trade_class_suggestion == TradeClass.CONTINUATION)

# =========================================================================
# 8. Low confluence quality -> safer trade class
# =========================================================================
print("\n--- 8. Low quality safety ---")

# Low quality (0.3) with SCALP available in TREND_UP -> SCALP
idea = generator.generate_idea(
    confluence_result=make_confluence(direction="BULLISH", quality=0.3),
    market_story=make_story(regime="TREND_UP"),
    conviction_score=make_conviction(),
    timestamp=_GOLDEN_TIMESTAMP,
)
check("8.1 Low quality + SCALP available -> SCALP",
      idea.trade_class_suggestion == TradeClass.SCALP)

# =========================================================================
# 9. Supporting and opposing heads
# =========================================================================
print("\n--- 9. Supporting and opposing heads ---")

idea = generator.generate_idea(
    confluence_result=make_confluence(
        direction="BULLISH",
        aligned=["SMC Head", "ICT Head"],
        opposing=["Options Head", "Macro Head"],
    ),
    market_story=make_story(),
    conviction_score=make_conviction(),
    timestamp=_GOLDEN_TIMESTAMP,
)

check("9.1 Supporting heads extracted", "SMC Head" in idea.supporting_heads)
check("9.2 Opposing heads extracted", "Options Head" in idea.opposing_heads)
check("9.3 Both heads in supporting", "ICT Head" in idea.supporting_heads)
check("9.4 Reasoning includes supporting",
      "SMC Head" in idea.reasoning and "ICT Head" in idea.reasoning)

# =========================================================================
# 10. Setup source identification
# =========================================================================
print("\n--- 10. Setup source ---")

# SMC is highest priority
idea = generator.generate_idea(
    confluence_result=make_confluence(
        direction="BULLISH",
        aligned=["Technical Head", "SMC Head", "Options Head"],
    ),
    market_story=make_story(),
    conviction_score=make_conviction(),
    timestamp=_GOLDEN_TIMESTAMP,
)
check("10.1 SMC Head is primary setup source", idea.setup_source == "SMC Head")

# Only Macro and Options
idea = generator.generate_idea(
    confluence_result=make_confluence(
        direction="BULLISH",
        aligned=["Options Head", "Macro Head"],
    ),
    market_story=make_story(),
    conviction_score=make_conviction(),
    timestamp=_GOLDEN_TIMESTAMP,
)
check("10.2 Options/Macro -> first aligned is setup source",
      idea.setup_source in ("Options Head", "Macro Head"))

# No heads
idea = generator.generate_idea(
    confluence_result=make_confluence(
        direction="BULLISH",
        aligned=[],
    ),
    market_story=make_story(),
    conviction_score=make_conviction(),
    timestamp=_GOLDEN_TIMESTAMP,
)
check("10.3 Empty setup source when no heads", idea.setup_source == "")

# =========================================================================
# 11. Psychology caution in opposing heads
# =========================================================================
print("\n--- 11. Psychology caution ---")

# Psychology blocks
idea = generator.generate_idea(
    confluence_result=make_confluence(direction="BULLISH"),
    market_story=make_story(),
    conviction_score=make_conviction(),
    psychology_report=make_psych_report(trade_allowed=False),
    timestamp=_GOLDEN_TIMESTAMP,
)
psych_opposing = [h for h in idea.opposing_heads if "Psychology" in h]
check("11.1 Psychology block appears in opposing", len(psych_opposing) > 0)
check("11.2 'blocked' in psychology opposing text",
      any("blocked" in h.lower() for h in psych_opposing))

# Psychology high caution
idea = generator.generate_idea(
    confluence_result=make_confluence(direction="BULLISH"),
    market_story=make_story(),
    conviction_score=make_conviction(),
    psychology_report=make_psych_report(caution_level=0.8),
    timestamp=_GOLDEN_TIMESTAMP,
)
psych_opposing = [h for h in idea.opposing_heads if "Psychology" in h]
check("11.3 High caution appears in opposing", len(psych_opposing) > 0)

# Psychology trap pressure
idea = generator.generate_idea(
    confluence_result=make_confluence(direction="BULLISH"),
    market_story=make_story(),
    conviction_score=make_conviction(),
    psychology_report=make_psych_report(trap_pressure=True),
    timestamp=_GOLDEN_TIMESTAMP,
)
psych_opposing = [h for h in idea.opposing_heads if "Psychology" in h]
check("11.4 Trap pressure appears in opposing", len(psych_opposing) > 0)

# No psychology concern -> no opposing from psychology
idea = generator.generate_idea(
    confluence_result=make_confluence(direction="BULLISH"),
    market_story=make_story(),
    conviction_score=make_conviction(),
    psychology_report=make_psych_report(),
    timestamp=_GOLDEN_TIMESTAMP,
)
psych_opposing = [h for h in idea.opposing_heads if "Psychology" in h]
check("11.5 No psychology concern -> no psychology in opposing",
      len(psych_opposing) == 0)

# =========================================================================
# 12. get_idea_summary()
# =========================================================================
print("\n--- 12. get_idea_summary() ---")

idea = generator.generate_idea(
    confluence_result=make_confluence(direction="BULLISH"),
    market_story=make_story(),
    conviction_score=make_conviction(),
    timestamp=_GOLDEN_TIMESTAMP,
)
summary = generator.get_idea_summary(idea)

check("12.1 Summary has direction", summary.get("direction") == "BUY")
check("12.2 Summary has trade_class", summary.get("trade_class") == "CONTINUATION")
check("12.3 Summary has reasoning", bool(summary.get("reasoning")))
check("12.4 Summary has supporting_heads", len(summary.get("supporting_heads", [])) > 0)
check("12.5 Summary has has_idea", summary.get("has_idea") is True)
check("12.6 Summary has conviction_band", summary.get("conviction_band") == "STRONG")
check("12.7 Summary has session_phase", summary.get("session_phase") == "GOLDEN_MORNING")
check("12.8 Summary has aggression_modifier",
      summary.get("aggression_modifier") == get_aggression_modifier(SessionPhase.GOLDEN_MORNING))
check("12.9 Summary has timestamp", bool(summary.get("timestamp")))

# Empty idea
empty_idea = generator.generate_idea(
    confluence_result=None,
    timestamp=_GOLDEN_TIMESTAMP,
)
empty_summary = generator.get_idea_summary(empty_idea)
check("12.10 Empty summary has_idea false", empty_summary.get("has_idea") is False)
check("12.11 Empty summary direction empty", empty_summary.get("direction") == "")

# =========================================================================
# 13. None inputs -> empty idea
# =========================================================================
print("\n--- 13. None inputs ---")

idea = generator.generate_idea()
check("13.1 Default direction empty", idea.direction == "")
check("13.2 Default no trade class", idea.trade_class_suggestion is None)
check("13.3 Default reasoning includes 'No trade idea'", "No trade idea" in idea.reasoning)
check("13.4 Default timestamp not None", idea.timestamp is not None)

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
