"""Floor 5 — Confidence Decay Engine (Step 5.15).

Gradually lowers conviction when setup freshness weakens over time.
Differs from expiry (hard cutoff) — decay is gradual softening.

Architecture (see ROADMAP_FLOOR_05 Section 15 & 5.15):
- Setup still technically valid, but freshness weakens
- Conviction gradually decays as time passes without trigger
- Different decay rates by trade class
- Decay is applied by captain_engine AFTER expiry check
- Works alongside setup_expiry_manager (hard cutoff) as a complementary system

Decay rates (LOCKED — per candle elapsed):
- SCALP: 0.30 — fast decay (tight window, must trigger quickly)
- CONTINUATION: 0.10 — slow decay (trend lasts longer)
- REVERSAL: 0.15 — moderate decay (needs confirmation within reasonable window)
- LIQUIDITY_RECLAIM: 0.05 — very slow (zone-based, stays valid longer)
- OPTIONS_PRESSURE: 0.05 — very slow (wall-based, pressure persists)
- Unknown/None: 0.10 — moderate default
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from junior_aladdin.shared.types import TradeClass


# ── Decay rates by trade class (per candle) (LOCKED) ────────────────────────
# Higher = faster decay. Multiplied by candles elapsed to produce decay factor.
# Decay factor always clamped to [0.0, 1.0].

_DECAY_RATES: dict[TradeClass, float] = {
    TradeClass.SCALP: 0.30,
    TradeClass.CONTINUATION: 0.10,
    TradeClass.REVERSAL: 0.15,
    TradeClass.LIQUIDITY_RECLAIM: 0.05,
    TradeClass.OPTIONS_PRESSURE: 0.05,
}

# Fallback rate for unknown / None trade class
_DEFAULT_DECAY_RATE = 0.10

# Minimum decay factor — conviction never fully decays to zero automatically
_MIN_DECAY_FACTOR = 0.10


# ── DecayResult dataclass ─────────────────────────────────────────────────


@dataclass
class DecayResult:
    """Result of applying confidence decay to a conviction score.

    Fields:
        original_score: The conviction score before decay (0.0-100.0).
        decayed_score: The conviction score after decay is applied.
        decay_factor: The calculated decay factor (0.0-1.0).
                      1.0 = no decay, 0.0 = fully decayed.
        elapsed_candles: Number of candles since creation/trigger.
        trade_class: The trade class used for decay rate lookup.
        decay_rate: The decay rate applied (per candle).
        band_downgraded: Whether the decay caused a conviction band drop.
        original_band: The conviction band before decay (as string).
        new_band: The conviction band after decay (as string).
    """
    original_score: float = 0.0
    decayed_score: float = 0.0
    decay_factor: float = 1.0
    elapsed_candles: int = 0
    trade_class: str = ""
    decay_rate: float = 0.0
    band_downgraded: bool = False
    original_band: str = ""
    new_band: str = ""


# ── Conviction score-to-band helper (local copy to avoid captain_types import) ──


def _score_to_band(score: float) -> str:
    """Map a conviction score (0-100) to a band label string."""
    if score >= 90:
        return "ELITE"
    elif score >= 75:
        return "STRONG"
    elif score >= 60:
        return "TRADABLE"
    elif score >= 40:
        return "WEAK"
    return "REJECT"


# ── ConfidenceDecayEngine ─────────────────────────────────────────────────


class ConfidenceDecayEngine:
    """Gradually decays conviction scores as setups age.

    Unlike ``SetupExpiryManager`` (hard cutoff), this engine applies a
    gradual softening to conviction scores based on the number of candles
    elapsed since a setup was created.

    Usage::

        engine = ConfidenceDecayEngine()

        # Get decay factor for a SCALP setup that is 3 candles old
        factor = engine.calculate_decay(TradeClass.SCALP, 3)
        # factor → 0.10 (clamped minimum)

        # Apply decay to a conviction score
        result = engine.apply_decay(conviction_score=72.0,
                                    trade_class=TradeClass.SCALP,
                                    elapsed_candles=3)
        # result.decayed_score → 7.2
        # result.band_downgraded → True
    """

    def __init__(self) -> None:
        """Initialize the confidence decay engine."""
        pass

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_decay_rate(self, trade_class: TradeClass | None) -> float:
        """Get the decay rate (per candle) for a trade class.

        Args:
            trade_class: The TradeClass to look up, or None.

        Returns:
            Float decay rate per candle (e.g., 0.30 for SCALP).
        """
        if trade_class is None:
            return _DEFAULT_DECAY_RATE
        return _DECAY_RATES.get(trade_class, _DEFAULT_DECAY_RATE)

    def calculate_decay(
        self,
        trade_class: TradeClass | None,
        elapsed_candles: int,
    ) -> float:
        """Calculate the decay factor for a setup.

        Decay factor = max(min_decay, 1.0 - (rate × elapsed_candles))

        Args:
            trade_class: The trade class of the setup.
            elapsed_candles: Number of candles since creation/trigger.

        Returns:
            Decay factor between 0.0 and 1.0.
            1.0 = no decay; 0.0 (or _MIN_DECAY_FACTOR) = fully decayed.
        """
        if elapsed_candles <= 0:
            return 1.0

        rate = self.get_decay_rate(trade_class)
        raw_factor = 1.0 - (rate * elapsed_candles)
        return max(_MIN_DECAY_FACTOR, min(1.0, raw_factor))

    def apply_decay(
        self,
        conviction_score: float,
        trade_class: TradeClass | None = None,
        elapsed_candles: int = 0,
    ) -> DecayResult:
        """Apply confidence decay to a conviction score.

        The conviction score is multiplied by the decay factor to produce
        a decayed score. The method also tracks whether the decay caused
        a conviction band downgrade.

        Args:
            conviction_score: The original conviction score (0.0-100.0).
            trade_class: The trade class of the setup.
            elapsed_candles: Number of candles since creation/trigger.

        Returns:
            A ``DecayResult`` with original, decayed scores and metadata.
        """
        rate = self.get_decay_rate(trade_class)
        decay_factor = self.calculate_decay(trade_class, elapsed_candles)
        decayed_score = conviction_score * decay_factor

        original_band = _score_to_band(conviction_score)
        new_band = _score_to_band(decayed_score)

        return DecayResult(
            original_score=round(conviction_score, 1),
            decayed_score=round(decayed_score, 1),
            decay_factor=round(decay_factor, 4),
            elapsed_candles=elapsed_candles,
            trade_class=trade_class.value if trade_class else "UNKNOWN",
            decay_rate=rate,
            band_downgraded=original_band != new_band,
            original_band=original_band,
            new_band=new_band,
        )

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    def get_decay_summary(self) -> dict[str, Any]:
        """Get a summary of all trade class decay rates.

        Returns:
            Dict mapping trade class names to their per-candle decay rates.
        """
        return {
            tc.value: self.get_decay_rate(tc)
            for tc in TradeClass
        }
