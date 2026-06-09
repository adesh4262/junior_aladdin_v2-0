"""Tests for Floor 2 Governance sub-system (Step 2.10).

Tests cover:
- DataContractRegistry: register, get, validate, enforce, report
- RegistryLoader: load defaults, config loading, hot-reload
- RuntimeContractChecks: stage checks, Floor 3 handoff enforcement
- SourcePolicyRegistry: register, feed allowance, validation tier
- RetentionPolicyRegistry: TTL defaults, overrides, reporting
"""

from __future__ import annotations

import pytest

from junior_aladdin.floor_2_datacenter.data_contract_registry import (
    DataContractRegistry,
)
from junior_aladdin.floor_2_datacenter.datacenter_contracts import (
    Candle,
    CandleStream,
    ComputedReadyHook,
    Floor3Handoff,
    MacroSupportStream,
    OptionsSnapshot,
    OptionsSnapshotStream,
    SessionPacket,
    TickStream,
)
from junior_aladdin.floor_2_datacenter.datacenter_types import (
    DataClass,
    FeedContract,
)
from junior_aladdin.floor_2_datacenter.governance.registry_loader import (
    RegistryLoader,
)
from junior_aladdin.floor_2_datacenter.governance.retention_policy_registry import (
    RetentionPolicyRegistry,
)
from junior_aladdin.floor_2_datacenter.governance.runtime_contract_checks import (
    RuntimeContractChecks,
)
from junior_aladdin.floor_2_datacenter.governance.source_policy_registry import (
    SourcePolicyRegistry,
)
from junior_aladdin.shared.errors import ContractViolationError


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def spot_contract() -> FeedContract:
    return FeedContract(
        name="spot_tick",
        ownership="Floor 2",
        schema_fields={"ltp": "float", "volume": "int", "symbol": "str", "feed_type": "str", "timestamp": "str"},
        freshness_expectation_s=1.0,
        source_expectations=["angel_one"],
        data_class=DataClass.MAJOR,
        consumers=["Floor 3"],
    )


@pytest.fixture
def macro_contract() -> FeedContract:
    return FeedContract(
        name="macro_data",
        ownership="Floor 2",
        schema_fields={"feed_type": "str", "value": "float"},
        freshness_expectation_s=300.0,
        source_expectations=["angel_one", "manual"],
        data_class=DataClass.MINOR,
        consumers=["Floor 3 Macro"],
    )


@pytest.fixture
def registry(spot_contract: FeedContract, macro_contract: FeedContract) -> DataContractRegistry:
    reg = DataContractRegistry()
    reg.register(spot_contract)
    reg.register(macro_contract)
    return reg


# =============================================================================
# DataContractRegistry
# =============================================================================


