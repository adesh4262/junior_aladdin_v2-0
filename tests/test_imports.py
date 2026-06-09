"""Verify that all major imports work correctly.

This is the import chain validation test per ROADMAP_PHASE_0.
"""


def test_shared_errors_import():
    """All error types import correctly."""
    from junior_aladdin.shared.errors import (
        JuniorAladdinError,
        ConnectionError,
        ValidationError,
        ConfigurationError,
        ExecutionError,
        MemoryError,
        ContractViolationError,
    )
    assert JuniorAladdinError
    assert ConnectionError
    assert ValidationError
    assert ConfigurationError
    assert ExecutionError
    assert MemoryError
    assert ContractViolationError


def test_shared_types_import():
    """All shared types import correctly."""
    from junior_aladdin.shared.types import (
        MarketPhase,
        SessionType,
        BiasType,
        TrendState,
        HeadState,
        CaptainMood,
        DecisionType,
        TradeClass,
        ExecutionMode,
        DataHealth,
        FreshnessTag,
        Severity,
        LifecycleState,
        MemoryEventFamily,
        FeedType,
        PacketEnvelope,
        SourceHealth,
        HeadReport,
        FloorSummary,
        CaptainDecision,
        ExecutionIntent,
        ArmedPlan,
        DecisionSnapshot,
        MemoryEvent,
        CMSP,
        Floor2Handoff,
    )
    assert MarketPhase
    assert BiasType
    assert PacketEnvelope
    assert HeadReport
    assert FloorSummary
    assert CaptainDecision
    assert ExecutionIntent
    assert MemoryEvent


def test_shared_config_import():
    """Config imports correctly."""
    from junior_aladdin.shared.config import Config
    c = Config()
    assert c.get("env") is not None


def test_shared_logging_import():
    """Logging imports correctly."""
    from junior_aladdin.shared.logging import get_logger, severity_to_log_level
    logger = get_logger("test_import")
    assert logger is not None


def test_shared_testing_import():
    """Testing utilities import correctly."""
    from junior_aladdin.shared.testing import (
        generate_mock_tick,
        generate_mock_candle,
        generate_mock_head_report,
        generate_mock_floor_summary,
        generate_mock_captain_decision,
        generate_mock_memory_event,
        InMemoryStore,
        seed_1min_candles,
    )
    assert generate_mock_tick
    assert generate_mock_candle
    assert generate_mock_head_report
    assert generate_mock_floor_summary
    assert InMemoryStore


def test_all_packages_importable():
    """All floor/side packages import correctly."""
    import junior_aladdin.floor_1_connection
    import junior_aladdin.floor_2_datacenter
    import junior_aladdin.floor_3_calculations
    import junior_aladdin.floor_3_calculations.market_structure
    import junior_aladdin.floor_3_calculations.smc
    import junior_aladdin.floor_3_calculations.ict
    import junior_aladdin.floor_3_calculations.technical
    import junior_aladdin.floor_3_calculations.options
    import junior_aladdin.floor_3_calculations.macro
    import junior_aladdin.floor_3_calculations.support_metrics
    import junior_aladdin.floor_4_heads
    import junior_aladdin.floor_5_captain
    import junior_aladdin.side_a_execution
    import junior_aladdin.side_b_api
    import junior_aladdin.side_b_dashboard
    import junior_aladdin.side_c_memory
    assert junior_aladdin.floor_1_connection
    assert junior_aladdin.floor_2_datacenter
    assert junior_aladdin.floor_5_captain
