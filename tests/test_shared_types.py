"""Tests for shared types, enums, dataclasses, and Config."""

from __future__ import annotations

from datetime import datetime
from enum import Enum

import pytest

from junior_aladdin.shared.config import Config
from junior_aladdin.shared.errors import (
    ConfigurationError,
    ConnectionError,
    ExecutionError,
    ValidationError,
)
from junior_aladdin.shared.types import (
    ArmedPlan,
    BiasType,
    CaptainDecision,
    CaptainMood,
    DataHealth,
    DecisionSnapshot,
    DecisionType,
    ExecutionIntent,
    ExecutionMode,
    FeedType,
    Floor2Handoff,
    FloorSummary,
    FreshnessTag,
    HeadReport,
    HeadState,
    LifecycleState,
    MarketPhase,
    MemoryEvent,
    MemoryEventFamily,
    PacketEnvelope,
    SessionType,
    Severity,
    SourceHealth,
    TradeClass,
    TrendState,
)


# =============================================================================
# Config Tests
# =============================================================================


class TestConfig:
    """Config class tests."""

    def test_config_get_value(self):
        """get() returns values via dot notation."""
        cfg = Config(env="test", load_dotenv=False)
        cfg._data["env"] = "test"
        assert cfg.env == "test"

    def test_config_angel_one_blank(self, monkeypatch):
        """Fresh Config with no .env has blank Angel One fields."""
        monkeypatch.delenv("ANGEL_ONE_CLIENT_ID", raising=False)
        monkeypatch.delenv("ANGEL_ONE_API_KEY", raising=False)
        monkeypatch.delenv("ANGEL_ONE_PIN", raising=False)
        cfg = Config(env="test", load_dotenv=False)
        cfg._data["angel_one"] = {"client_id": "", "api_key": "", "pin": ""}
        assert cfg.get("angel_one.client_id") == ""
        assert cfg.get("angel_one.api_key") == ""
        assert cfg.get("angel_one.pin") == ""

    def test_config_defaults(self, monkeypatch):
        """Config loads defaults merged with environment yaml overrides."""
        # Isolate from system env vars that might override YAML config
        monkeypatch.delenv("CAPITAL_PAPER_LIMIT", raising=False)
        monkeypatch.delenv("CAPITAL_REAL_LIMIT", raising=False)
        monkeypatch.delenv("CAPITAL_MAX_LOSS_PER_TRADE", raising=False)
        monkeypatch.delenv("ENV", raising=False)
        cfg = Config(env="test", load_dotenv=False)
        # paper_limit from test.yaml overrides default 100000
        assert cfg.get("capital.paper_limit") == 1000000
        # logging.level from test.yaml overrides default "INFO"
        assert cfg.get("logging.level") == "DEBUG"

    def test_config_overrides(self):
        """Overrides are properly applied."""
        cfg = Config(env="test", load_dotenv=False)
        cfg._data["thresholds"] = {"conviction_min": 70}
        assert cfg.get("thresholds.conviction_min") == 70

    def test_config_missing_key_returns_none(self):
        """Missing keys return default."""
        cfg = Config(env="test", load_dotenv=False)
        assert cfg.get("nonexistent.key") is None
        assert cfg.get("nonexistent", 42) == 42

    def test_config_env_property(self):
        """Config.env returns the configured environment."""
        cfg = Config(env="test", load_dotenv=False)
        cfg._data["env"] = "test"
        assert cfg.env == "test"

    def test_config_env_fallback(self):
        """Config.env falls back to default."""
        cfg = Config(load_dotenv=False)
        cfg._data["env"] = "development"
        assert cfg.env == "development"

    def test_config_validate_required_passes(self):
        """validate_required() passes with all required fields."""
        cfg = Config(env="test", load_dotenv=False)
        cfg._data["angel_one"] = {
            "client_id": "TEST001",
            "api_key": "test_key",
            "pin": "1234",
        }
        cfg.validate_required()

    def test_config_validate_fails_on_missing(self):
        """validate_required() raises on missing fields."""
        cfg = Config(env="test", load_dotenv=False)
        cfg._data["angel_one"] = {"client_id": "", "api_key": "", "pin": ""}
        with pytest.raises(ConfigurationError, match="Missing required"):
            cfg.validate_required()


