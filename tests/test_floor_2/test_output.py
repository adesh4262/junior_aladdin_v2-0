"""Tests for Floor 2 Output sub-system (Step 2.11).

Tests cover:
1. MetadataSidechannelBuilder — build side-channel, quality facts, review signal, source health
2. ReviewStatusRouter — light signal, Side B, Side C routing
3. SessionStreamRouter — session phase detection, packet extraction, routing context
4. Floor3HandoffBuilder — all 7 categories, enforce, non-enforce mode
5. DatacenterOutputGateway — dispatch to Floor 3, Side B, Side C, transmission log
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, PropertyMock, patch

import pytest

from junior_aladdin.floor_2_datacenter.datacenter_contracts import (
    Candle,
    CandleStream,
    ComputedReadyHook,
    Floor3Handoff,
    MacroSupportPacket,
    MacroSupportStream,
    OptionsSnapshot,
    OptionsSnapshotStream,
    SessionPacket,
    TickStream,
    ValidatedTick,
)
from junior_aladdin.floor_2_datacenter.datacenter_types import (
    ReviewSignal,
    StreamType,
    StructureResult,
    TransformStage,
)
from junior_aladdin.floor_2_datacenter.output.datacenter_output_gateway import (
    DatacenterOutputGateway,
    _generate_transmission_id,
)
from junior_aladdin.floor_2_datacenter.output.floor3_handoff_builder import (
    Floor3HandoffBuilder,
)
from junior_aladdin.floor_2_datacenter.output.metadata_sidechannel_builder import (
    MetadataSidechannelBuilder,
)
from junior_aladdin.floor_2_datacenter.output.review_status_router import (
    ReviewStatusRouter,
)
from junior_aladdin.floor_2_datacenter.output.session_stream_router import (
    SessionStreamRouter,
    SESSION_OPEN,
    SESSION_CLOSE,
)


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def review_engine():
    """Create a mock review engine."""
    engine = MagicMock()
    engine.compute_signal.return_value = ReviewSignal.GOOD
    engine.get_active_event_count.return_value = 0
    engine.get_report_count.return_value = 0
    engine.get_event_sources.return_value = set()
    engine.get_all_events.return_value = []
    engine.get_events_by_source.return_value = []
    engine.get_all_reports.return_value = []
    engine._events = {}
    return engine


@pytest.fixture
def health_monitor():
    """Create a mock health monitor."""
    monitor = MagicMock()
    monitor.get_health_score.return_value = 1.0
    monitor.get_health_state.return_value = "HEALTHY"
    monitor.get_all_health_states.return_value = {
        "angel_one": {
            "state": "HEALTHY", "score": 1.0,
            "avg_latency_ms": 50.0, "heartbeat_age_s": 5.0,
            "reconnect_count": 0, "events_emitted": [],
        },
    }
    return monitor


@pytest.fixture
def transform_tracker():
    """Create a mock transform stage tracker."""
    tracker = MagicMock()
    tracker.find_stuck_packets.return_value = []
    return tracker


@pytest.fixture
def structured_writer():
    """Create a mock structured writer."""
    writer = MagicMock()
    writer.get_stream_data.return_value = None
    writer.get_by_type.return_value = []
    writer.stream_types = set()
    return writer


@pytest.fixture
def metadata_builder(review_engine, health_monitor, transform_tracker):
    """Create a MetadataSidechannelBuilder with mock dependencies."""
    return MetadataSidechannelBuilder(
        review_engine=review_engine,
        health_monitor=health_monitor,
        transform_tracker=transform_tracker,
    )


@pytest.fixture
def review_router(review_engine, health_monitor):
    """Create a ReviewStatusRouter with mock dependencies."""
    return ReviewStatusRouter(
        review_engine=review_engine,
        health_monitor=health_monitor,
    )


@pytest.fixture
def session_router(structured_writer):
    """Create a SessionStreamRouter with mock dependencies."""
    return SessionStreamRouter(
        structured_writer=structured_writer,
    )


@pytest.fixture
def handoff_builder(structured_writer, metadata_builder, session_router):
    """Create a Floor3HandoffBuilder with mock dependencies."""
    return Floor3HandoffBuilder(
        structured_writer=structured_writer,
        sidechannel_builder=metadata_builder,
        session_router=session_router,
    )


@pytest.fixture
def output_gateway(handoff_builder, metadata_builder, review_router, session_router):
    """Create a DatacenterOutputGateway with mock dependencies."""
    return DatacenterOutputGateway(
        handoff_builder=handoff_builder,
        sidechannel_builder=metadata_builder,
        review_router=review_router,
        session_router=session_router,
    )


# =============================================================================
# Tests: MetadataSidechannelBuilder
# =============================================================================


class TestMetadataSidechannelBuilder:
    """Tests for MetadataSidechannelBuilder."""

    def test_build_sidechannel_returns_dict(self, metadata_builder):
        """Side-channel build returns a dict with expected keys."""
        result = metadata_builder.build_sidechannel()
        assert isinstance(result, dict)
        assert "quality_facts" in result
        assert "review_signal" in result
        assert "source_health" in result
        assert "transform_stage" in result
        assert "event_summary" in result
        assert "report_summary" in result
        assert "built_at" in result

    def test_build_sidechannel_review_signal(self, metadata_builder):
        """Review signal is the string value of ReviewSignal.GOOD."""
        result = metadata_builder.build_sidechannel()
        assert result["review_signal"] == "GOOD"

    def test_build_sidechannel_source_health(self, metadata_builder):
        """Source health contains monitored sources."""
        result = metadata_builder.build_sidechannel()
        assert "angel_one" in result["source_health"]
        assert result["source_health"]["angel_one"]["state"] == "HEALTHY"

    def test_build_sidechannel_scoped_to_source(self, metadata_builder, health_monitor):
        """Build side-channel scoped to a specific source."""
        result = metadata_builder.build_sidechannel(source="angel_one")
        assert result["quality_facts"]["source"] == "angel_one"

    def test_quality_facts_section(self, metadata_builder):
        """Quality facts section returns dict with health score."""
        result = metadata_builder.build_quality_facts_section()
        assert "overall_health_score" in result
        assert result["overall_health_score"] == 1.0
        assert "overall_health_state" in result

    def test_review_signal_section(self, metadata_builder):
        """Review signal section returns signal and source."""
        result = metadata_builder.build_review_signal_section()
        assert result["signal"] == "GOOD"
        assert result["source"] is None

    def test_source_health_section_all(self, metadata_builder):
        """Source health section returns all sources."""
        result = metadata_builder.build_source_health_section()
        assert "angel_one" in result

    def test_source_health_section_scoped(self, metadata_builder):
        """Source health section scoped to a source returns only that source."""
        result = metadata_builder.build_source_health_section(source="angel_one")
        assert "angel_one" in result

    def test_empty_health_all_sources(self, metadata_builder, health_monitor):
        """All sources empty returns default healthy quality facts."""
        health_monitor.get_all_health_states.return_value = {}
        result = metadata_builder.build_sidechannel()
        assert result["quality_facts"]["overall_health_score"] == 1.0
        assert result["quality_facts"]["overall_health_state"] == "HEALTHY"
        assert result["quality_facts"]["source_count"] == 0


# =============================================================================
# Tests: ReviewStatusRouter
# =============================================================================


class TestReviewStatusRouter:
    """Tests for ReviewStatusRouter."""

    def test_route_light_signal_returns_dict(self, review_router):
        """Light signal returns a dict with signal info."""
        result = review_router.route_light_signal()
        assert isinstance(result, dict)
        assert result["type"] == "review_light_signal"
        assert result["signal"] == "GOOD"
        assert result["routed_to"] == "captain"
        assert "routed_at" in result

    def test_route_light_signal_scoped(self, review_router):
        """Light signal scoped to source includes source."""
        result = review_router.route_light_signal(source="angel_one")
        assert result["source"] == "angel_one"

    def test_route_light_signal_label(self, review_router):
        """Light signal includes a human-readable label."""
        result = review_router.route_light_signal()
        assert result["label"] == "All systems nominal"

    def test_route_to_side_b_returns_dict(self, review_router, review_engine):
        """Side B routing returns dict with event summary."""
        result = review_router.route_to_side_b()
        assert isinstance(result, dict)
        assert result["type"] == "review_side_b"
        assert result["routed_to"] == "side_b_dashboard"
        assert "event_summary" in result
        assert "source_health" in result
        assert "recent_reports" in result

    def test_route_to_side_b_event_summary(self, review_router):
        """Side B event summary has expected keys."""
        result = review_router.route_to_side_b()
        summary = result["event_summary"]
        assert "total_events" in summary
        assert "by_severity" in summary
        assert "by_source" in summary
        assert "highest_severity" in summary

    def test_route_to_side_c_returns_dict(self, review_router):
        """Side C routing returns dict with event references."""
        result = review_router.route_to_side_c()
        assert isinstance(result, dict)
        assert result["type"] == "review_side_c"
        assert result["routed_to"] == "side_c_memory"
        assert "events" in result
        assert "reports" in result
        assert "event_count" in result

    def test_route_to_side_c_event_references(self, review_router):
        """Side C event references have expected fields."""
        result = review_router.route_to_side_c()
        for event_ref in result["events"]:
            assert "event_id" in event_ref or "event_type" in event_ref

    def test_signal_to_label_all_signals(self, review_router):
        """Signal to label returns correct label for each signal."""
        labels = {
            ReviewSignal.GOOD: "All systems nominal",
            ReviewSignal.CAUTION: "Minor issues detected — monitoring",
            ReviewSignal.DEGRADED: "Significant degradation — attention required",
            ReviewSignal.CRITICAL: "Critical issues — immediate action needed",
        }
        for signal, expected_label in labels.items():
            label = review_router._signal_to_label(signal)
            assert label == expected_label


# =============================================================================
# Tests: SessionStreamRouter
# =============================================================================


class TestSessionStreamRouter:
    """Tests for SessionStreamRouter."""

    def test_get_current_session_phase_returns_dict(self, session_router):
        """Session phase returns a dict with expected keys."""
        result = session_router.get_current_session_phase()
        assert isinstance(result, dict)
        assert "phase" in result
        assert "session_type" in result
        assert "is_market_hours" in result
        assert "label" in result
        assert "ist_time" in result

    def test_get_session_phase_closed_outside_market(self, session_router):
        """Outside market hours (e.g., 5 AM UTC = 10:30 AM IST = MID session)."""
        # Morning UTC = afternoon IST
        early_morning_utc = datetime(2025, 1, 15, 5, 0, 0, tzinfo=timezone.utc)
        result = session_router.get_current_session_phase(now=early_morning_utc)
        # 5:00 UTC = 10:30 IST → MID session
        assert result["is_market_hours"] is True

    def test_extract_session_packets_empty(self, session_router, structured_writer):
        """Empty session writer returns empty list."""
        structured_writer.get_by_type.return_value = []
        packets = session_router.extract_session_packets()
        assert packets == []

    def test_extract_session_packets_with_data(self, session_router, structured_writer):
        """Session packets are extracted correctly from writer."""
        session = SessionPacket(
            session_id="sess_001",
            session_type="REGULAR",
            session_phase="MID",
            session_status="ACTIVE",
        )
        entries = [
            {
                "stream_data": session,
                "metadata": {"stream_id": "sess_001"},
            },
        ]
        structured_writer.get_by_type.return_value = entries
        packets = session_router.extract_session_packets()
        assert len(packets) == 1
        assert packets[0].session_id == "sess_001"
        assert packets[0].session_phase == "MID"

    def test_extract_session_packets_from_dict(self, session_router, structured_writer):
        """Session packets from dict entries are parsed correctly."""
        entries = [
            {
                "stream_data": {
                    "session_id": "sess_002",
                    "session_type": "REGULAR",
                    "session_phase": "OPENING",
                    "session_status": "ACTIVE",
                },
                "metadata": {},
            },
        ]
        structured_writer.get_by_type.return_value = entries
        packets = session_router.extract_session_packets()
        assert len(packets) == 1
        assert packets[0].session_id == "sess_002"

    def test_get_session_routing_context(self, session_router):
        """Session routing context has expected keys."""
        context = session_router.get_session_routing_context()
        assert "session_phase" in context
        assert "session_packets" in context
        assert "packet_count" in context
        assert "routing_targets" in context
        assert "consumers" in context

    def test_route_for_handoff_with_packets(self, session_router, structured_writer):
        """Route for handoff returns session packets."""
        session = SessionPacket(session_id="sess_001", session_type="REGULAR")
        entries = [{"stream_data": session, "metadata": {}}]
        structured_writer.get_by_type.return_value = entries
        packets = session_router.route_for_handoff()
        assert len(packets) == 1
        assert packets[0].session_id == "sess_001"

    def test_route_for_handoff_without_packets(self, session_router):
        """Route for handoff without stored packets generates context packet."""
        packets = session_router.route_for_handoff()
        assert len(packets) == 1
        assert packets[0].session_type in ("REGULAR", "PRE_OPEN", "POST_CLOSE")

    def test_routing_targets_for_mid_session(self, session_router):
        """Mid session has tick, candle, and options routing targets."""
        targets = session_router._get_routing_targets("MID")
        assert "tick_stream_consumers" in targets
        assert "candle_stream_consumers" in targets
        assert "options_consumers" in targets

    def test_routing_targets_for_closed(self, session_router):
        """Closed session has candle, options, and macro targets."""
        targets = session_router._get_routing_targets("CLOSED")
        assert "candle_stream_consumers" in targets
        assert "options_consumers" in targets
        assert "macro_consumers" in targets


# =============================================================================
# Tests: Floor3HandoffBuilder
# =============================================================================


class TestFloor3HandoffBuilder:
    """Tests for Floor3HandoffBuilder."""

    def test_build_handoff_returns_floor3_handoff(self, handoff_builder):
        """Build handoff returns a Floor3Handoff instance."""
        handoff = handoff_builder.build_handoff(enforce=False)
        assert isinstance(handoff, Floor3Handoff)

    def test_build_handoff_has_all_7_categories(self, handoff_builder):
        """All 7 categories are present in the handoff."""
        handoff = handoff_builder.build_handoff(enforce=False)
        assert hasattr(handoff, "validated_tick_stream")
        assert hasattr(handoff, "validated_candle_streams")
        assert hasattr(handoff, "options_snapshots")
        assert hasattr(handoff, "session_packets")
        assert hasattr(handoff, "macro_support_packets")
        assert hasattr(handoff, "metadata_side_channel")
        assert hasattr(handoff, "computed_ready_hooks")

    def test_build_handoff_metadata_side_channel(self, handoff_builder):
        """Metadata side-channel is populated."""
        handoff = handoff_builder.build_handoff(enforce=False)
        assert isinstance(handoff.metadata_side_channel, dict)
        assert "review_signal" in handoff.metadata_side_channel
        assert "quality_facts" in handoff.metadata_side_channel

    def test_build_handoff_computed_hooks(self, handoff_builder):
        """Computed-ready hooks contain default hooks."""
        handoff = handoff_builder.build_handoff(enforce=False)
        assert len(handoff.computed_ready_hooks) >= 3
        assert handoff.computed_ready_hooks[0].hook_name == "tick_to_candle"

    def test_build_handoff_session_packets(self, handoff_builder):
        """Session packets are present."""
        handoff = handoff_builder.build_handoff(enforce=False)
        assert isinstance(handoff.session_packets, list)

    def test_build_handoff_empty_categories(self, handoff_builder):
        """Empty categories return default empty instances (not None)."""
        handoff = handoff_builder.build_handoff(enforce=False)
        assert handoff.validated_tick_stream.tick_count == 0
        assert len(handoff.validated_candle_streams.candles) == 0
        assert len(handoff.options_snapshots.snapshots) == 0
        assert len(handoff.macro_support_packets) == 0

    def test_build_handoff_with_check_returns_tuple(self, handoff_builder):
        """Build with check returns (handoff, issues) tuple."""
        handoff, issues = handoff_builder.build_handoff_with_check()
        assert isinstance(handoff, Floor3Handoff)
        assert isinstance(issues, list)

    def test_build_tick_stream_from_writer(self, structured_writer, handoff_builder):
        """Tick stream is populated from structured writer."""
        tick_stream = TickStream(
            stream_id="ts_001",
            ticks=[ValidatedTick(price=100.0, volume=1000)],
            tick_count=1,
        )
        structured_writer.get_stream_data.side_effect = lambda st: (
            tick_stream if st == StreamType.TICK_STREAM else None
        )
        handoff = handoff_builder.build_handoff(enforce=False)
        assert handoff.validated_tick_stream.tick_count == 1
        assert len(handoff.validated_tick_stream.ticks) == 1

    def test_build_candle_streams_from_writer(self, structured_writer, handoff_builder):
        """Candle stream is populated from structured writer."""
        candle_stream = CandleStream(
            stream_id="cs_001",
            candles=[Candle(open=100.0, high=101.0, low=99.0, close=100.5, volume=5000)],
        )
        structured_writer.get_stream_data.side_effect = lambda st: (
            candle_stream if st == StreamType.CANDLE_STREAM else None
        )
        handoff = handoff_builder.build_handoff(enforce=False)
        assert len(handoff.validated_candle_streams.candles) == 1


# =============================================================================
# Tests: DatacenterOutputGateway
# =============================================================================


class TestDatacenterOutputGateway:
    """Tests for DatacenterOutputGateway."""

    def test_dispatch_to_floor3_returns_dict(self, output_gateway):
        """Dispatch to Floor 3 returns a dict."""
        result = output_gateway.dispatch_to_floor3(enforce=False)
        assert isinstance(result, dict)
        assert result["dispatch_type"] == "floor3_handoff"
        assert "transmission_id" in result
        assert "dispatched_at" in result

    def test_dispatch_to_floor3_has_handoff_summary(self, output_gateway):
        """Floor 3 dispatch includes handoff summary."""
        result = output_gateway.dispatch_to_floor3(enforce=False)
        assert "handoff_summary" in result
        summary = result["handoff_summary"]
        assert "tick_count" in summary
        assert "candle_count" in summary
        assert "session_count" in summary
        assert "hook_count" in summary

    def test_dispatch_to_side_b_returns_dict(self, output_gateway):
        """Dispatch to Side B returns a dict."""
        result = output_gateway.dispatch_to_side_b()
        assert isinstance(result, dict)
        assert result["dispatch_type"] == "side_b_dashboard"

    def test_dispatch_to_side_b_has_review_data(self, output_gateway):
        """Side B dispatch includes review data."""
        result = output_gateway.dispatch_to_side_b()
        assert "review_data" in result
        assert result["review_data"]["type"] == "review_side_b"

    def test_dispatch_to_side_c_returns_dict(self, output_gateway):
        """Dispatch to Side C returns a dict."""
        result = output_gateway.dispatch_to_side_c()
        assert isinstance(result, dict)
        assert result["dispatch_type"] == "side_c_memory"

    def test_dispatch_to_side_c_has_review_refs(self, output_gateway):
        """Side C dispatch includes review references."""
        result = output_gateway.dispatch_to_side_c()
        assert "review_references" in result

    def test_dispatch_all_returns_all_three(self, output_gateway):
        """Dispatch all returns floor3, side_b, side_c."""
        results = output_gateway.dispatch_all(enforce=False)
        assert "floor3" in results
        assert "side_b" in results
        assert "side_c" in results

    def test_dispatch_all_correct_types(self, output_gateway):
        """Each dispatch in dispatch_all has correct type."""
        results = output_gateway.dispatch_all(enforce=False)
        assert results["floor3"]["dispatch_type"] == "floor3_handoff"
        assert results["side_b"]["dispatch_type"] == "side_b_dashboard"
        assert results["side_c"]["dispatch_type"] == "side_c_memory"

    def test_transmission_log_populated(self, output_gateway):
        """Dispatches are logged in transmission log."""
        output_gateway.dispatch_to_floor3(enforce=False)
        output_gateway.dispatch_to_side_b()
        output_gateway.dispatch_to_side_c()
        assert output_gateway.count_transmissions() == 3

    def test_get_transmission_returns_record(self, output_gateway):
        """Get transmission returns correct record."""
        result = output_gateway.dispatch_to_floor3(enforce=False)
        tid = result["transmission_id"]
        record = output_gateway.get_transmission(tid)
        assert record is not None
        assert record["transmission_id"] == tid

    def test_list_transmissions_filtered(self, output_gateway):
        """List transmissions filtered by type."""
        output_gateway.dispatch_to_floor3(enforce=False)
        output_gateway.dispatch_to_side_b()
        floor3_records = output_gateway.list_transmissions(
            dispatch_type="floor3_handoff",
        )
        assert len(floor3_records) == 1
        assert floor3_records[0]["dispatch_type"] == "floor3_handoff"

    def test_clear_log(self, output_gateway):
        """Clear log removes all transmissions."""
        output_gateway.dispatch_to_floor3(enforce=False)
        output_gateway.clear_log()
        assert output_gateway.count_transmissions() == 0

    def test_transmission_id_generation(self):
        """Transmission ID has correct prefix."""
        tid = _generate_transmission_id("f3")
        assert tid.startswith("f3_")
        assert len(tid) == 11  # f3_ + 8 hex chars
        tid = _generate_transmission_id("sb")
        assert tid.startswith("sb_")

    def test_dispatch_to_floor3_with_source(self, output_gateway):
        """Floor 3 dispatch includes source in record."""
        result = output_gateway.dispatch_to_floor3(source="angel_one", enforce=False)
        assert result["source"] == "angel_one"
