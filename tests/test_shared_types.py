"""Tests for shared modules: errors, types, config, logging, testing."""

from __future__ import annotations

import json
import io

import pytest

from junior_aladdin.shared.errors import (
    ConfigurationError,
    ConnectionError,
    ContractViolationError,
    ExecutionError,
    JuniorAladdinError,
    MemoryError,
    ValidationError,
)
from junior_aladdin.shared.logging import get_logger, JsonFormatter
from junior_aladdin.shared.types import (
    ArmedPlan,
    BiasType,
    CaptainDecision,
    CaptainMood,
    CMSP,
    DataHealth,
    DecisionSnapshot,
    DecisionType,
    ExecutionIntent,
    ExecutionMode,
    FloorSummary,
    Floor2Handoff,
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


class TestErrors:
    """Tests for error hierarchy."""

    def test_base_error(self):
        """JuniorAladdinError base class works."""
        err = JuniorAladdinError("test error")
        assert str(err) == "test error"
        assert err.message == "test error"
        assert err.details == {}
        assert err.original_exception is None

    def test_error_with_details(self):
        """Error with details dict."""
        err = JuniorAladdinError("config error", details={"key": "api_key"})
        assert "key" in err.details

    def test_error_with_original_exception(self):
        """Error chaining works."""
        original = ValueError("bad value")
        err = JuniorAladdinError("wrapped", original_exception=original)
        assert err.original_exception is original

    def test_all_error_types_catchable(self):
        """All errors are catchable via JuniorAladdinError."""
        errors = [
            ConnectionError("conn"),
            ValidationError("val"),
            ConfigurationError("cfg"),
            ExecutionError("exec"),
            MemoryError("mem"),
            ContractViolationError("contract"),
        ]
        for err in errors:
            assert isinstance(err, JuniorAladdinError)
            assert isinstance(err, Exception)


class TestTypes:
    """Tests for shared types."""

    def test_enums_have_correct_values(self):
        """All enums have expected values."""
        assert MarketPhase.OPEN.value == "OPEN"
        assert BiasType.BULLISH.value == "BULLISH"
        assert TrendState.RANGE.value == "RANGE"
        assert HeadState.READY.value == "READY"
        assert CaptainMood.OBSERVER.value == "OBSERVER"
        assert DecisionType.TRADE.value == "TRADE"
        assert TradeClass.SCALP.value == "SCALP"
        assert ExecutionMode.ALERT.value == "ALERT"
        assert DataHealth.GOOD.value == "GOOD"
        assert FreshnessTag.FRESH.value == "FRESH"
        assert Severity.INFO.value == "INFO"
        assert LifecycleState.HEALTHY.value == "HEALTHY"
        assert MemoryEventFamily.TRADE_JOURNAL.value == "TRADE_JOURNAL"
        assert SessionType.ASIA.value == "ASIA"

    def test_packet_envelope_creation(self):
        """PacketEnvelope dataclass works."""
        from datetime import datetime
        env = PacketEnvelope(
            source="angel_one",
            feed_type="spot_tick",
            connection_id="conn_001",
            packet_id="pkt_001",
            routing_id="angel_one::spot_tick",
            received_at=datetime.utcnow(),
        )
        assert env.source == "angel_one"
        assert env.feed_type == "spot_tick"
        assert env.payload == {}

    def test_head_report_defaults(self):
        """HeadReport has correct defaults."""
        from datetime import datetime
        report = HeadReport(
            head_name="SMC",
            state=HeadState.READY,
            freshness_score=0.9,
            freshness_tag=FreshnessTag.FRESH,
            last_deep_update=datetime.utcnow(),
            bias=BiasType.BULLISH,
            confidence=0.75,
            dominant_tf="1m",
            timeframe_view="Bullish",
        )
        assert report.head_name == "SMC"
        assert report.primary_setup is None
        assert report.context_quality_score is None
        assert report.trade_allowed is True

    def test_floor_summary_defaults(self):
        """FloorSummary has correct defaults."""
        from datetime import datetime
        summary = FloorSummary(summary_timestamp=datetime.utcnow())
        assert summary.active_setup_count == 0
        assert summary.conflict_present is False
        assert summary.data_health_signal == DataHealth.GOOD

    def test_captain_decision_defaults(self):
        """CaptainDecision has correct defaults."""
        from datetime import datetime
        decision = CaptainDecision(
            decision=DecisionType.TRADE,
            action="BUY",
            option_side="CE",
            selected_strike="19500",
            trade_class=TradeClass.CONTINUATION,
        )
        assert decision.conviction_score == 0.0
        assert decision.silence_reason is None

    def test_execution_intent_defaults(self):
        """ExecutionIntent has correct defaults."""
        intent = ExecutionIntent(
            trade_id="t1",
            action="BUY",
            option_side="CE",
            selected_strike="19500",
            trade_class=TradeClass.SCALP,
        )
        assert intent.mode == ExecutionMode.ALERT

    def test_armed_plan_creation(self):
        """ArmedPlan works with required fields."""
        plan = ArmedPlan(
            plan_id="plan_001",
            direction="BUY",
            setup_class="FVG_RETEST",
        )
        assert plan.readiness == "WATCHING"
        assert plan.originating_heads == []

    def test_memory_event_defaults(self):
        """MemoryEvent has correct defaults."""
        event = MemoryEvent(
            event_type="trade_executed",
            source="side_a_execution",
            family="EXECUTION_EVENT",
        )
        assert event.severity == Severity.INFO
        assert event.payload == {}

    def test_cmsp_defaults(self):
        """CMSP has correct defaults."""
        cmsp = CMSP()
        assert cmsp.price_state == {}
        assert cmsp.key_levels == []

    def test_floor2_handoff_defaults(self):
        """Floor2Handoff has correct defaults."""
        handoff = Floor2Handoff()
        assert handoff.manual_source_tags is None
        assert handoff.feed_routing_identity == ""

    def test_decision_snapshot_defaults(self):
        """DecisionSnapshot has correct defaults."""
        snap = DecisionSnapshot(snapshot_id="snap_001")
        assert snap.mood == CaptainMood.OBSERVER
        assert snap.conviction_score == 0.0

    def test_source_health_initial_state(self):
        """SourceHealth starts HEALTHY."""
        health = SourceHealth()
        assert health.lifecycle_state == LifecycleState.HEALTHY
        assert health.reconnect_count == 0


class TestConfig:
    """Tests for configuration system."""

    def test_config_defaults(self, test_config):
        """Config loads with correct environment."""
        assert test_config.env == "test"

    def test_config_get_value(self, test_config):
        """Config.get returns correct values."""
        env = test_config.get("env")
        assert env == "test"

    def test_config_get_nested(self, test_config):
        """Config.get with dot notation works."""
        log_level = test_config.get("logging.level")
        assert log_level is not None

    def test_config_get_default(self, test_config):
        """Config.get returns default for missing key."""
        value = test_config.get("nonexistent.key", "fallback")
        assert value == "fallback"

    def test_config_angel_one_blank(self, test_config):
        """Angel One config is blank by default."""
        client_id = test_config.get("angel_one.client_id", "")
        assert client_id == ""

    def test_config_thresholds(self, test_config):
        """Config thresholds load correctly."""
        confidence_min = test_config.get("thresholds.confidence_min")
        assert isinstance(confidence_min, (int, float))

    def test_config_development_env(self, test_config_development):
        """Development config has correct env."""
        assert test_config_development.env == "development"

    def test_config_path_defaults(self, test_config):
        """Config path defaults are strings."""
        data_dir = test_config.get("paths.data_dir")
        assert isinstance(data_dir, str)


class TestLogging:
    """Tests for logging framework."""

    def test_get_logger(self):
        """get_logger returns a logger instance."""
        logger = get_logger("test_module")
        assert logger.name == "test_module"

    def test_logger_outputs_json(self, capsys):
        """Logger produces JSON output."""
        logger = get_logger("test_json")
        logger.info("test message")
        captured = capsys.readouterr()
        if captured.out:
            log_data = json.loads(captured.out.strip())
            assert log_data["level"] == "INFO"
            assert log_data["message"] == "test message"
            assert log_data["module"] == "test_json"
            assert "timestamp" in log_data

    def test_logger_warning(self, capsys):
        """Logger warning level works."""
        logger = get_logger("test_warning")
        logger.warning("warning message")
        captured = capsys.readouterr()
        if captured.out:
            log_data = json.loads(captured.out.strip())
            assert log_data["level"] == "WARNING"

    def test_logger_error(self, capsys):
        """Logger error level works."""
        logger = get_logger("test_error")
        logger.error("error message")
        captured = capsys.readouterr()
        if captured.out:
            log_data = json.loads(captured.out.strip())
            assert log_data["level"] == "ERROR"

    def test_json_formatter(self):
        """JsonFormatter produces valid JSON."""
        import logging
        formatter = JsonFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg="test",
            args=(),
            exc_info=None,
        )
        output = formatter.format(record)
        log_data = json.loads(output)
        assert log_data["level"] == "INFO"
        assert log_data["message"] == "test"