# =============================================================================
# Enum Tests
# =============================================================================


class TestEnums:
    """All shared enums have correct values."""

    def test_bias_type(self):
        assert BiasType.BULLISH.value == "BULLISH"
        assert BiasType.BEARISH.value == "BEARISH"
        assert BiasType.NEUTRAL.value == "NEUTRAL"

    def test_captain_mood(self):
        assert CaptainMood.OBSERVER.value == "OBSERVER"
        assert CaptainMood.PATIENT.value == "PATIENT"
        assert CaptainMood.AGGRESSIVE.value == "AGGRESSIVE"
        assert CaptainMood.DEFENSIVE.value == "DEFENSIVE"
        assert CaptainMood.SILENT.value == "SILENT"

    def test_decision_type(self):
        assert DecisionType.TRADE.value == "TRADE"
        assert DecisionType.WAIT.value == "WAIT"
        assert DecisionType.BLOCKED.value == "BLOCKED"

    def test_execution_mode(self):
        assert ExecutionMode.ALERT.value == "ALERT"
        assert ExecutionMode.PAPER.value == "PAPER"
        assert ExecutionMode.REAL.value == "REAL"

    def test_data_health(self):
        assert DataHealth.GOOD.value == "GOOD"
        assert DataHealth.DEGRADED.value == "DEGRADED"
        assert DataHealth.CRITICAL.value == "CRITICAL"

    def test_trade_class(self):
        assert TradeClass.SCALP.value == "SCALP"
        assert TradeClass.CONTINUATION.value == "CONTINUATION"
        assert TradeClass.REVERSAL.value == "REVERSAL"

    def test_head_state(self):
        assert HeadState.READY.value == "READY"
        assert HeadState.UNCERTAIN.value == "UNCERTAIN"
        assert HeadState.STALE.value == "STALE"

    def test_freshness_tag(self):
        assert FreshnessTag.FRESH.value == "FRESH"
        assert FreshnessTag.WARM.value == "WARM"
        assert FreshnessTag.STALE.value == "STALE"

    def test_severity(self):
        assert Severity.INFO.value == "INFO"
        assert Severity.CAUTION.value == "CAUTION"
        assert Severity.SEVERE.value == "SEVERE"
        assert Severity.CRITICAL.value == "CRITICAL"

    def test_lifecycle_state(self):
        assert LifecycleState.HEALTHY.value == "HEALTHY"
        assert LifecycleState.DEGRADED.value == "DEGRADED"
        assert LifecycleState.STALE.value == "STALE"
        assert LifecycleState.AUTH_FAILED.value == "AUTH_FAILED"
        assert LifecycleState.DISCONNECTED.value == "DISCONNECTED"

    def test_market_phase(self):
        assert MarketPhase.OPEN.value == "OPEN"
        assert MarketPhase.LUNCH.value == "LUNCH"
        assert MarketPhase.CLOSING.value == "CLOSING"

    def test_session_type(self):
        assert SessionType.ASIA.value == "ASIA"
        assert SessionType.LONDON.value == "LONDON"
        assert SessionType.NY.value == "NY"

    def test_trend_state(self):
        assert TrendState.STRONG_UP.value == "STRONG_UP"
        assert TrendState.RANGE.value == "RANGE"
        assert TrendState.STRONG_DOWN.value == "STRONG_DOWN"

    def test_feed_type(self):
        assert FeedType.SPOT_FEED.value == "SPOT_FEED"
        assert FeedType.OPTIONS_FEED.value == "OPTIONS_FEED"
        assert FeedType.VIX_FEED.value == "VIX_FEED"

    def test_memory_event_family(self):
        assert MemoryEventFamily.TRADE_JOURNAL.value == "TRADE_JOURNAL"
        assert MemoryEventFamily.EXECUTION_EVENT.value == "EXECUTION_EVENT"

    def test_all_enums_have_unique_values(self):
        """No duplicate values within any enum."""
        for enum_class in [BiasType, CaptainMood, DecisionType, ExecutionMode,
                           DataHealth, TradeClass, HeadState, FreshnessTag,
                           Severity, LifecycleState, MarketPhase, SessionType,
                           TrendState, FeedType, MemoryEventFamily]:
            values = [e.value for e in enum_class]
            assert len(values) == len(set(values)), f"{enum_class.__name__} has duplicates"


