"""Unit tests for ``technical_head.py`` — Floor 4 Step 4.8.

Tests:
- Signal extraction (TECHNICAL domain only)
- Full interpretation with RSI, MA cross, ATR, Volume Profile
- Empty signals fallback
- Bias determination from multiple indicators
- Primary/backup setup selection
- Invalidation generation
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from datetime import datetime

from junior_aladdin.floor_3_calculations.f3_contracts import OutputContract
from junior_aladdin.floor_3_calculations.f3_types import (
    CalculatedSignal,
    CalculationDomain,
)
from junior_aladdin.floor_4_heads.technical_head import TechnicalHead
from junior_aladdin.shared.types import BiasType, HeadState

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


def make_signal(indicator_type: str, value: dict, signal_id: str = "") -> CalculatedSignal:
    return CalculatedSignal(
        signal_id=signal_id or f"tech_{indicator_type}_{datetime.utcnow().timestamp()}",
        domain=CalculationDomain.TECHNICAL,
        indicator_type=indicator_type,
        value=value,
    )


def make_oc(signals: list[CalculatedSignal]) -> OutputContract:
    return OutputContract(signals=signals)


print("=" * 60)
print("Floor 4 — Technical Head Tests")
print("=" * 60)

# =========================================================================
# 1. Signal extraction
# =========================================================================
print("\n--- 1. Signal extraction ---")

head = TechnicalHead()
all_signals = [
    make_signal("RSI", {"rsi_value": 65.0}),
    make_signal("RSI", {"rsi_value": 70.0, "overbought": True}),
    make_signal("VOLUME_PROFILE", {"poc": 19550.0, "vah": 19600.0, "val": 19500.0, "volume_ratio": 1.5}),
]
oc = make_oc(all_signals)
extracted = head._extract_signals(oc)
check("1.1 Extracts TECHNICAL domain signals", len(extracted) == 3)
check("1.2 Filters out non-technical signals",
      all(s.domain == CalculationDomain.TECHNICAL for s in extracted))

# Non-technical signals filtered
oc_mixed = OutputContract(signals=[
    make_signal("RSI", {"rsi_value": 50.0}),
    CalculatedSignal(signal_id="smc1", domain=CalculationDomain.SMC,
                     indicator_type="FVG", value={"fvg_type": "BULLISH_FVG"}),
])
extracted2 = head._extract_signals(oc_mixed)
check("1.3 Only 1 technical signal extracted", len(extracted2) == 1)

# =========================================================================
# 2. Empty signals
# =========================================================================
print("\n--- 2. Empty signals ---")

oc_empty = make_oc([])
report = head.refresh(oc_empty)
check("2.1 Empty signals -> NEUTRAL bias",
      report.bias == BiasType.NEUTRAL)
check("2.2 Empty signals -> confidence 0", report.confidence == 0.0)
check("2.3 Empty signals -> STALE state",
      report.state == HeadState.STALE)
check("2.4 Empty signals -> has invalidation",
      len(report.invalidation.get("rules", [])) > 0)
check("2.5 Empty signals -> no primary setup",
      report.primary_setup is None)
check("2.6 Head name correct", report.head_name == "Technical Head")

# =========================================================================
# 3. Bullish signals — RSI, golden cross, volume
# =========================================================================
print("\n--- 3. Bullish signals ---")

bullish_signals = [
    make_signal("RSI", {"rsi_value": 65.0}),
    make_signal("MA_FAST", {"ma_value": 19600.0, "ma_type": "EMA"}),
    make_signal("MA_SLOW", {"ma_value": 19550.0, "ma_type": "EMA"}),
    make_signal("MA_CROSS", {"cross_type": "GOLDEN", "confirmed": True}),
    make_signal("ATR", {"atr_value": 120.0, "volatility_context": "NORMAL"}),
    make_signal("VOLUME_PROFILE", {"poc": 19550.0, "vah": 19650.0, "val": 19500.0, "volume_ratio": 1.8}),
]
oc_bull = make_oc(bullish_signals)
report = head.refresh(oc_bull)
check("3.1 Bullish signals -> BULLISH bias", report.bias == BiasType.BULLISH)
check("3.2 Confidence > 0", report.confidence > 0)
check("3.3 Has primary setup", report.primary_setup is not None)
check("3.4 Primary setup mentions trend or continuation",
      "Trend" in report.primary_setup or "Continuation" in report.primary_setup)
check("3.5 Has invalidation rules", len(report.invalidation.get("rules", [])) > 0)
check("3.6 Has active zones", len(report.active_zones) > 0)
check("3.7 Has witness summary", len(report.witness_summary) > 0)
check("3.8 Has timeframe_view", len(report.timeframe_view) > 0)
check("3.9 Has bull_case", len(report.bull_case) > 0)
check("3.10 Has bear_case", len(report.bear_case) > 0)
check("3.11 Has confluence_note", len(report.confluence_note) > 0)

# =========================================================================
# 4. Bearish signals — RSI overbought, death cross
# =========================================================================
print("\n--- 4. Bearish signals ---")

bearish_signals = [
    make_signal("RSI", {"rsi_value": 72.0, "overbought": True}),
    make_signal("MA_FAST", {"ma_value": 19400.0, "ma_type": "EMA"}),
    make_signal("MA_SLOW", {"ma_value": 19500.0, "ma_type": "EMA"}),
    make_signal("MA_CROSS", {"cross_type": "DEATH", "confirmed": True}),
    make_signal("ATR", {"atr_value": 150.0, "volatility_context": "HIGH"}),
    make_signal("VOLUME_PROFILE", {"poc": 19450.0, "vah": 19550.0, "val": 19350.0, "volume_ratio": 0.4}),
]
oc_bear = make_oc(bearish_signals)
report = head.refresh(oc_bear)
check("4.1 Bearish signals -> BEARISH bias", report.bias == BiasType.BEARISH)
check("4.2 Confidence > 0", report.confidence > 0)
check("4.3 Has primary setup", report.primary_setup is not None)

# =========================================================================
# 5. Neutral signals — mixed RSI, no cross
# =========================================================================
print("\n--- 5. Neutral signals ---")

neutral_signals = [
    make_signal("RSI", {"rsi_value": 52.0}),
    make_signal("MA_FAST", {"ma_value": 19500.0, "ma_type": "EMA"}),
    make_signal("MA_SLOW", {"ma_value": 19500.0, "ma_type": "EMA"}),
    make_signal("ATR", {"atr_value": 100.0, "volatility_context": "NORMAL"}),
    make_signal("VOLUME_PROFILE", {"poc": 19500.0, "vah": 19550.0, "val": 19450.0, "volume_ratio": 1.0}),
]
oc_neutral = make_oc(neutral_signals)
report = head.refresh(oc_neutral)
check("5.1 Neutral signals -> NEUTRAL bias", report.bias == BiasType.NEUTRAL)

# =========================================================================
# 6. RSI extremes
# =========================================================================
print("\n--- 6. RSI extremes ---")

# Overbought
overbought_oc = make_oc([
    make_signal("RSI", {"rsi_value": 82.0, "overbought": True}),
    make_signal("VOLUME_PROFILE", {"poc": 19600.0, "vah": 19700.0, "val": 19500.0, "volume_ratio": 2.0}),
])
report = head.refresh(overbought_oc)
check("6.1 Overbought RSI + high vol -> bias determined",
      report.bias in (BiasType.BULLISH, BiasType.BEARISH, BiasType.NEUTRAL))
check("6.2 Has invalidation", len(report.invalidation.get("rules", [])) > 0)

# =========================================================================
# 7. Volume profile only
# =========================================================================
print("\n--- 7. Volume profile only ---")

vol_only_oc = make_oc([
    make_signal("VOLUME_PROFILE", {"poc": 19500.0, "vah": 19600.0, "val": 19400.0, "volume_ratio": 1.2}),
])
report = head.refresh(vol_only_oc)
check("7.1 Volume only -> valid report", report.bias is not None)
check("7.2 Has POC zone", any(z.get("zone_type") == "POC" for z in report.active_zones))
check("7.3 Has VAH zone", any(z.get("zone_type") == "VOLUME_PROFILE_VAH" for z in report.active_zones))
check("7.4 Has VAL zone", any(z.get("zone_type") == "VOLUME_PROFILE_VAL" for z in report.active_zones))

# =========================================================================
# 8. Head name and properties
# =========================================================================
print("\n--- 8. Head properties ---")

head2 = TechnicalHead()
check("8.1 Head name", head2.head_name == "Technical Head")

head3 = TechnicalHead(name="custom_tech")
report3 = head3.refresh(oc_empty)
check("8.2 Custom name override", report3.head_name == "Technical Head")
# head_name comes from the property, not the _name

# =========================================================================
# 9. Freshness computation
# =========================================================================
print("\n--- 9. Freshness ---")

head4 = TechnicalHead()
report = head4.refresh(oc_empty)
check("9.1 freshness_score is 0.0-1.0", 0.0 <= report.freshness_score <= 1.0)
check("9.2 freshness_tag is valid", report.freshness_tag is not None)
check("9.3 last_deep_update set", report.last_deep_update is not None)


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
