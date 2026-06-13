"""Junior Aladdin — Base Contract Definitions.

This file defines the formal contracts between modules.
Every module in the system must satisfy its Input, Output, and Error contracts.

**What is a contract?**
- Input Contract: What this module expects to receive from upstream/dependencies.
- Output Contract: What this module guarantees to produce for downstream consumers.
- Error Contract: What error states this module can raise or propagate.

**How to use:**
1. Every new module should have a corresponding CONTRACT dict entry.
2. Add the module name to the MODULE_CONTRACTS dict.
3. Define input_schema, output_schema, and error_types.

Architecture reference:
- QUALITY = Floor 3
- CONFIDENCE = Floor 4
- CONVICTION = Floor 5
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class BaseModuleContract:
    """Formal contract definition for a single module.

    Fields:
        module_name: Fully qualified module name (e.g., "shared.config").
        description: One-line purpose of the module.
        input_schema: Keys/types this module expects as input.
        output_schema: Keys/types this module guarantees as output.
        error_types: Exception types this module can raise.
        dependencies: Module names this module imports from.
        consumers: Module names that import from this module.
        owner: Floor/Side that owns this module (e.g., "Phase 0", "Floor 1").
    """
    module_name: str
    description: str
    input_schema: dict[str, str] = field(default_factory=dict)
    output_schema: dict[str, str] = field(default_factory=dict)
    error_types: list[str] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)
    consumers: list[str] = field(default_factory=list)
    owner: str = ""


# =============================================================================
# MODULE CONTRACTS REGISTRY
# =============================================================================
# Every module in the system should have an entry here.
# Add entries as new modules are created.

MODULE_CONTRACTS: dict[str, BaseModuleContract] = {
    "shared.errors": BaseModuleContract(
        module_name="shared.errors",
        description="Error hierarchy — all custom exceptions inherit from JuniorAladdinError.",
        input_schema={},
        output_schema={
            "JuniorAladdinError": "Base exception (message, details, original_exception)",
            "ConnectionError": "Floor 1 connectivity failures",
            "ValidationError": "Floor 2 data validation failures",
            "ConfigurationError": "Config loading failures",
            "ExecutionError": "Side A trade execution failures",
            "MemoryError": "Side C storage failures",
            "ContractViolationError": "Cross-floor contract mismatch",
        },
        error_types=["JuniorAladdinError"],
        dependencies=[],
        consumers=["shared.config", "shared.types", "shared.logging", "shared.testing"],
        owner="Phase 0",
    ),
    "shared.types": BaseModuleContract(
        module_name="shared.types",
        description="Single source of truth for all enums, dataclasses, and base contracts.",
        input_schema={},
        output_schema={
            "MarketPhase": "PRE_OPEN / OPEN / LUNCH / CLOSING / POST_CLOSE",
            "BiasType": "BULLISH / BEARISH / NEUTRAL",
            "TrendState": "STRONG_UP / WEAK_UP / RANGE / WEAK_DOWN / STRONG_DOWN",
            "HeadState": "READY / UNCERTAIN / STALE",
            "CaptainMood": "OBSERVER / PATIENT / AGGRESSIVE / DEFENSIVE / SILENT",
            "DecisionType": "TRADE / WAIT / BLOCKED",
            "TradeClass": "SCALP / CONTINUATION / REVERSAL / LIQUIDITY_RECLAIM / OPTIONS_PRESSURE",
            "ExecutionMode": "ALERT / PAPER / REAL",
            "DataHealth": "GOOD / CAUTION / DEGRADED / CRITICAL",
            "FreshnessTag": "FRESH / WARM / STALE",
            "Severity": "INFO / CAUTION / SEVERE / CRITICAL",
            "LifecycleState": "HEALTHY / DEGRADED / STALE / AUTH_FAILED / DISCONNECTED",
            "MemoryEventFamily": "8 event families",
            "FeedType": "SPOT / OPTIONS / VIX / CALENDAR / MACRO",
            "SessionType": "ASIA / LONDON / NY / ALL",
            "PacketEnvelope": "Floor 1 operational envelope",
            "SourceHealth": "Floor 1 connection health",
            "HeadReport": "Floor 4 head report with confidence",
            "FloorSummary": "Aggregated floor summary for Captain",
            "CaptainDecision": "Floor 5 final decision",
            "ExecutionIntent": "Side A execution intent",
            "ArmedPlan": "Conditional trade plan",
            "DecisionSnapshot": "Frozen decision record",
            "MemoryEvent": "Side C storage event",
            "CMSP": "Common Market State Projection",
            "Floor2Handoff": "Floor 1 → Floor 2 handoff",
        },
        error_types=[],
        dependencies=[],
        consumers=[
            "shared.logging", "shared.testing",
            "floor_1_connection.*", "floor_2_datacenter.*",
            "floor_3_calculations.*", "floor_4_heads.*",
            "floor_5_captain.*", "side_a_execution.*",
            "side_b_api.*", "side_c_memory.*",
        ],
        owner="Phase 0",
    ),
    "shared.config": BaseModuleContract(
        module_name="shared.config",
        description="YAML config loading with environment variable overrides.",
        input_schema={
            "config/default.yaml": "Default configuration values",
            "config/test.yaml": "Test environment overrides",
            "config/production.yaml": "Production environment overrides",
            ".env": "Environment variable file (optional)",
            "os.environ": "System environment variables",
        },
        output_schema={
            "Config.get(key_path)": "Typed config value via dot notation",
            "Config.env": "Current environment name",
            "Config.validate_required()": "Raises ConfigurationError if missing required keys",
        },
        error_types=["ConfigurationError"],
        dependencies=["shared.errors"],
        consumers=["shared.logging", "shared.testing", "all floors and sides"],
        owner="Phase 0",
    ),
    "shared.logging": BaseModuleContract(
        module_name="shared.logging",
        description="Centralized structured JSON logging with sensitive data redaction.",
        input_schema={
            "name": "Module name string",
            "level": "Optional log level override",
        },
        output_schema={
            "get_logger(name)": "Logger instance with JSON formatting",
            "structure JSON output": "{timestamp, level, module, message, extra?, exception?}",
            "setup_file_logging()": "Configures file-based logging with rotation",
        },
        error_types=["Exception (never crashes on log failure — fallback to stderr)"],
        dependencies=["shared.types", "shared.config"],
        consumers=["all floors and sides"],
        owner="Phase 0",
    ),
    "shared.testing": BaseModuleContract(
        module_name="shared.testing",
        description="Mock generators, seed data, and in-memory stores for testing.",
        input_schema={
            "shared.types": "All enums and dataclasses for type-correct mock data",
        },
        output_schema={
            "generate_mock_tick()": "Floor 1 mock tick",
            "generate_mock_tick_stream()": "Floor 1 mock tick stream",
            "generate_mock_candle()": "Floor 1/2 mock OHLCV candle",
            "generate_mock_floor2_handoff()": "Floor 1 → 2 handoff payload",
            "generate_mock_head_report()": "Floor 4 head report",
            "generate_mock_floor_summary()": "Floor 4 floor summary",
            "generate_mock_captain_decision()": "Floor 5 captain decision",
            "generate_mock_execution_intent()": "Side A execution intent",
            "generate_mock_memory_event()": "Side C memory event",
            "generate_mock_smc_state()": "Floor 3 SMC state",
            "generate_mock_ict_state()": "Floor 3 ICT state",
            "generate_mock_options_state()": "Floor 3 Options state",
            "generate_mock_macro_state()": "Floor 3 Macro state",
            "generate_mock_technical_state()": "Floor 3 Technical state",
            "InMemoryStore": "Key-value test store",
            "seed_1min_candles()": "Seed OHLCV data",
        },
        error_types=["AssertionError"],
        dependencies=["shared.types"],
        consumers=["tests.*", "all floors and sides (test code)"],
        owner="Phase 0",
    ),
    "shared.trading_calendar": BaseModuleContract(
        module_name="shared.trading_calendar",
        description="Central trading calendar — market hours, holidays, expiry, sessions.",
        input_schema={
            "date/datetime": "Query parameters (defaults to current IST)",
        },
        output_schema={
            "get_market_session()": "Complete MarketSession info",
            "is_market_open()": "bool — is market currently trading",
            "is_holiday()": "bool — is today an NSE holiday",
            "is_expiry_day()": "bool — is today expiry",
            "is_expiry_week()": "bool — are we in expiry week",
            "get_events_for_date()": "List[CalendarEvent] for given date",
            "get_next_event()": "Next upcoming calendar event",
        },
        error_types=[],
        dependencies=[],
        consumers=["floor_3_calculations.macro", "floor_4_heads.macro_head", "floor_5_captain"],
        owner="Phase 0 (shared infrastructure)",
    ),
}


def get_contract(module_name: str) -> BaseModuleContract | None:
    """Get the contract for a specific module.

    Args:
        module_name: Fully qualified module name (e.g., "shared.config").

    Returns:
        BaseModuleContract if found, None if module is not yet registered.
    """
    return MODULE_CONTRACTS.get(module_name)


def get_contracts_by_owner(owner: str) -> list[BaseModuleContract]:
    """Get all contracts belonging to a specific owner (floor/side).

    Args:
        owner: Owner name (e.g., "Phase 0", "Floor 1", "Side A").

    Returns:
        List of BaseModuleContract matching the owner.
    """
    return [c for c in MODULE_CONTRACTS.values() if c.owner == owner]


def get_consumer_chain(module_name: str) -> list[str]:
    """Get the full downstream consumer chain for a module.

    Args:
        module_name: Module name to trace consumers for.

    Returns:
        List of consumer module names.
    """
    contract = MODULE_CONTRACTS.get(module_name)
    if not contract:
        return []
    return list(contract.consumers)