# =============================================================================
# Dataclass Tests
# =============================================================================


class TestPacketEnvelope:
    """PacketEnvelope dataclass tests."""

    def test_default_creation(self):
        env = PacketEnvelope(
            source="test",
            feed_type="spot_tick",
            connection_id="conn_001",
            packet_id="pkt_001",
            routing_id="route_001",
            received_at=datetime.utcnow(),
        )
        assert env.source == "test"
        assert env.feed_type == "spot_tick"
        assert env.packet_id == "pkt_001"
        assert env.payload == {}

    def test_with_payload(self):
        env = PacketEnvelope(
            source="test",
            feed_type="spot_tick",
            connection_id="conn_001",
            packet_id="pkt_001",
            routing_id="route_001",
            received_at=datetime.utcnow(),
            payload={"ltp": 19500.0},
        )
        assert env.payload["ltp"] == 19500.0


class TestSourceHealth:
    """SourceHealth dataclass tests."""

    def test_default_creation(self):
        sh = SourceHealth()
        assert sh.lifecycle_state == LifecycleState.HEALTHY
        assert sh.latency_ms == 0.0
        assert sh.reconnect_count == 0

    def test_custom_values(self):
        sh = SourceHealth(
            lifecycle_state=LifecycleState.DEGRADED,
            latency_ms=150.0,
            reconnect_count=3,
        )
        assert sh.lifecycle_state == LifecycleState.DEGRADED
        assert sh.latency_ms == 150.0


class TestHeadReport:
    """HeadReport dataclass tests."""

    def test_default_creation(self):
        hr = HeadReport(
            head_name="SMC Head",
            state=HeadState.READY,
            freshness_score=1.0,
            freshness_tag=FreshnessTag.FRESH,
            last_deep_update=datetime.utcnow(),
            bias=BiasType.NEUTRAL,
            confidence=0.5,
            dominant_tf="",
            timeframe_view="1m",
        )
        assert hr.head_name == "SMC Head"
        assert hr.state == HeadState.READY
        assert hr.confidence == 0.5

    def test_with_setups(self):
        hr = HeadReport(
            head_name="ICT Head",
            state=HeadState.READY,
            freshness_score=0.9,
            freshness_tag=FreshnessTag.FRESH,
            last_deep_update=datetime.utcnow(),
            bias=BiasType.BULLISH,
            confidence=0.8,
            dominant_tf="",
            timeframe_view="1m",
            primary_setup="FVG",
            backup_setup="Order Block",
            context_quality_score=0.75,
        )
        assert hr.primary_setup == "FVG"
        assert hr.context_quality_score == 0.75

    def test_macro_head_no_setups(self):
        hr = HeadReport(
            head_name="Macro Head",
            state=HeadState.READY,
            freshness_score=0.8,
            freshness_tag=FreshnessTag.FRESH,
            last_deep_update=datetime.utcnow(),
            bias=BiasType.NEUTRAL,
            confidence=0.5,
            dominant_tf="",
            timeframe_view="1d",
            event_risk_flag=True,
        )
        assert hr.primary_setup is None
        assert hr.event_risk_flag is True


class TestFloorSummary:
    """FloorSummary dataclass tests."""

    def test_default_creation(self):
        fs = FloorSummary(summary_timestamp=datetime.utcnow())
        assert fs.active_setup_count == 0
        assert fs.ready_heads_count == 0
        assert fs.data_health_signal == DataHealth.GOOD

    def test_with_values(self):
        fs = FloorSummary(
            summary_timestamp=datetime.utcnow(),
            active_setup_count=3,
            ready_heads_count=4,
            uncertain_heads_count=1,
            stale_heads_count=0,
            conflict_present=False,
            data_health_signal=DataHealth.GOOD,
        )
        assert fs.active_setup_count == 3
        assert fs.ready_heads_count == 4