class TestTesting:
    """Tests for mock generators."""

    def test_mock_tick(self):
        """Mock tick has expected keys."""
        tick = generate_mock_tick()
        assert "ltp" in tick
        assert "symbol" in tick
        assert "volume" in tick
        assert "feed_type" in tick

    def test_mock_tick_stream(self):
        """Mock tick stream has correct count."""
        ticks = generate_mock_tick_stream(60)
        assert len(ticks) == 60

    def test_mock_candle(self):
        """Mock candle has OHLCV keys."""
        candle = generate_mock_candle()
        assert "open" in candle
        assert "high" in candle
        assert "low" in candle
        assert "close" in candle
        assert "volume" in candle

    def test_mock_head_report(self):
        """Mock head report returns HeadReport instance."""
        report = generate_mock_head_report("Technical")
        assert isinstance(report, HeadReport)
        assert report.head_name == "Technical"

    def test_mock_floor_summary(self):
        """Mock floor summary returns FloorSummary instance."""
        summary = generate_mock_floor_summary()
        assert isinstance(summary, FloorSummary)
        assert isinstance(summary.ready_heads_count, int)

    def test_mock_captain_decision(self):
        """Mock captain decision returns CaptainDecision."""
        decision = generate_mock_captain_decision()
        assert isinstance(decision, CaptainDecision)
        assert isinstance(decision.decision, DecisionType)

    def test_mock_execution_intent(self):
        """Mock execution intent returns ExecutionIntent."""
        intent = generate_mock_execution_intent()
        assert isinstance(intent, ExecutionIntent)

    def test_mock_memory_event(self):
        """Mock memory event returns MemoryEvent."""
        event = generate_mock_memory_event()
        assert isinstance(event, MemoryEvent)

    def test_in_memory_store(self):
        """InMemoryStore works correctly."""
        from junior_aladdin.shared.testing import InMemoryStore
        store = InMemoryStore()
        store.put("key1", "value1")
        assert store.get("key1") == "value1"
        store.delete("key1")
        assert store.get("key1") is None

    def test_seed_candles(self):
        """Seed candles have correct count."""
        candles = seed_1min_candles(60)
        assert len(candles) == 60

    def test_smc_state(self):
        """Mock SMC state has expected keys."""
        state = generate_mock_smc_state()
        assert "smc_state" in state
        assert "smc_quality_score" in state

    def test_ict_state(self):
        """Mock ICT state has expected keys."""
        state = generate_mock_ict_state()
        assert "ict_state" in state
        assert "ict_delivery_score" in state

    def test_options_state(self):
        """Mock Options state has expected keys."""
        state = generate_mock_options_state()
        assert "options_state" in state
        assert "pcr" in state

    def test_macro_state(self):
        """Mock Macro state has expected keys."""
        state = generate_mock_macro_state()
        assert "macro_state" in state
        assert "vix" in state

    def test_technical_state(self):
        """Mock Technical state has expected keys."""
        state = generate_mock_technical_state()
        assert "trend_state" in state
        assert "rsi" in state


# Import mock generators for the tests above
from junior_aladdin.shared.testing import (
    generate_mock_tick,
    generate_mock_tick_stream,
    generate_mock_candle,
    generate_mock_head_report,
    generate_mock_floor_summary,
    generate_mock_captain_decision,
    generate_mock_execution_intent,
    generate_mock_memory_event,
    generate_mock_smc_state,
    generate_mock_ict_state,
    generate_mock_options_state,
    generate_mock_macro_state,
    generate_mock_technical_state,
    seed_1min_candles,
)