class TestDataContractRegistry:
    def test_register_and_get(self, registry: DataContractRegistry, spot_contract: FeedContract) -> None:
        contract = registry.get("spot_tick")
        assert contract is not None
        assert contract.name == "spot_tick"
        assert contract.ownership == "Floor 2"

    def test_get_nonexistent(self, registry: DataContractRegistry) -> None:
        assert registry.get("nonexistent") is None

    def test_get_or_default_returns_existing(self, registry: DataContractRegistry) -> None:
        contract = registry.get_or_default("spot_tick")
        assert contract.name == "spot_tick"

    def test_get_or_default_creates_minor(self, registry: DataContractRegistry) -> None:
        contract = registry.get_or_default("unknown_feed")
        assert contract.name == "unknown_feed"
        assert contract.data_class == DataClass.MINOR

    def test_register_many(self, registry: DataContractRegistry) -> None:
        assert registry.count() == 2

    def test_update_contract(self, registry: DataContractRegistry) -> None:
        assert registry.update("spot_tick", freshness_expectation_s=60.0) is True
        contract = registry.get("spot_tick")
        assert contract is not None
        assert contract.freshness_expectation_s == 60.0

    def test_update_nonexistent(self, registry: DataContractRegistry) -> None:
        assert registry.update("nonexistent", freshness_expectation_s=60.0) is False

    def test_remove_contract(self, registry: DataContractRegistry) -> None:
        assert registry.remove("macro_data") is True
        assert registry.get("macro_data") is None
        assert registry.count() == 1

    def test_remove_nonexistent(self, registry: DataContractRegistry) -> None:
        assert registry.remove("nonexistent") is False

    def test_has_contract(self, registry: DataContractRegistry) -> None:
        assert registry.has("spot_tick") is True
        assert registry.has("nonexistent") is False

    def test_list_contracts(self, registry: DataContractRegistry) -> None:
        contracts = registry.list_contracts()
        assert len(contracts) == 2
        assert contracts[0].name == "macro_data"  # sorted

    def test_get_names(self, registry: DataContractRegistry) -> None:
        names = registry.get_names()
        assert names == ["macro_data", "spot_tick"]

    def test_clear(self, registry: DataContractRegistry) -> None:
        registry.clear()
        assert registry.count() == 0

    # ── Validation ────────────────────────────────────────────────────

    def test_validate_data_valid(self, registry: DataContractRegistry) -> None:
        data = {"ltp": 18500.0, "volume": 1000, "symbol": "NIFTY", "feed_type": "spot_tick", "timestamp": "2026-01-15T10:00:00"}
        errors = registry.validate_data("spot_tick", data)
        assert errors == []

    def test_validate_data_missing_field(self, registry: DataContractRegistry) -> None:
        data = {"ltp": 18500.0, "volume": 1000}
        errors = registry.validate_data("spot_tick", data)
        assert len(errors) == 3  # symbol, feed_type, timestamp missing

    def test_validate_data_type_mismatch(self, registry: DataContractRegistry) -> None:
        data = {"ltp": "invalid", "volume": 1000, "symbol": "NIFTY", "feed_type": "spot_tick", "timestamp": "2026-01-15T10:00:00"}
        errors = registry.validate_data("spot_tick", data)
        assert len(errors) == 1
        assert errors[0]["field"] == "ltp"
        assert "expected float" in errors[0]["message"].lower() or errors[0]["expected"] == "float"

    def test_validate_data_strict_extra_field(self, registry: DataContractRegistry) -> None:
        data = {"feed_type": "macro_data", "value": 14.5, "extra_field": "should_not_be_here"}
        errors = registry.validate_data_strict("macro_data", data)
        extra_errors = [e for e in errors if "unexpected" in e["message"].lower()]
        assert len(extra_errors) >= 1

    # ── Enforcement ───────────────────────────────────────────────────

    def test_enforce_passes(self, registry: DataContractRegistry) -> None:
        data = {"ltp": 18500.0, "volume": 1000, "symbol": "NIFTY", "feed_type": "spot_tick", "timestamp": "2026-01-15T10:00:00"}
        registry.enforce("spot_tick", data)  # Should not raise

    def test_enforce_raises_on_violation(self, registry: DataContractRegistry) -> None:
        data = {"ltp": 18500.0}
        with pytest.raises(ContractViolationError):
            registry.enforce("spot_tick", data)

    def test_enforce_strict_raises_on_extra(self, registry: DataContractRegistry) -> None:
        data = {"feed_type": "macro_data", "value": 14.5, "extra": True}
        with pytest.raises(ContractViolationError):
            registry.enforce_strict("macro_data", data)

    # ── Freshness ─────────────────────────────────────────────────────

    def test_check_freshness_within_limit(self, registry: DataContractRegistry) -> None:
        assert registry.check_freshness("spot_tick", 0.5) is True

    def test_check_freshness_exceeded(self, registry: DataContractRegistry) -> None:
        assert registry.check_freshness("spot_tick", 5.0) is False

    def test_check_freshness_unknown_contract(self, registry: DataContractRegistry) -> None:
        assert registry.check_freshness("unknown", 9999) is True

    # ── Source Check ──────────────────────────────────────────────────

    def test_check_source_expected(self, registry: DataContractRegistry) -> None:
        assert registry.check_source("spot_tick", "angel_one") is True

    def test_check_source_unexpected(self, registry: DataContractRegistry) -> None:
        assert registry.check_source("spot_tick", "unknown") is False

    def test_check_source_no_expectations(self) -> None:
        reg = DataContractRegistry()
        reg.register(FeedContract(name="test", ownership="test"))
        assert reg.check_source("test", "anything") is True

    # ── Report ────────────────────────────────────────────────────────

    def test_report_shape(self, registry: DataContractRegistry) -> None:
        report = registry.report()
        assert report["count"] == 2
        assert len(report["names"]) == 2
        assert report["major_count"] == 1
        assert report["minor_count"] == 1
        assert len(report["contracts"]) == 2