class TestCaptainDecision:
    """CaptainDecision dataclass tests."""

    def test_trade_decision(self):
        d = CaptainDecision(
            decision=DecisionType.TRADE,
            action="BUY",
            option_side="CE",
            selected_strike="19500",
            trade_class=TradeClass.SCALP,
            conviction_score=75.0,
        )
        assert d.decision == DecisionType.TRADE
        assert d.action == "BUY"
        assert d.conviction_score == 75.0

    def test_wait_decision(self):
        d = CaptainDecision(
            decision=DecisionType.WAIT,
            action="",
            option_side="",
            selected_strike="",
            trade_class=TradeClass.SCALP,
            silence_reason="WEAK_CONVICTION",
        )
        assert d.decision == DecisionType.WAIT
        assert d.silence_reason == "WEAK_CONVICTION"


class TestExecutionIntent:
    """ExecutionIntent dataclass tests."""

    def test_minimal_intent(self):
        intent = ExecutionIntent(
            trade_id="TRADE-001",
            action="BUY",
            option_side="CE",
            selected_strike="19500",
            trade_class=TradeClass.SCALP,
        )
        assert intent.trade_id == "TRADE-001"
        assert intent.mode == ExecutionMode.ALERT

    def test_full_intent(self):
        intent = ExecutionIntent(
            trade_id="TRADE-002",
            action="SELL",
            option_side="PE",
            selected_strike="19000",
            trade_class=TradeClass.CONTINUATION,
            mode=ExecutionMode.PAPER,
            capital_context={"available": 50000},
        )
        assert intent.mode == ExecutionMode.PAPER
        assert intent.capital_context["available"] == 50000


class TestErrorClasses:
    """Custom error hierarchy tests."""

    def test_validation_error(self):
        err = ValidationError("Invalid value", details={"field": "price"})
        assert "Invalid value" in str(err)
        assert err.details["field"] == "price"

    def test_connection_error(self):
        err = ConnectionError("Connection failed", details={"host": "localhost"})
        assert "Connection failed" in str(err)

    def test_execution_error(self):
        err = ExecutionError("Execution blocked", details={"reason": "risk gate"})
        assert "Execution blocked" in str(err)

    def test_configuration_error(self):
        err = ConfigurationError("Missing config", details={"key": "angel_one"})
        assert "Missing config" in str(err)

    def test_error_chain(self):
        inner = ValueError("original")
        outer = ValidationError("wrapped", original_exception=inner)
        assert "wrapped" in str(outer)


class TestOtherDataclasses:
    """Tests for remaining dataclasses."""

    def test_armed_plan(self):
        p = ArmedPlan(
            plan_id="PLAN-001",
            direction="BUY",
            setup_class="FVG",
            readiness="WATCHING",
        )
        assert p.plan_id == "PLAN-001"
        assert p.readiness == "WATCHING"

    def test_decision_snapshot(self):
        snap = DecisionSnapshot(
            snapshot_id="SNAP-001",
            conviction_score=80.0,
        )
        assert snap.snapshot_id == "SNAP-001"
        assert snap.conviction_score == 80.0

    def test_floor2_handoff(self):
        handoff = Floor2Handoff(
            original_raw_packet={"ltp": 19500},
            feed_routing_identity="SPOT_FEED",
        )
        assert handoff.original_raw_packet["ltp"] == 19500

    def test_memory_event(self):
        evt = MemoryEvent(
            event_type="TRADE_OPENED",
            source="floor_5",
            family="TRADE_JOURNAL",
            emitter="captain_engine",
            severity=Severity.INFO,
            payload={"trade_id": "TRADE-001"},
        )
        assert evt.event_type == "TRADE_OPENED"
        assert evt.family == "TRADE_JOURNAL"

    def test_memory_event_defaults(self):
        evt = MemoryEvent(
            event_type="TEST",
            source="test",
            family="TRADE_JOURNAL",
        )
        assert evt.severity == Severity.INFO
        assert evt.payload == {}
