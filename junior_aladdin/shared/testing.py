"""Mock generators and testing utilities for Junior Aladdin.

Provides realistic mock data generators for ALL phases.
Every module in the system can use these for isolated testing.
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone
from typing import Any

from junior_aladdin.shared.types import (
    BiasType,
    CaptainDecision,
    CaptainMood,
    DataHealth,
    DecisionType,
    ExecutionMode,
    ExecutionIntent,
    FloorSummary,
    FreshnessTag,
    HeadReport,
    HeadState,
    MemoryEvent,
    MemoryEventFamily,
    PacketEnvelope,
    Severity,
    TradeClass,
)

# Seed for reproducible tests
random.seed(42)

# NIFTY 50 reasonable price range
NIFTY_BASE_PRICE = 19500.0


def _random_price(base: float = NIFTY_BASE_PRICE, variance: float = 10.0) -> float:
    """Generate a random price near the base."""
    return round(base + random.uniform(-variance, variance), 2)


def _random_datetime(days_back: int = 0) -> datetime:
    """Generate a random datetime within the last N days."""
    now = datetime.now(timezone.utc)
    offset = random.randint(0, days_back * 86400)
    return now - timedelta(seconds=offset)


# =============================================================================
# FLOOR 1 — TICK GENERATORS
# =============================================================================


def generate_mock_tick(
    price: float | None = None,
    symbol: str = "NIFTY",
    feed_type: str = "spot_tick",
) -> dict[str, Any]:
    """Generate a single mock tick as Angel One would send it."""
    p = price or _random_price()
    return {
        "symbol": symbol,
        "ltp": p,
        "volume": random.randint(100, 50000),
        "bid": round(p - random.uniform(0.5, 2.0), 2),
        "ask": round(p + random.uniform(0.5, 2.0), 2),
        "high": round(p + random.uniform(0, 5.0), 2),
        "low": round(p - random.uniform(0, 5.0), 2),
        "open": round(NIFTY_BASE_PRICE, 2),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "feed_type": feed_type,
    }


def generate_mock_tick_stream(count: int = 60, start_price: float | None = None) -> list[dict[str, Any]]:
    """Generate a stream of mock ticks simulating 1 minute of data."""
    price = start_price or NIFTY_BASE_PRICE
    ticks = []
    for _ in range(count):
        price = _random_price(price, 2.0)
        tick = generate_mock_tick(price=price)
        tick["ltp"] = price
        ticks.append(tick)
    return ticks


def generate_mock_candle(
    open_p: float | None = None,
    high: float | None = None,
    low: float | None = None,
    close: float | None = None,
    volume: int | None = None,
) -> dict[str, Any]:
    """Generate a single mock OHLCV candle."""
    base = open_p or _random_price()
    vol = volume or random.randint(10000, 500000)
    return {
        "open": base,
        "high": high or round(base + random.uniform(1, 15), 2),
        "low": low or round(base - random.uniform(1, 15), 2),
        "close": close or _random_price(base, 5.0),
        "volume": vol,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# =============================================================================
# FLOOR 2 — STRUCTURED DATA GENERATORS
# =============================================================================


def generate_mock_floor2_handoff(
    feed_type: str = "SPOT_FEED",
) -> dict[str, Any]:
    """Generate a mock Floor 1 → Floor 2 handoff payload."""
    tick = generate_mock_tick()
    return {
        "original_raw_packet": tick,
        "minimal_source_envelope": {
            "source": "angel_one",
            "feed_type": tick["feed_type"],
            "connection_id": "conn_001",
            "packet_id": f"pkt_{random.randint(1000, 9999)}",
            "routing_id": f"angel_one::{tick['feed_type']}",
            "received_at": datetime.now(timezone.utc).isoformat(),
        },
        "feed_routing_identity": feed_type,
        "source_health_facts": {
            "lifecycle_state": "HEALTHY",
            "latency_ms": random.uniform(5, 50),
            "heartbeat_age_s": random.uniform(0, 2),
            "reconnect_count": 0,
        },
        "manual_source_tags": None,
    }


# =============================================================================
# FLOOR 4 — HEAD REPORT GENERATORS
# =============================================================================


def generate_mock_head_report(
    head_name: str = "SMC",
    bias: BiasType | None = None,
    state: HeadState = HeadState.READY,
    confidence: float | None = None,
) -> HeadReport:
    """Generate a mock Department Head report."""
    b = bias or random.choice(list(BiasType))
    conf = confidence if confidence is not None else random.uniform(0.3, 0.95)
    now = datetime.now(timezone.utc)
    return HeadReport(
        head_name=head_name,
        state=state,
        freshness_score=random.uniform(0.7, 1.0),
        freshness_tag=FreshnessTag.FRESH,
        last_deep_update=now - timedelta(seconds=random.randint(10, 120)),
        bias=b,
        confidence=round(conf, 2),
        dominant_tf="1m",
        timeframe_view=f"Price in {b.value.lower()} zone",
        primary_setup="fvg_retest" if head_name in ("SMC", "ICT") else None,
        backup_setup="ob_bounce" if head_name in ("SMC",) else None,
        active_zones=[{"level": _random_price(), "type": "FVG", "strength": "strong"}],
        armed_triggers=[{"zone": _random_price(), "condition": "touch"}],
        invalidation={"level": _random_price(), "condition": "break"},
        bull_case=f"Bullish case: {b.value} structure intact",
        bear_case="Bearish case: sweep failure",
        confluence_note=f"{head_name} aligns with structure",
        witness_summary=f"{head_name} sees {b.value} opportunity",
        timestamp=now,
        context_quality_score=random.uniform(0.5, 1.0) if head_name in ("SMC", "ICT") else None,
    )


def generate_mock_floor_summary() -> FloorSummary:
    """Generate a mock Floor Summary from all 6 heads."""
    heads = ["Technical", "SMC", "ICT", "Options", "Macro", "Psychology"]
    reports = {h: generate_mock_head_report(h) for h in heads}
    now = datetime.now(timezone.utc)
    bullish_count = sum(1 for r in reports.values() if r.bias == BiasType.BULLISH)
    bearish_count = sum(1 for r in reports.values() if r.bias == BiasType.BEARISH)
    ready = sum(1 for r in reports.values() if r.state == HeadState.READY)
    uncertain = sum(1 for r in reports.values() if r.state == HeadState.UNCERTAIN)
    stale = sum(1 for r in reports.values() if r.state == HeadState.STALE)
    setups = [r.primary_setup for r in reports.values() if r.primary_setup]

    return FloorSummary(
        summary_timestamp=now,
        floor_bias_snapshot={"bullish": bullish_count, "bearish": bearish_count, "neutral": 6 - bullish_count - bearish_count},
        floor_confidence_snapshot={"average": round(random.uniform(0.4, 0.8), 2)},
        active_setup_count=len(setups),
        primary_setups_by_head={h: reports[h].primary_setup for h in heads if reports[h].primary_setup},
        backup_setups_by_head={h: reports[h].backup_setup for h in heads if reports[h].backup_setup},
        ready_heads_count=ready,
        uncertain_heads_count=uncertain,
        stale_heads_count=stale,
        conflict_present=bullish_count > 0 and bearish_count > 0,
        stale_warning_present=stale > 0,
        strongest_domain_signal="Bullish Structure + SMC Confluence",
        strongest_context_signal="Premium Zone Active",
        strongest_risk_warning="Macro Caution: FII Selling",
        data_health_signal=DataHealth.GOOD,
        summary_witness_lines=["SMC confident bullish", "ICT sees discount opportunity"],
        core_head_health_snapshot={h: reports[h].state.value for h in ["SMC", "ICT", "Technical"]},
        head_health_snapshot={h: {"state": reports[h].state.value, "freshness": reports[h].freshness_tag.value} for h in heads},
        setup_presence="HAS_SETUP" if setups else "NO_SETUP",
        setup_absence_context=None if setups else "READY_NO_SETUP",
    )


# =============================================================================
# FLOOR 5 — CAPTAIN DECISION GENERATORS
# =============================================================================


def generate_mock_captain_decision(
    decision: DecisionType = DecisionType.TRADE,
) -> CaptainDecision:
    """Generate a mock Captain decision."""
    now = datetime.now(timezone.utc)
    return CaptainDecision(
        decision=decision,
        action="BUY" if decision == DecisionType.TRADE else "NONE",
        option_side="CE" if decision == DecisionType.TRADE else "",
        selected_strike="19500",
        trade_class=TradeClass.CONTINUATION if decision == DecisionType.TRADE else TradeClass.SCALP,
        permission_score=85.0,
        conviction_score=72.0,
        no_trade_score=15.0 if decision == DecisionType.TRADE else 80.0,
        entry_plan={"zone": _random_price(), "type": "limit"},
        invalidation_level=_random_price(),
        stop_loss_plan={"level": _random_price(), "type": "fixed"},
        target_plan={"level": _random_price() + 50, "type": "1:2"},
        reason_summary="Strong SMC + ICT confluence in bullish structure",
        silence_reason=None if decision == DecisionType.TRADE else "insufficient_confluence",
        snapshot_id=f"snap_{random.randint(10000, 99999)}",
        timestamp=now,
    )


# =============================================================================
# SIDE A — EXECUTION INTENT GENERATOR
# =============================================================================


def generate_mock_execution_intent(
    mode: ExecutionMode = ExecutionMode.PAPER,
) -> ExecutionIntent:
    """Generate a mock execution intent from Captain."""
    return ExecutionIntent(
        trade_id=f"trade_{random.randint(10000, 99999)}",
        action="BUY",
        option_side="CE",
        selected_strike="19500",
        trade_class=TradeClass.CONTINUATION,
        entry_plan={"price": _random_price(), "quantity": 50},
        invalidation_level=_random_price(19400, 50),
        stop_loss_plan={"price": _random_price(19400, 30), "type": "fixed"},
        target_plan={"price": _random_price(19600, 50), "type": "1:2"},
        capital_context={"available": 50000, "max_risk": 5000},
        mode=mode,
        intervention_allowed=False,
    )


# =============================================================================
# SIDE C — MEMORY EVENT GENERATOR
# =============================================================================


def generate_mock_memory_event(family: str | None = None) -> MemoryEvent:
    """Generate a mock memory event for Side C."""
    fam = family or random.choice([f.value for f in MemoryEventFamily])
    return MemoryEvent(
        event_type=fam.lower(),
        source=random.choice(["floor_5_captain", "side_a_execution", "floor_1_connection"]),
        family=fam,
        severity=random.choice(list(Severity)),
        payload={"message": f"Mock {fam} event", "value": random.random()},
        refs={"source_id": f"ref_{random.randint(1000, 9999)}"},
    )


# =============================================================================
# FLOOR 3 — DOMAIN STATE GENERATOR
# =============================================================================


def generate_mock_smc_state() -> dict[str, Any]:
    """Generate mock SMC domain state."""
    return {
        "smc_state": "BULLISH",
        "ob_state": "ACTIVE",
        "fvg_state": "ACTIVE",
        "liquidity_state": "ABOVE",
        "sweep_state": "NO_SWEEP",
        "mitigation_state": "NONE",
        "smc_quality_score": round(random.uniform(0.3, 0.95), 2),
    }


def generate_mock_ict_state() -> dict[str, Any]:
    """Generate mock ICT domain state."""
    return {
        "ict_state": "BULLISH",
        "premium_discount_state": "DISCOUNT",
        "displacement_state": "BULLISH",
        "mss_state": "NONE",
        "delivery_context_state": "STRONG",
        "ict_delivery_score": round(random.uniform(0.3, 0.95), 2),
    }


def generate_mock_options_state() -> dict[str, Any]:
    """Generate mock Options domain state."""
    return {
        "options_state": "CALL_PRESSURE",
        "pressure_state": "BULLISH",
        "wall_state": "CALL_WALL",
        "iv_state": "LOW",
        "pcr": round(random.uniform(0.8, 1.5), 2),
        "max_pain": _random_price(),
    }


def generate_mock_macro_state() -> dict[str, Any]:
    """Generate mock Macro state."""
    return {
        "macro_state": "CAUTIOUS",
        "caution_state": "LIGHT",
        "event_risk_state": "CLEAR",
        "environment_state": "STABLE",
        "vix": round(random.uniform(12, 18), 2),
        "fii_dii_net": random.choice(["BUY", "SELL", "NEUTRAL"]),
    }


def generate_mock_technical_state() -> dict[str, Any]:
    """Generate mock Technical domain state."""
    return {
        "trend_state": "BULLISH",
        "momentum_state": "STRONG",
        "mtf_state": "ALIGNED",
        "ema_9": _random_price(),
        "ema_21": _random_price(19550, 100),
        "vwap": _random_price(),
        "rsi": round(random.uniform(40, 70), 1),
        "atr": round(random.uniform(30, 80), 1),
    }


# =============================================================================
# IN-MEMORY TEST STORE
# =============================================================================


class InMemoryStore:
    """Simple in-memory key-value store for testing."""

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}

    def put(self, key: str, value: Any) -> None:
        self._data[key] = value

    def get(self, key: str) -> Any | None:
        return self._data.get(key)

    def delete(self, key: str) -> None:
        self._data.pop(key, None)

    def clear(self) -> None:
        self._data.clear()

    def keys(self) -> list[str]:
        return list(self._data.keys())

    def __len__(self) -> int:
        return len(self._data)


# =============================================================================
# SEED DATA
# =============================================================================


def seed_1min_candles(count: int = 60) -> list[dict[str, Any]]:
    """Generate seed OHLCV data for 1 minute candles."""
    candles = []
    price = NIFTY_BASE_PRICE
    for i in range(count):
        price = _random_price(price, 5.0)
        candle = {
            "timestamp": (datetime.now(timezone.utc) - timedelta(minutes=count - i)).isoformat(),
            "open": round(price - random.uniform(0, 3), 2),
            "high": round(price + random.uniform(1, 8), 2),
            "low": round(price - random.uniform(1, 8), 2),
            "close": price,
            "volume": random.randint(10000, 300000),
        }
        candles.append(candle)
    return candles