# =============================================================================
# RegistryLoader
# =============================================================================


class TestRegistryLoader:
    def test_load_defaults(self) -> None:
        registry = DataContractRegistry()
        loader = RegistryLoader(registry)
        count = loader.load_defaults()
        assert count >= 5
        assert registry.has("spot_tick")
        assert registry.has("options_snapshot")

    def test_load_minimal(self) -> None:
        registry = DataContractRegistry()
        loader = RegistryLoader(registry)
        count = loader.load_minimal()
        assert count == 2
        assert registry.has("spot_tick")
        assert registry.has("options_snapshot")

    def test_load_from_config(self) -> None:
        registry = DataContractRegistry()
        loader = RegistryLoader(registry)
        config = [
            {"name": "test_feed", "ownership": "Test", "data_class": "MINOR"},
            {"name": "test_feed_2", "ownership": "Test", "data_class": "MAJOR", "schema_fields": {"price": "float"}},
        ]
        count = loader.load_from_config(config)
        assert count == 2
        assert registry.has("test_feed")

    def test_load_from_config_missing_mandatory(self) -> None:
        registry = DataContractRegistry()
        loader = RegistryLoader(registry)
        config = [{"name": "test_feed"}]  # Missing "ownership"
        with pytest.raises(ContractViolationError):
            loader.load_from_config(config)

    def test_load_from_config_safe_skips_invalid(self) -> None:
        registry = DataContractRegistry()
        loader = RegistryLoader(registry)
        config = [
            {"name": "valid", "ownership": "Test", "data_class": "MINOR"},
            {"invalid": True},  # Missing mandatory fields
        ]
        count = loader.load_from_config_safe(config)
        assert count == 1

    def test_reload_defaults(self) -> None:
        registry = DataContractRegistry()
        loader = RegistryLoader(registry)
        loader.load_defaults()
        assert registry.count() >= 5
        loader.reload_defaults()
        assert registry.count() >= 5

    def test_registry_property(self) -> None:
        registry = DataContractRegistry()
        loader = RegistryLoader(registry)
        assert loader.registry is registry


# =============================================================================
# RuntimeContractChecks
# =============================================================================


