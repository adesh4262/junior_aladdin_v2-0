"""Junior Aladdin — Floor 4: Department Heads.

Floor 4 is the EXPERT INTERPRETATION layer.
It consumes Floor 3 structured intelligence and produces HeadReport + FloorSummary
for Captain consumption.

Architecture law:
- CONFIDENCE = Floor 4
- CONVICTION = Floor 5
- QUALITY = Floor 3

Every Head:
- Interprets Floor 3 signals (never recomputes them)
- Produces a HeadReport with bias, confidence, invalidation
- Reduces complexity for Captain
- SMC/ICT Heads must include context_quality_score
- Macro/Psychology Heads must NOT produce primary_setup or backup_setup
"""

from junior_aladdin.shared.types import HeadReport, HeadState, BiasType, FreshnessTag

from junior_aladdin.floor_4_heads.head_types import (
    HeadDecision,
    InvalidationRule,
    SetupGrade,
    TriggerInfo,
    TriggerStatus,
    ZoneInfo,
    ZoneStatus,
    compute_bias_from_signals,
    compute_confidence,
    compute_freshness,
)
from junior_aladdin.floor_4_heads.head_base import BaseHead, HeadMemory
from junior_aladdin.floor_4_heads.smc_head import SMCHead
from junior_aladdin.floor_4_heads.floor_summary_builder import FloorSummaryBuilder

__all__ = [
    # Shared types
    "HeadReport",
    "HeadState",
    "BiasType",
    "FreshnessTag",
    # Head-specific types
    "HeadDecision",
    "InvalidationRule",
    "SetupGrade",
    "TriggerInfo",
    "TriggerStatus",
    "ZoneInfo",
    "ZoneStatus",
    # Base
    "BaseHead",
    "HeadMemory",
    # Heads
    "SMCHead",
    # Summary
    "FloorSummaryBuilder",
    # Utilities
    "compute_bias_from_signals",
    "compute_confidence",
    "compute_freshness",
]
