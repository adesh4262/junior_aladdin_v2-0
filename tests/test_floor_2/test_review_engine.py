"""Tests for Floor 2 Review Engine sub-system (Step 2.8).

Tests cover:
- ReviewEngine: event emission, signal computation, review status, audits
- HealthMonitor: latency/heartbeat/reconnect tracking, state transitions, scoring
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from junior_aladdin.floor_2_datacenter.datacenter_types import (
    AuditReport,
    HealthEvent,
    ReviewSignal,
)
from junior_aladdin.floor_2_datacenter.review.health_monitor import (
    CRITICAL,
    DEGRADED,
    HEALTHY,
    HealthMonitor,
)
from junior_aladdin.floor_2_datacenter.review.review_engine import ReviewEngine


# =============================================================================
# ReviewEngine Tests
# =============================================================================


class TestReviewEngine:
    @pytest.fixture
    def engine(self) -> ReviewEngine:
        return ReviewEngine()

    # ── Event Emission ─────────────────────────────────────────────────

    def test_emit_event(self, engine: ReviewEngine) -> None:
        eid = engine.emit_event("latency_spike", "SEVERE", "angel_one",
                                "Latency exceeded 500ms")
        assert len(eid) > 0
        assert "latency_spike" in eid
        assert "angel_one" in eid

    def test_emit_event_invalid_severity(self, engine: ReviewEngine) -> None:
        with pytest.raises(ValueError, match="Unknown severity"):
            engine.emit_event("test", "INVALID", "source", "msg")

    def test_emit_event_caution(self, engine: ReviewEngine) -> None:
        eid = engine.emit_event("minor_issue", "CAUTION", "angel_one",
                                "Slight delay")
        event = engine.get_event(eid)
        assert event is not None
        assert event.severity == "CAUTION"

    def test_emit_event_critical(self, engine: ReviewEngine) -> None:
        eid = engine.emit_event("connection_lost", "CRITICAL", "angel_one",
                                "Connection dropped")
        event = engine.get_event(eid)
        assert event is not None
        assert event.severity == "CRITICAL"

    def test_emit_event_with_details(self, engine: ReviewEngine) -> None:
        eid = engine.emit_event("latency_spike", "SEVERE", "angel_one",
                                "High latency",
                                details={"latency_ms": 600.0})
        event = engine.get_event(eid)
        assert event is not None
        assert event.details.get("latency_ms") == 600.0

    def test_get_event_nonexistent(self, engine: ReviewEngine) -> None:
        assert engine.get_event("nonexistent") is None

    def test_get_events_by_source(self, engine: ReviewEngine) -> None:
        engine.emit_event("event_a", "CAUTION", "source_a", "msg a")
        engine.emit_event("event_b", "SEVERE", "source_a", "msg b")
        engine.emit_event("event_c", "CAUTION", "source_b", "msg c")

        events_a = engine.get_events_by_source("source_a")
        assert len(events_a) == 2

        events_b = engine.get_events_by_source("source_b")
        assert len(events_b) == 1

    def test_get_all_events(self, engine: ReviewEngine) -> None:
        engine.emit_event("e1", "CAUTION", "src1", "msg1")
        engine.emit_event("e2", "SEVERE", "src2", "msg2")
        all_events = engine.get_all_events()
        assert len(all_events) == 2

    def test_clear_events_all(self, engine: ReviewEngine) -> None:
        engine.emit_event("e1", "CAUTION", "src1", "msg1")
        engine.emit_event("e2", "SEVERE", "src2", "msg2")
        assert engine.clear_events() == 2
        assert engine.get_active_event_count() == 0

    def test_clear_events_by_source(self, engine: ReviewEngine) -> None:
        engine.emit_event("e1", "CAUTION", "src1", "msg1")
        engine.emit_event("e2", "SEVERE", "src1", "msg2")
        engine.emit_event("e3", "CAUTION", "src2", "msg3")
        assert engine.clear_events(source="src1") == 2
        assert engine.get_active_event_count() == 1

    def test_get_event_sources(self, engine: ReviewEngine) -> None:
        engine.emit_event("e1", "CAUTION", "src1", "msg1")
        engine.emit_event("e2", "SEVERE", "src2", "msg2")
        sources = engine.get_event_sources()
        assert sources == {"src1", "src2"}

    # ── Review Signal ──────────────────────────────────────────────────

    def test_signal_good_no_events(self, engine: ReviewEngine) -> None:
        assert engine.compute_signal() == ReviewSignal.GOOD
        assert engine.compute_signal("angel_one") == ReviewSignal.GOOD

    def test_signal_caution_one_event(self, engine: ReviewEngine) -> None:
        engine.emit_event("minor", "CAUTION", "angel_one", "msg")
        assert engine.compute_signal("angel_one") == ReviewSignal.CAUTION

    def test_signal_caution_aggregated(self, engine: ReviewEngine) -> None:
        engine.emit_event("e1", "CAUTION", "src1", "msg1")
        assert engine.compute_signal() == ReviewSignal.CAUTION

    def test_signal_degraded_critical_event(self, engine: ReviewEngine) -> None:
        engine.emit_event("critical", "CRITICAL", "angel_one", "msg")
        assert engine.compute_signal("angel_one") == ReviewSignal.DEGRADED

    def test_signal_critical_two_critical_events(self, engine: ReviewEngine) -> None:
        engine.emit_event("c1", "CRITICAL", "src1", "msg1")
        engine.emit_event("c2", "CRITICAL", "src2", "msg2")
        assert engine.compute_signal() == ReviewSignal.CRITICAL

    def test_signal_critical_weight_threshold(self, engine: ReviewEngine) -> None:
        """5 CAUTION events (weight 1 each) should reach CRITICAL threshold."""
        for i in range(5):
            engine.emit_event(f"e{i}", "CAUTION", f"src{i}", f"msg{i}")
        assert engine.compute_signal() == ReviewSignal.CRITICAL

    def test_signal_degraded_weight_threshold(self, engine: ReviewEngine) -> None:
        """3 CAUTION events (weight 1 each) should reach DEGRADED threshold."""
        for i in range(3):
            engine.emit_event(f"e{i}", "CAUTION", f"src{i}", f"msg{i}")
        assert engine.compute_signal() == ReviewSignal.DEGRADED

    def test_signal_source_specific(self, engine: ReviewEngine) -> None:
        engine.emit_event("e1", "CRITICAL", "angel_one", "msg1")
        engine.emit_event("e2", "CAUTION", "other", "msg2")
        assert engine.compute_signal("angel_one") == ReviewSignal.DEGRADED
        assert engine.compute_signal("other") == ReviewSignal.CAUTION

    # ── Review Status ──────────────────────────────────────────────────

    def test_set_and_get_review_status(self, engine: ReviewEngine) -> None:
        engine.set_review_status("angel_one", "IN_REVIEW")
        assert engine.get_review_status("angel_one") == "IN_REVIEW"

    def test_get_review_status_not_set(self, engine: ReviewEngine) -> None:
        assert engine.get_review_status("nonexistent") is None

    def test_get_all_review_statuses(self, engine: ReviewEngine) -> None:
        engine.set_review_status("src1", "PENDING")
        engine.set_review_status("src2", "CLEARED")
        statuses = engine.get_all_review_statuses()
        assert statuses == {"src1": "PENDING", "src2": "CLEARED"}

    # ── Audit Reports ──────────────────────────────────────────────────

    def test_run_scheduled_audit_no_events(self, engine: ReviewEngine) -> None:
        report = engine.run_scheduled_audit()
        assert isinstance(report, AuditReport)
        assert report.report_type == "SCHEDULED"
        assert report.score == 1.0
        assert len(report.findings) == 0

    def test_run_scheduled_audit_with_events(self, engine: ReviewEngine) -> None:
        engine.emit_event("latency", "SEVERE", "angel_one", "High latency")
        report = engine.run_scheduled_audit()
        assert len(report.findings) == 1
        assert report.score < 1.0

    def test_run_scheduled_audit_source_scoped(self, engine: ReviewEngine) -> None:
        engine.emit_event("e1", "SEVERE", "src1", "msg1")
        engine.emit_event("e2", "CAUTION", "src2", "msg2")
        report = engine.run_scheduled_audit(scope={"source": "src1"})
        assert len(report.findings) == 1
        assert report.findings[0]["source"] == "src1"

    def test_run_investigation_by_source(self, engine: ReviewEngine) -> None:
        engine.emit_event("e1", "SEVERE", "src1", "msg1")
        engine.emit_event("e2", "CAUTION", "src2", "msg2")
        report = engine.run_investigation(source="src1")
        assert len(report.findings) == 1
        assert report.report_type == "INVESTIGATION"

    def test_run_investigation_by_event_type(self, engine: ReviewEngine) -> None:
        engine.emit_event("latency", "SEVERE", "src1", "msg1")
        engine.emit_event("heartbeat", "CAUTION", "src1", "msg2")
        report = engine.run_investigation(event_type="latency")
        assert len(report.findings) == 1
        assert report.findings[0]["event_type"] == "latency"

    def test_run_investigation_by_both(self, engine: ReviewEngine) -> None:
        engine.emit_event("latency", "SEVERE", "src1", "msg1")
        engine.emit_event("latency", "CAUTION", "src2", "msg2")
        engine.emit_event("heartbeat", "SEVERE", "src1", "msg3")
        report = engine.run_investigation(source="src1", event_type="latency")
        assert len(report.findings) == 1

    def test_run_investigation_no_matches(self, engine: ReviewEngine) -> None:
        engine.emit_event("latency", "SEVERE", "src1", "msg1")
        report = engine.run_investigation(source="nonexistent")
        assert len(report.findings) == 0
        assert report.score == 1.0

    def test_get_report(self, engine: ReviewEngine) -> None:
        report = engine.run_scheduled_audit()
        retrieved = engine.get_report(report.report_id)
        assert retrieved is not None
        assert retrieved.report_id == report.report_id

    def test_get_report_nonexistent(self, engine: ReviewEngine) -> None:
        assert engine.get_report("nonexistent") is None

    def test_get_all_reports(self, engine: ReviewEngine) -> None:
        engine.run_scheduled_audit()
        engine.run_investigation(source="test")
        assert engine.get_report_count() == 2
        assert len(engine.get_all_reports()) == 2

    def test_reset(self, engine: ReviewEngine) -> None:
        engine.emit_event("e1", "SEVERE", "src1", "msg1")
        engine.set_review_status("src1", "PENDING")
        engine.run_scheduled_audit()
        engine.reset()
        assert engine.get_active_event_count() == 0
        assert engine.get_report_count() == 0
        assert engine.get_all_review_statuses() == {}
        assert engine.get_event_sources() == set()


# =============================================================================
# HealthMonitor Tests
# =============================================================================
#
# Scoring model:
#   HEALTHY: score >= 0.7
#   DEGRADED: 0.4 <= score < 0.7
#   CRITICAL: score < 0.4
#
# Penalties:
#   Latency > 500ms:     -0.4    (score 0.6 → DEGRADED)
#   Latency > 200ms:     -0.2    (score 0.8 → HEALTHY)
#   Heartbeat age > 120s: -0.3  (score 0.7 → HEALTHY edge)
#   Heartbeat age > 30s:  -0.15 (score 0.85 → HEALTHY)
#   Reconnect >= 3:       -0.3  (score 0.7 → HEALTHY edge)
#   Reconnect = 1:        -0.1  (score 0.9 → HEALTHY)


class TestHealthMonitor:
    @pytest.fixture
    def engine(self) -> ReviewEngine:
        return ReviewEngine()

    @pytest.fixture
    def monitor(self, engine: ReviewEngine) -> HealthMonitor:
        return HealthMonitor(engine)

    # ── Latency ────────────────────────────────────────────────────────

    def test_record_latency_healthy(self, monitor: HealthMonitor) -> None:
        """50ms latency is well below threshold — stays HEALTHY."""
        monitor.record_latency("angel_one", 50.0)
        assert monitor.get_health_state("angel_one") == HEALTHY

    def test_record_latency_warning_stays_healthy(self, monitor: HealthMonitor) -> None:
        """250ms latency triggers warning event but only -0.2 → score 0.8 → HEALTHY."""
        monitor.record_latency("angel_one", 250.0)
        assert monitor.get_health_state("angel_one") == HEALTHY

    def test_record_latency_high_is_degraded(self, monitor: HealthMonitor) -> None:
        """600ms latency exceeds 500ms critical threshold: -0.4 → score 0.6 → DEGRADED."""
        monitor.record_latency("angel_one", 600.0)
        assert monitor.get_health_state("angel_one") == DEGRADED

    def test_latency_emits_warning_event(
        self, monitor: HealthMonitor, engine: ReviewEngine,
    ) -> None:
        monitor.record_latency("angel_one", 250.0)
        events = engine.get_events_by_source("angel_one")
        event_types = [e.event_type for e in events]
        assert "latency_warning" in event_types

    def test_latency_emits_critical_event(
        self, monitor: HealthMonitor, engine: ReviewEngine,
    ) -> None:
        monitor.record_latency("angel_one", 600.0)
        events = engine.get_events_by_source("angel_one")
        event_types = [e.event_type for e in events]
        assert "latency_critical" in event_types

    def test_latency_averaged(self, monitor: HealthMonitor) -> None:
        """Record multiple latencies — average determines penalty."""
        for _ in range(5):
            monitor.record_latency("angel_one", 50.0)
        assert monitor.get_health_state("angel_one") == HEALTHY

        # One 600ms spike averaged with 5x 50ms: avg = (5*50 + 600)/6 ≈ 141ms
        monitor.record_latency("angel_one", 600.0)
        score = monitor.get_health_score("angel_one")
        assert 0.8 < score <= 1.0  # avg ≈ 141ms < 200ms, no penalty

    # ── Heartbeat ──────────────────────────────────────────────────────

    def test_record_heartbeat(self, monitor: HealthMonitor) -> None:
        monitor.record_heartbeat("angel_one")
        age = monitor.get_heartbeat_age("angel_one")
        assert age is not None
        assert age < 2.0  # Just recorded, age should be < 2s

    def test_heartbeat_age_nonexistent_source(self, monitor: HealthMonitor) -> None:
        assert monitor.get_heartbeat_age("nonexistent") is None

    def test_heartbeat_age_increases(self, monitor: HealthMonitor) -> None:
        """Heartbeat age should increase with time."""
        old = datetime.now(timezone.utc) - timedelta(seconds=60)
        monitor.record_heartbeat("angel_one", timestamp=old)
        age = monitor.get_heartbeat_age("angel_one")
        assert age is not None
        assert age >= 58.0

    # ── Reconnect ──────────────────────────────────────────────────────

    def test_record_reconnect_healthy(self, monitor: HealthMonitor) -> None:
        """1 reconnect is only -0.1 → score 0.9 → HEALTHY."""
        monitor.record_reconnect("angel_one")
        assert monitor.get_health_state("angel_one") == HEALTHY

    def test_record_reconnect_storm_is_degraded(self, monitor: HealthMonitor) -> None:
        """5 reconnects exceed threshold of 3: -0.3 → score 0.7 → HEALTHY still."""
        for _ in range(5):
            monitor.record_reconnect("angel_one")
        # Score = 1.0 - 0.3 = 0.7 → HEALTHY (0.7 >= 0.7)
        assert monitor.get_health_state("angel_one") == HEALTHY

    def test_reconnect_emits_event(
        self, monitor: HealthMonitor, engine: ReviewEngine,
    ) -> None:
        for _ in range(5):
            monitor.record_reconnect("angel_one")
        events = engine.get_events_by_source("angel_one")
        event_types = [e.event_type for e in events]
        assert "reconnect_storm" in event_types

    # ── Source Health Facts ────────────────────────────────────────────

    def test_record_source_health_facts(self, monitor: HealthMonitor) -> None:
        facts = {
            "latency_ms": 100.0,
            "heartbeat_age_s": 5.0,
            "reconnect_count": 0,
        }
        monitor.record_source_health_facts("angel_one", facts)
        # 100ms latency: no penalty. Recent heartbeat: no penalty. 0 reconnects.
        assert monitor.get_health_state("angel_one") == HEALTHY

    def test_record_source_health_facts_high_latency_is_degraded(
        self, monitor: HealthMonitor,
    ) -> None:
        """600ms latency → -0.4 → score 0.6 → DEGRADED."""
        facts = {"latency_ms": 600.0, "heartbeat_age_s": 1.0, "reconnect_count": 0}
        monitor.record_source_health_facts("angel_one", facts)
        assert monitor.get_health_state("angel_one") == DEGRADED

    def test_record_source_health_facts_empty(self, monitor: HealthMonitor) -> None:
        monitor.record_source_health_facts("angel_one", {})
        assert monitor.get_health_state("angel_one") == HEALTHY

    # ── Health Score ───────────────────────────────────────────────────

    def test_health_score_perfect(self, monitor: HealthMonitor) -> None:
        assert monitor.get_health_score("new_source") == 1.0

    def test_health_score_reduced_by_latency(self, monitor: HealthMonitor) -> None:
        monitor.record_latency("angel_one", 600.0)
        score = monitor.get_health_score("angel_one")
        assert score == 0.6  # 1.0 - 0.4

    def test_health_score_critical_combination(self, monitor: HealthMonitor) -> None:
        """Latency critical + old heartbeat → score < 0.4 → CRITICAL."""
        monitor.record_latency("angel_one", 600.0)  # -0.4 → 0.6
        old = datetime.now(timezone.utc) - timedelta(seconds=300)
        monitor.record_heartbeat("angel_one", timestamp=old)  # -0.3 → 0.3
        score = monitor.get_health_score("angel_one")
        assert score == 0.3

    def test_health_score_critical_state(self, monitor: HealthMonitor) -> None:
        """Latency critical + old heartbeat → score 0.3 → CRITICAL state."""
        monitor.record_latency("angel_one", 600.0)  # -0.4 → 0.6 → DEGRADED
        old = datetime.now(timezone.utc) - timedelta(seconds=300)
        monitor.record_heartbeat("angel_one", timestamp=old)  # -0.3 → 0.3 → CRITICAL
        assert monitor.get_health_state("angel_one") == CRITICAL

    def test_health_score_zero(self, monitor: HealthMonitor) -> None:
        """Multiple critical issues should drive score to 0."""
        monitor.record_latency("angel_one", 600.0)  # -0.4 → 0.6
        old = datetime.now(timezone.utc) - timedelta(seconds=300)
        monitor.record_heartbeat("angel_one", timestamp=old)  # -0.3 → 0.3
        for _ in range(5):
            monitor.record_reconnect("angel_one")  # -0.3 → 0.0

        score = monitor.get_health_score("angel_one")
        assert score == 0.0

    def test_health_score_floor_at_zero(self, monitor: HealthMonitor) -> None:
        """Score should not go below 0.0."""
        monitor.record_latency("angel_one", 600.0)
        monitor.record_latency("angel_one", 600.0)
        monitor.record_latency("angel_one", 600.0)
        old = datetime.now(timezone.utc) - timedelta(seconds=300)
        monitor.record_heartbeat("angel_one", timestamp=old)
        for _ in range(10):
            monitor.record_reconnect("angel_one")
        score = monitor.get_health_score("angel_one")
        assert score >= 0.0

    # ── State Transitions ──────────────────────────────────────────────

    def test_state_transition_healthy_to_degraded(
        self, monitor: HealthMonitor, engine: ReviewEngine,
    ) -> None:
        # Use a fresh source → starts at HEALTHY
        assert monitor.get_health_state("angel_one") == HEALTHY

        # 600ms → avg=600 → -0.4 → score 0.6 → DEGRADED
        monitor.record_latency("angel_one", 600.0)
        state = monitor.get_health_state("angel_one")
        assert state == DEGRADED, f"Expected DEGRADED got {state}"

        # State transition event should be emitted
        events = engine.get_events_by_source("angel_one")
        event_types = [e.event_type for e in events]
        assert "state_degraded" in event_types

    def test_state_transition_degraded_to_critical(
        self, monitor: HealthMonitor,
    ) -> None:
        # 600ms → avg=600 → -0.4 → score 0.6 → DEGRADED
        monitor.record_latency("angel_one", 600.0)
        assert monitor.get_health_state("angel_one") == DEGRADED

        # Old heartbeat → age=300s → -0.3 → score 0.3 → CRITICAL
        old = datetime.now(timezone.utc) - timedelta(seconds=300)
        monitor.record_heartbeat("angel_one", timestamp=old)
        assert monitor.get_health_state("angel_one") == CRITICAL

    def test_state_transition_healthy_to_critical(
        self, monitor: HealthMonitor,
    ) -> None:
        """600ms latency + old heartbeat → score 0.3 → CRITICAL."""
        monitor.record_latency("angel_one", 600.0)
        old = datetime.now(timezone.utc) - timedelta(seconds=300)
        monitor.record_heartbeat("angel_one", timestamp=old)
        state = monitor.get_health_state("angel_one")
        assert state == CRITICAL, f"Expected CRITICAL got {state}"

    # ── All Health States ──────────────────────────────────────────────

    def test_get_all_health_states_empty(self, monitor: HealthMonitor) -> None:
        assert monitor.get_all_health_states() == {}

    def test_get_all_health_states_populated(self, monitor: HealthMonitor) -> None:
        monitor.record_latency("angel_one", 50.0)
        # 600ms → -0.4 → score 0.6 → DEGRADED
        monitor.record_latency("other", 600.0)
        states = monitor.get_all_health_states()
        assert "angel_one" in states
        assert "other" in states
        assert states["angel_one"]["state"] == HEALTHY
        assert states["other"]["state"] == DEGRADED

    def test_get_all_health_states_shape(self, monitor: HealthMonitor) -> None:
        monitor.record_latency("angel_one", 100.0)
        states = monitor.get_all_health_states()
        entry = states["angel_one"]
        assert "state" in entry
        assert "score" in entry
        assert "avg_latency_ms" in entry
        assert "heartbeat_age_s" in entry
        assert "reconnect_count" in entry
        assert "events_emitted" in entry

    # ── Edge Cases ─────────────────────────────────────────────────────

    def test_unknown_source_state(self, monitor: HealthMonitor) -> None:
        assert monitor.get_health_state("unknown") == HEALTHY

    def test_multiple_sources_independent(self, monitor: HealthMonitor) -> None:
        # 600ms → -0.4 → score 0.6 → DEGRADED
        monitor.record_latency("source_a", 600.0)
        monitor.record_latency("source_b", 50.0)

        assert monitor.get_health_state("source_a") == DEGRADED
        assert monitor.get_health_state("source_b") == HEALTHY

    def test_critical_combination_sources(self, monitor: HealthMonitor) -> None:
        """600ms + old heartbeat for one source → CRITICAL, other stays HEALTHY."""
        monitor.record_latency("source_a", 600.0)  # -0.4 → score 0.6 → DEGRADED
        old = datetime.now(timezone.utc) - timedelta(seconds=300)
        monitor.record_heartbeat("source_a", timestamp=old)  # -0.3 → score 0.3 → CRITICAL
        monitor.record_latency("source_b", 50.0)  # score 1.0 → HEALTHY

        assert monitor.get_health_state("source_a") == CRITICAL
        assert monitor.get_health_state("source_b") == HEALTHY

    def test_deduplicates_events(self, monitor: HealthMonitor, engine: ReviewEngine) -> None:
        """Same event type should not be emitted twice for the same source."""
        monitor.record_latency("angel_one", 600.0)
        monitor.record_latency("angel_one", 600.0)
        monitor.record_latency("angel_one", 600.0)

        events = engine.get_events_by_source("angel_one")
        latency_critical_events = [e for e in events if e.event_type == "latency_critical"]
        assert len(latency_critical_events) == 1  # Only emitted once

    def test_health_and_review_integration(self, engine: ReviewEngine) -> None:
        """HealthMonitor CRITICAL event → ReviewEngine DEGRADED signal (1 critical event)."""
        monitor = HealthMonitor(engine)

        for _ in range(5):
            monitor.record_reconnect("angel_one")

        signal = engine.compute_signal("angel_one")
        # reconnect_storm event is CRITICAL severity
        # 1 CRITICAL event → DEGRADED signal
        assert signal == ReviewSignal.DEGRADED