class TestRuntimeContractChecks:
    @pytest.fixture
    def checks(self, registry: DataContractRegistry) -> RuntimeContractChecks:
        return RuntimeContractChecks(registry)

    def test_check_ingress_packet_valid(self, checks: RuntimeContractChecks) -> None:
        packet = {
            "feed_routing_identity": "SPOT_FEED",
            "minimal_source_envelope": {"feed_type": "spot_tick"},
            "original_raw_packet": {"ltp": 18500.0, "volume": 1000, "symbol": "NIFTY", "feed_type": "spot_tick", "timestamp": "2026-01-15T10:00:00"},
        }
        errors = checks.check_ingress_packet(packet)
        assert errors == []

    def test_check_ingress_packet_missing_fields(self, checks: RuntimeContractChecks) -> None:
        packet = {
            "feed_routing_identity": "SPOT_FEED",
            "minimal_source_envelope": {"feed_type": "spot_tick"},
            "original_raw_packet": {},
        }
        errors = checks.check_ingress_packet(packet)
        assert len(errors) >= 1

    def test_check_ingress_packet_no_routing(self, checks: RuntimeContractChecks) -> None:
        packet = {"minimal_source_envelope": {"feed_type": "spot_tick"}, "original_raw_packet": {}}
        errors = checks.check_ingress_packet(packet)
        routing_errors = [e for e in errors if "routing_identity" in str(e)]
        assert len(routing_errors) >= 1

    def test_check_raw_packet(self, checks: RuntimeContractChecks) -> None:
        record = {
            "feed_type": "spot_tick",
            "source": "angel_one",
            "original_raw_packet": {"ltp": 18500.0, "volume": 1000, "symbol": "NIFTY", "feed_type": "spot_tick", "timestamp": "2026-01-15T10:00:00"},
        }
        errors = checks.check_raw_packet(record)
        assert errors == []

    def test_check_raw_packet_invalid_source(self, checks: RuntimeContractChecks) -> None:
        record = {
            "feed_type": "spot_tick",
            "source": "unknown_source",
            "original_raw_packet": {"ltp": 18500.0, "volume": 1000, "symbol": "NIFTY", "feed_type": "spot_tick", "timestamp": "2026-01-15T10:00:00"},
        }
        errors = checks.check_raw_packet(record)
        source_errors = [e for e in errors if "source" in str(e)]
        assert len(source_errors) >= 1

    def test_check_cleaned_packet(self, checks: RuntimeContractChecks) -> None:
        entry = {
            "feed_type": "spot_tick",
            "cleaned_data": {"ltp": 18600.0, "volume": 500, "symbol": "NIFTY", "feed_type": "spot_tick", "timestamp": "2026-01-15T10:00:00"},
        }
        errors = checks.check_cleaned_packet(entry)
        assert errors == []

    def test_check_cleaned_packet_empty(self, checks: RuntimeContractChecks) -> None:
        errors = checks.check_cleaned_packet({})
        assert errors == []

    def test_check_structured_output_valid(self, checks: RuntimeContractChecks) -> None:
        entry = {
            "stream_type": "TICK_STREAM",
            "stream_data": {"ticks": []},
            "metadata": {"stream_id": "ts_001"},
        }
        errors = checks.check_structured_output(entry)
        assert errors == []

    def test_check_structured_output_missing_stream_id(self, checks: RuntimeContractChecks) -> None:
        entry = {
            "stream_type": "TICK_STREAM",
            "stream_data": {"ticks": []},
            "metadata": {},
        }
        errors = checks.check_structured_output(entry)
        stream_id_errors = [e for e in errors if "stream_id" in str(e)]
        assert len(stream_id_errors) >= 1

    def test_check_structured_output_no_stream_data(self, checks: RuntimeContractChecks) -> None:
        entry = {"stream_type": "TICK_STREAM", "metadata": {"stream_id": "ts_001"}}
        errors = checks.check_structured_output(entry)
        data_errors = [e for e in errors if "stream_data" in str(e)]
        assert len(data_errors) >= 1

    # ── Floor 3 Handoff ───────────────────────────────────────────────

    def test_enforce_floor3_handoff_valid(self, checks: RuntimeContractChecks) -> None:
        from datetime import datetime, timezone
        handoff = Floor3Handoff(
            validated_tick_stream=TickStream(tick_count=10, ticks=[]),
            validated_candle_streams=CandleStream(
                candles=[Candle(open=100.0, high=101.0, low=99.0, close=100.5, volume=1000)],
                source="test",
                feed_type="test",
            ),
            options_snapshots=OptionsSnapshotStream(
                snapshots=[OptionsSnapshot(strike=18500.0, option_type="CE", oi=100, premium=150.0, iv=15.0)],
                interval_minutes=5,
            ),
            session_packets=[SessionPacket(session_id="s1", timestamp=datetime.now(timezone.utc))],
            macro_support_packets=[MacroSupportStream(stream_id="ms1")],
            metadata_side_channel={"quality": "good"},
            computed_ready_hooks=[ComputedReadyHook(hook_name="test")],
        )
        checks.enforce_floor3_handoff(handoff)  # Should not raise

    def test_enforce_floor3_handoff_raises_on_empty(self, checks: RuntimeContractChecks) -> None:
        handoff = Floor3Handoff()
        with pytest.raises(ContractViolationError):
            checks.enforce_floor3_handoff(handoff)

    def test_check_floor3_handoff_issues(self, checks: RuntimeContractChecks) -> None:
        handoff = Floor3Handoff()
        issues = checks.check_floor3_handoff(handoff)
        assert len(issues) >= 4

    def test_registry_property(self, checks: RuntimeContractChecks, registry: DataContractRegistry) -> None:
        assert checks.registry is registry


