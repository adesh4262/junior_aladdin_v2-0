"""Floor 4 — Head Refresh Policy.

Defines common refresh rules that align with Captain's two-speed architecture.

Three refresh tiers:
A. **1-MINUTE BASE REFRESH** — Keep Captain updated at intraday speed.
   Refresh tactical interpretation, setup relevance, confidence, invalidation.
   Aligns with Captain's heavy cycle (1m candle close).

B. **5-MINUTE / 15-MINUTE DEEP REFRESH** — Deeper structural refresh.
   Stronger zone validity update, bigger timeframe confirmation refresh.
   Not every head rethinks structure every 1m (noise reduction).

C. **TICK-LEVEL LIGHT WATCH** — Trigger watch only.
   Invalidation touch awareness, micro confirmation watch.
   NOT full thinking on every tick (performance + noise).

Architecture rules:
- HEAD-SPECIFIC intervals (no one-size-fits-all).
- ``stale_after_seconds`` defines when state becomes STALE without update.
- ``tick_watch_enabled`` + ``min_ticks_between_refresh`` throttle tick-level work.

Usage::

    from junior_aladdin.floor_4_heads.head_refresh_policy import (
        REFRESH_POLICY_SMC,
        should_deep_refresh,
        should_base_refresh,
        should_tick_watch,
    )

    now = datetime.utcnow()
    last_deep = head._last_deep_update

    if should_deep_refresh(REFRESH_POLICY_SMC, last_deep, now):
        ...  # Full structural re-interpretation
    elif should_base_refresh(REFRESH_POLICY_SMC, last_deep, now):
        ...  # Tactical refresh
    elif should_tick_watch(REFRESH_POLICY_SMC, last_tick, tick_count):
        ...  # Light trigger observation
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any


# =============================================================================
# Refresh Tier Enum
# =============================================================================


class RefreshTier(Enum):
    """Which refresh tier is currently recommended for a Head.

    ``DEEP``: Time for full structural reinterpretation (5m/15m interval).
    ``BASE``: Time for tactical refresh (1m interval).
    ``TICK_WATCH``: Only light trigger observation is appropriate.
    ``SKIP``: No refresh needed yet — within cooldown window.
    """
    DEEP = "DEEP"
    BASE = "BASE"
    TICK_WATCH = "TICK_WATCH"
    SKIP = "SKIP"


# =============================================================================
# RefreshPolicy Dataclass
# =============================================================================


@dataclass
class RefreshPolicy:
    """Defines when a Head should perform base, deep, or tick-level refresh.

    Aligns with Captain's two-speed architecture:
    - Heavy cycle (1m candle close) → base refresh
    - Structural cycle (5m/15m) → deep refresh
    - Light cycle (tick) → tick watch only

    Fields:
        head_name: Human-readable name for logging/debugging.
        base_refresh_interval_seconds: Interval for base (tactical) refresh.
            Default ``60`` (1 minute — aligns with Captain's heavy cycle).
        deep_refresh_interval_seconds: Interval for deep (structural) refresh.
            Head-specific: ``300`` (5m) or ``900`` (15m).
        stale_after_seconds: Seconds without update before Head becomes STALE.
            Default ``300`` (5 minutes).
        tick_watch_enabled: Whether tick-level light watch is active.
        min_ticks_between_refresh: Minimum ticks between light-watch checks.
            Prevents excessive CPU on rapid tick sequences.
        description: Human-readable purpose of this policy.

    Example::

        policy = RefreshPolicy(
            head_name="smc",
            base_refresh_interval_seconds=60,
            deep_refresh_interval_seconds=300,
            stale_after_seconds=600,
            tick_watch_enabled=True,
            min_ticks_between_refresh=5,
        )
    """
    head_name: str = ""
    base_refresh_interval_seconds: int = 60        # 1m — Captain heavy cycle
    deep_refresh_interval_seconds: int = 300        # 5m — structural refresh
    stale_after_seconds: int = 300                  # 5m — default stale threshold
    tick_watch_enabled: bool = True
    min_ticks_between_refresh: int = 5
    description: str = ""


# =============================================================================
# Pre-built refresh policies for each Head type
# =============================================================================

# ── SMC HEAD ────────────────────────────────────────────────────────────
# Structural memory lasts longer; 5m deep refresh, 10m stale threshold
REFRESH_POLICY_SMC = RefreshPolicy(
    head_name="smc",
    base_refresh_interval_seconds=60,
    deep_refresh_interval_seconds=300,     # 5m — structure doesn't flip every minute
    stale_after_seconds=600,               # 10m — structural context degrades slower
    tick_watch_enabled=True,
    min_ticks_between_refresh=5,
    description="SMC: structural interpretation, 5m deep, 10m stale",
)

# ── ICT HEAD ────────────────────────────────────────────────────────────
# Similar to SMC — PD arrays, displacement, MSS need structural time
REFRESH_POLICY_ICT = RefreshPolicy(
    head_name="ict",
    base_refresh_interval_seconds=60,
    deep_refresh_interval_seconds=300,     # 5m — delivery context
    stale_after_seconds=600,               # 10m
    tick_watch_enabled=True,
    min_ticks_between_refresh=5,
    description="ICT: PD/displacement/MSS interpretation, 5m deep, 10m stale",
)

# ── TECHNICAL HEAD ─────────────────────────────────────────────────────
# Trend shifts can happen faster; 5m deep, 5m stale
REFRESH_POLICY_TECHNICAL = RefreshPolicy(
    head_name="technical",
    base_refresh_interval_seconds=60,
    deep_refresh_interval_seconds=300,     # 5m — MTF alignment
    stale_after_seconds=300,               # 5m — technical data decays faster
    tick_watch_enabled=True,
    min_ticks_between_refresh=5,
    description="Technical: trend/MTF/VWAP, 5m deep, 5m stale",
)

# ── OPTIONS HEAD ───────────────────────────────────────────────────────
# OI/PCR/Walls update slower; 15m deep, 15m stale
REFRESH_POLICY_OPTIONS = RefreshPolicy(
    head_name="options",
    base_refresh_interval_seconds=60,
    deep_refresh_interval_seconds=900,     # 15m — OI data shifts slower
    stale_after_seconds=900,               # 15m
    tick_watch_enabled=True,
    min_ticks_between_refresh=10,          # Options data ticks are less frequent
    description="Options: OI/PCR/walls, 15m deep, 15m stale",
)

# ── MACRO HEAD ─────────────────────────────────────────────────────────
# Macro context is slow-moving; 15m deep, 30m stale
REFRESH_POLICY_MACRO = RefreshPolicy(
    head_name="macro",
    base_refresh_interval_seconds=60,
    deep_refresh_interval_seconds=900,     # 15m — VIX/FII/events
    stale_after_seconds=1800,              # 30m — macro context lasts longer
    tick_watch_enabled=True,
    min_ticks_between_refresh=20,          # Macro doesn't change on every tick
    description="Macro: gate/context, 15m deep, 30m stale",
)

# ── PSYCHOLOGY HEAD ────────────────────────────────────────────────────
# Behavioural markers update in real-time; 5m deep, 10m stale
REFRESH_POLICY_PSYCHOLOGY = RefreshPolicy(
    head_name="psychology",
    base_refresh_interval_seconds=60,
    deep_refresh_interval_seconds=300,     # 5m — trap/cooldown awareness
    stale_after_seconds=600,               # 10m
    tick_watch_enabled=True,
    min_ticks_between_refresh=5,
    description="Psychology: brake/discipline, 5m deep, 10m stale",
)

# ── All policies indexed by head name ──────────────────────────────────

_ALL_POLICIES: dict[str, RefreshPolicy] = {
    "smc": REFRESH_POLICY_SMC,
    "ict": REFRESH_POLICY_ICT,
    "technical": REFRESH_POLICY_TECHNICAL,
    "options": REFRESH_POLICY_OPTIONS,
    "macro": REFRESH_POLICY_MACRO,
    "psychology": REFRESH_POLICY_PSYCHOLOGY,
}


# =============================================================================
# Refresh Decision Helpers
# =============================================================================


def should_deep_refresh(
    policy: RefreshPolicy,
    last_deep_update: datetime | None,
    now: datetime | None = None,
) -> bool:
    """Check whether a deep (structural) refresh is due.

    Deep refresh is due when enough time has passed since the last deep update,
    based on ``policy.deep_refresh_interval_seconds``.

    Args:
        policy: The Head's ``RefreshPolicy``.
        last_deep_update: Timestamp of the last deep refresh (UTC).
        now: Current time (UTC). Uses ``datetime.utcnow()`` if None.

    Returns:
        ``True`` if a deep refresh should be performed.
    """
    if last_deep_update is None:
        return True  # Never refreshed — definitely due

    check_time = now or datetime.utcnow()
    elapsed = (check_time - last_deep_update).total_seconds()
    return elapsed >= policy.deep_refresh_interval_seconds


def should_base_refresh(
    policy: RefreshPolicy,
    last_update: datetime | None,
    now: datetime | None = None,
) -> bool:
    """Check whether a base (tactical) refresh is due.

    Base refresh is due when enough time has passed since the last update,
    based on ``policy.base_refresh_interval_seconds``.

    A deep refresh ALSO qualifies as a base refresh (deep implies base).

    Args:
        policy: The Head's ``RefreshPolicy``.
        last_update: Timestamp of the last update (base or deep) (UTC).
        now: Current time (UTC). Uses ``datetime.utcnow()`` if None.

    Returns:
        ``True`` if a base refresh should be performed.
    """
    if last_update is None:
        return True

    check_time = now or datetime.utcnow()
    elapsed = (check_time - last_update).total_seconds()
    return elapsed >= policy.base_refresh_interval_seconds


def should_tick_watch(
    policy: RefreshPolicy,
    last_tick_time: datetime | None,
    tick_count_since_last_refresh: int = 0,
    now: datetime | None = None,
) -> bool:
    """Check whether tick-level light watch should activate.

    Tick watch is appropriate when:
    - Tick watch is enabled in the policy.
    - Enough ticks have passed since last check (throttling).
    - It's NOT time for a base or deep refresh (tick watch is for
      the period BETWEEN refreshes).

    Args:
        policy: The Head's ``RefreshPolicy``.
        last_tick_time: Timestamp of the last tick watch check (UTC).
        tick_count_since_last_refresh: How many ticks have been seen
            since the last refresh. Used for throttling.
        now: Current time (UTC). Uses ``datetime.utcnow()`` if None.

    Returns:
        ``True`` if tick watch should run a light check.
    """
    if not policy.tick_watch_enabled:
        return False

    # Don't tick-watch if we're due for a full refresh
    if should_base_refresh(policy, last_tick_time, now):
        return False

    # Throttle: enough ticks must have passed
    if tick_count_since_last_refresh < policy.min_ticks_between_refresh:
        return False

    return True


def get_refresh_tier(
    policy: RefreshPolicy,
    last_deep_update: datetime | None,
    last_update: datetime | None,
    last_tick_time: datetime | None = None,
    tick_count_since_last_refresh: int = 0,
    now: datetime | None = None,
) -> RefreshTier:
    """Determine the recommended refresh tier for a Head at this moment.

    Checks deep → base → tick → skip in priority order.

    Args:
        policy: The Head's ``RefreshPolicy``.
        last_deep_update: Last deep refresh timestamp.
        last_update: Last update (base or deep) timestamp.
        last_tick_time: Last tick watch timestamp (optional).
        tick_count_since_last_refresh: Ticks since last refresh.
        now: Current time (UTC).

    Returns:
        The recommended ``RefreshTier`` enum.
    """
    if should_deep_refresh(policy, last_deep_update, now):
        return RefreshTier.DEEP
    if should_base_refresh(policy, last_update, now):
        return RefreshTier.BASE
    if should_tick_watch(policy, last_tick_time, tick_count_since_last_refresh, now):
        return RefreshTier.TICK_WATCH
    return RefreshTier.SKIP


def is_stale(
    policy: RefreshPolicy,
    last_update: datetime | None,
    now: datetime | None = None,
) -> bool:
    """Check whether a Head has become stale (no update within threshold).

    Args:
        policy: The Head's ``RefreshPolicy``.
        last_update: Timestamp of the last any update (UTC).
        now: Current time (UTC). Uses ``datetime.utcnow()`` if None.

    Returns:
        ``True`` if the Head is past its ``stale_after_seconds`` threshold.
    """
    if last_update is None:
        return True  # Never updated — effectively stale

    check_time = now or datetime.utcnow()
    elapsed = (check_time - last_update).total_seconds()
    return elapsed >= policy.stale_after_seconds


def get_policy(head_name: str) -> RefreshPolicy | None:
    """Look up a RefreshPolicy by head name.

    Args:
        head_name: Lowercase head name (e.g., ``\"smc\"``, ``\"ict\"``).

    Returns:
        The matching ``RefreshPolicy``, or ``None`` if not found.
    """
    return _ALL_POLICIES.get(head_name.lower())