# =============================================================================
# SourcePolicyRegistry
# =============================================================================


class TestSourcePolicyRegistry:
    def test_register_and_get_policy(self) -> None:
        reg = SourcePolicyRegistry()
        reg.register_source("angel_one", allowed_feeds={"spot_tick"})
        policy = reg.get_policy("angel_one")
        assert policy is not None
        assert policy.source == "angel_one"
        assert "spot_tick" in policy.allowed_feeds

    def test_register_with_defaults(self) -> None:
        reg = SourcePolicyRegistry()
        reg.register_source("manual")
        policy = reg.get_policy("manual")
        assert policy is not None
        assert policy.is_active is True

    def test_remove_source(self) -> None:
        reg = SourcePolicyRegistry()
        reg.register_source("test")
        assert reg.remove_source("test") is True
        assert reg.remove_source("test") is False

    def test_is_feed_allowed_unrestricted(self) -> None:
        reg = SourcePolicyRegistry()
        reg.register_source("angel_one")  # No restrictions
        assert reg.is_feed_allowed("angel_one", "spot_tick") is True

    def test_is_feed_allowed_restricted(self) -> None:
        reg = SourcePolicyRegistry()
        reg.register_source("manual", allowed_feeds={"calendar_event"})
        assert reg.is_feed_allowed("manual", "calendar_event") is True
        assert reg.is_feed_allowed("manual", "spot_tick") is False

    def test_is_feed_allowed_inactive_source(self) -> None:
        reg = SourcePolicyRegistry()
        reg.register_source("angel_one", is_active=False)
        assert reg.is_feed_allowed("angel_one", "spot_tick") is False

    def test_unregistered_source_is_active(self) -> None:
        reg = SourcePolicyRegistry()
        assert reg.is_source_active("angel_one") is True
        assert reg.is_feed_allowed("angel_one", "spot_tick") is True

    def test_get_validation_tier(self) -> None:
        reg = SourcePolicyRegistry()
        reg.register_source("angel_one")
        assert reg.get_validation_tier("angel_one", "spot_tick") == "A"
        assert reg.get_validation_tier("angel_one", "macro_data") == "C"

    def test_get_validation_tier_source_default(self) -> None:
        reg = SourcePolicyRegistry()
        reg.register_source("custom_source", default_validation_tier="B")
        assert reg.get_validation_tier("custom_source", "unknown_feed") == "B"

    def test_get_retention_class(self) -> None:
        reg = SourcePolicyRegistry()
        assert reg.get_retention_class("angel_one", "spot_tick") == "MAJOR"
        assert reg.get_retention_class("angel_one", "macro_data") == "MINOR"

    def test_list_sources(self) -> None:
        reg = SourcePolicyRegistry()
        reg.register_source("b_src")
        reg.register_source("a_src")
        assert reg.list_sources() == ["a_src", "b_src"]

    def test_count_sources(self) -> None:
        reg = SourcePolicyRegistry()
        assert reg.count_sources() == 0
        reg.register_source("test")
        assert reg.count_sources() == 1

    def test_report_sources(self) -> None:
        reg = SourcePolicyRegistry()
        reg.register_source("angel_one", allowed_feeds={"spot_tick"})
        report = reg.report_sources()
        assert report["total_sources"] == 1
        assert report["active_sources"] == 1


# =============================================================================
# RetentionPolicyRegistry
# =============================================================================


class TestRetentionPolicyRegistry:
    def test_default_major_ttl(self) -> None:
        reg = RetentionPolicyRegistry()
        assert reg.get_retention_s("spot_tick") == 7 * 24 * 3600

    def test_default_minor_ttl(self) -> None:
        reg = RetentionPolicyRegistry()
        assert reg.get_retention_s("macro_data") == 1 * 24 * 3600

    def test_unknown_feed_ttl(self) -> None:
        reg = RetentionPolicyRegistry()
        assert reg.get_retention_s("unknown_feed") > 0

    def test_set_policy_override(self) -> None:
        reg = RetentionPolicyRegistry()
        reg.set_policy("macro_data", 3600)
        assert reg.get_retention_s("macro_data") == 3600

    def test_set_policy_many(self) -> None:
        reg = RetentionPolicyRegistry()
        count = reg.set_policy_many({"feed_a": 100, "feed_b": 200})
        assert count == 2
        assert reg.get_retention_s("feed_a") == 100

    def test_remove_policy(self) -> None:
        reg = RetentionPolicyRegistry()
        reg.set_policy("macro_data", 3600)
        assert reg.get_retention_s("macro_data") == 3600
        reg.remove_policy("macro_data")
        assert reg.get_retention_s("macro_data") == 1 * 24 * 3600

    def test_has_override(self) -> None:
        reg = RetentionPolicyRegistry()
        assert reg.has_override("macro_data") is False
        reg.set_policy("macro_data", 3600)
        assert reg.has_override("macro_data") is True

    def test_list_overrides(self) -> None:
        reg = RetentionPolicyRegistry()
        reg.set_policy("feed_a", 100)
        reg.set_policy("feed_b", 200)
        overrides = reg.list_overrides()
        assert overrides == {"feed_a": 100, "feed_b": 200}

    def test_get_data_class_ttl(self) -> None:
        reg = RetentionPolicyRegistry()
        assert reg.get_data_class_ttl("MAJOR") == 7 * 24 * 3600
        assert reg.get_data_class_ttl("MINOR") == 1 * 24 * 3600

    def test_clear_policies(self) -> None:
        reg = RetentionPolicyRegistry()
        reg.set_policy("macro_data", 3600)
        reg.clear_policies()
        assert reg.has_override("macro_data") is False

    def test_get_retention_timedelta(self) -> None:
        reg = RetentionPolicyRegistry()
        from datetime import timedelta
        td = reg.get_retention_timedelta("spot_tick")
        assert td == timedelta(days=7)

    def test_get_retention_display(self) -> None:
        reg = RetentionPolicyRegistry()
        assert "day" in reg.get_retention_display("spot_tick")

    def test_report_policies(self) -> None:
        reg = RetentionPolicyRegistry()
        reg.set_policy("macro_data", 3600)
        report = reg.report_policies()
        assert report["default_major_s"] == 7 * 24 * 3600
        assert report["override_count"] == 1

    def test_report_feed_retention(self) -> None:
        reg = RetentionPolicyRegistry()
        report = reg.report_feed_retention("spot_tick")
        assert report["feed_type"] == "spot_tick"
        assert report["retention_s"] == 7 * 24 * 3600
        assert "dataclass" in report["source"]
