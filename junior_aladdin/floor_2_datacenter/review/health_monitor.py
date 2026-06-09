"""Floor 2 Health Monitor — continuous health checks, source monitoring.

Provides the **HealthMonitor** class that continuously monitors source health,
tracks latency/reconnect/health states, and triggers audits when thresholds
are breached.

Responsibilities:
- **Source health tracking**: Monitor connection state, latency, heartbeats.
- **Health state transitions**: Track HEALTHY → DEGRADED → CRITICAL transitions.
- **Threshold-based alerts**: Emit ``HealthEvent`` via ``ReviewEngine`` when
  configurable thresholds are breached.
- **Health scoring**: Compute a numerical health score per source (0.0–1.0).

Architecture rules:
- All health measures are FACTUAL — latency in ms, heartbeat age in seconds.
- No predictive analytics — only current/measured health state.
- Thresholds are configurable per source.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from threading import Lock
from typing import Any

from junior_aladdin.floor_2_datacenter.datacenter_types import HealthEvent
from junior_aladdin.floor_2_datacenter.review.review_engine import ReviewEngine
from junior_aladdin.shared.logging import get_logger

logger = get_logger("health_monitor")

# Default health thresholds
DEFAULT_LATENCY_THRESHOLD_MS: float = 200.0  # Warning at 200ms average
DEFAULT_LATENCY_CRITICAL_MS: float = 500.0  # Critical at 500ms
DEFAULT_HEARTBEAT_AGE_WARNING_S: float = 30.0  # Warning at 30s since last heartbeat
DEFAULT_HEARTBEAT_AGE_CRITICAL_S: float = 120.0  # Critical at 120s
DEFAULT_RECONNECT_WINDOW_S: float = 300.0  # Reset reconnect count after 5 min
DEFAULT_RECONNECT_THRESHOLD: int = 3  # 3+ reconnects in window = CRITICAL


# Valid health states
HEALTHY = "HEALTHY"
DEGRADED = "DEGRADED"
CRITICAL = "CRITICAL"
HEALTH_STATES = (HEALTHY, DEGRADED, CRITICAL)


class HealthMonitor:
    """Continuous health monitor for data sources.

    Tracks per-source health metrics and emits events through the
    ``ReviewEngine`` when thresholds are breached.

    Typical usage::

        engine = ReviewEngine()
        monitor = HealthMonitor(engine)
        monitor.record_latency("angel_one", 150.0)
        monitor.record_heartbeat("angel_one")
        monitor.record_reconnect("angel_one")
        score = monitor.get_health_score("angel_one")
        state = monitor.get_health_state("angel_one")
    """

    def __init__(
        self,
        review_engine: ReviewEngine,
        latency_threshold_ms: float = DEFAULT_LATENCY_THRESHOLD_MS,
        latency_critical_ms: float = DEFAULT_LATENCY_CRITICAL_MS,
        heartbeat_age_warning_s: float = DEFAULT_HEARTBEAT_AGE_WARNING_S,
        heartbeat_age_critical_s: float = DEFAULT_HEARTBEAT_AGE_CRITICAL_S,
        reconnect_window_s: float = DEFAULT_RECONNECT_WINDOW_S,
        reconnect_threshold: int = DEFAULT_RECONNECT_THRESHOLD,
    ) -> None:
        """Initialise the health monitor.

        Args:
            review_engine: The review engine to emit events through.
            latency_threshold_ms: Latency above this (ms) triggers CAUTION.
            latency_critical_ms: Latency above this (ms) triggers CRITICAL.
            heartbeat_age_warning_s: Seconds since last heartbeat before CAUTION.
            heartbeat_age_critical_s: Seconds since last heartbeat before CRITICAL.
            reconnect_window_s: Time window (seconds) for counting reconnects.
            reconnect_threshold: Reconnects in window before CRITICAL.
        """
        self._engine = review_engine
        self._lock = Lock()

        self._latency_threshold_ms = latency_threshold_ms
        self._latency_critical_ms = latency_critical_ms
        self._heartbeat_age_warning_s = heartbeat_age_warning_s
        self._heartbeat_age_critical_s = heartbeat_age_critical_s
        self._reconnect_window_s = reconnect_window_s
        self._reconnect_threshold = reconnect_threshold

        # Per-source health state
        # source -> { "latency_samples": [...], "last_heartbeat": datetime,
        #             "reconnects": [(timestamp, ...)], "state": str,
        #             "state_changed": datetime, "events_emitted": [...] }
        self._source_health: dict[str, dict[str, Any]] = {}

    # ------------------------------------------------------------------
    # Metric Recording
    # ------------------------------------------------------------------

    def record_latency(self, source: str, latency_ms: float) -> None:
        """Record a latency measurement for a source.

        If the average latency exceeds thresholds, emits a health event.

        Args:
            source: The source name.
            latency_ms: Measured latency in milliseconds.
        """
        with self._lock:
            health = self._get_or_create(source)
            health["latency_samples"].append(latency_ms)

            # Keep last 10 samples for averaging
            if len(health["latency_samples"]) > 10:
                health["latency_samples"] = health["latency_samples"][-10:]

            avg_latency = sum(health["latency_samples"]) / len(health["latency_samples"])

        # Emit events based on average latency (outside lock to avoid deadlock)
        if avg_latency >= self._latency_critical_ms:
            self._emit_if_new(source, "latency_critical", "CRITICAL",
                              f"Avg latency {avg_latency:.0f}ms exceeded critical {self._latency_critical_ms:.0f}ms",
                              {"avg_latency_ms": avg_latency})
        elif avg_latency >= self._latency_threshold_ms:
            self._emit_if_new(source, "latency_warning", "SEVERE",
                              f"Avg latency {avg_latency:.0f}ms exceeded threshold {self._latency_threshold_ms:.0f}ms",
                              {"avg_latency_ms": avg_latency})

        # Update health state
        self._update_state(source)

    def record_heartbeat(self, source: str, timestamp: datetime | None = None) -> None:
        """Record a heartbeat for a source.

        Emits heartbeat-missed events if the heartbeat is stale, and
        updates the source health state.

        Args:
            source: The source name.
            timestamp: Heartbeat timestamp (defaults to now).
        """
        now = timestamp or datetime.now(timezone.utc)
        with self._lock:
            health = self._get_or_create(source)
            health["last_heartbeat"] = now

        # Check heartbeat age and emit warnings
        age = self.get_heartbeat_age(source)
        if age is not None:
            if age > self._heartbeat_age_critical_s:
                self._emit_if_new(
                    source, "heartbeat_missed", "CRITICAL",
                    f"No heartbeat for {age:.0f}s (critical: {self._heartbeat_age_critical_s:.0f}s)",
                    {"heartbeat_age_s": age},
                )
            elif age > self._heartbeat_age_warning_s:
                self._emit_if_new(
                    source, "heartbeat_warning", "SEVERE",
                    f"No heartbeat for {age:.0f}s (warning: {self._heartbeat_age_warning_s:.0f}s)",
                    {"heartbeat_age_s": age},
                )

        self._update_state(source)

    def get_heartbeat_age(self, source: str) -> float | None:
        """Get the age of the last heartbeat in seconds.

        Args:
            source: The source name.

        Returns:
            Seconds since last heartbeat, or ``None`` if no heartbeat recorded.
        """
        with self._lock:
            health = self._source_health.get(source)
            if health is None or health.get("last_heartbeat") is None:
                return None
            age = (datetime.now(timezone.utc) - health["last_heartbeat"]).total_seconds()
        return max(0.0, age)

    def record_reconnect(self, source: str) -> None:
        """Record a reconnection event for a source.

        If reconnects exceed the threshold within the configured window,
        emits a critical health event.

        Args:
            source: The source name.
        """
        now = datetime.now(timezone.utc)
        with self._lock:
            health = self._get_or_create(source)
            health["reconnects"].append(now)

            # Prune reconnects outside the window
            cutoff = now - timedelta(seconds=self._reconnect_window_s)
            health["reconnects"] = [
                t for t in health["reconnects"] if t >= cutoff
            ]

            reconnect_count = len(health["reconnects"])

        if reconnect_count >= self._reconnect_threshold:
            self._emit_if_new(
                source, "reconnect_storm", "CRITICAL",
                f"{reconnect_count} reconnection(s) in {self._reconnect_window_s:.0f}s window "
                f"(threshold: {self._reconnect_threshold})",
                {"reconnect_count": reconnect_count, "window_s": self._reconnect_window_s},
            )

        self._update_state(source)

    def record_source_health_facts(self, source: str, facts: dict[str, Any]) -> None:
        """Record health facts from a source's ``source_health_facts`` dict.

        Extracts ``latency_ms``, ``heartbeat_age_s``, and ``reconnect_count``
        from the facts dict and processes them.

        Args:
            source: The source name.
            facts: The ``source_health_facts`` dict from the Floor 1 payload.
        """
        latency = facts.get("latency_ms")
        if latency is not None:
            self.record_latency(source, float(latency))

        heartbeat_age = facts.get("heartbeat_age_s")
        if heartbeat_age is not None:
            # If heartbeat_age is small, it means a recent heartbeat
            if float(heartbeat_age) < self._heartbeat_age_critical_s:
                self.record_heartbeat(source)

        reconnect_count = facts.get("reconnect_count", 0)
        for _ in range(int(reconnect_count)):
            self.record_reconnect(source)

    # ------------------------------------------------------------------
    # Health State
    # ------------------------------------------------------------------

    def get_health_state(self, source: str) -> str:
        """Get the current health state for a source.

        Args:
            source: The source name.

        Returns:
            ``\"HEALTHY\"``, ``\"DEGRADED\"``, or ``\"CRITICAL\"``.
        """
        with self._lock:
            health = self._source_health.get(source)
            if health is None:
                return HEALTHY
            return health.get("state", HEALTHY)

    def get_health_score(self, source: str) -> float:
        """Compute a health score (0.0–1.0) for a source.

        Accounts for latency, heartbeat age, reconnection rate, and recent
        events.

        Args:
            source: The source name.

        Returns:
            Health score where 1.0 = perfect health.
        """
        with self._lock:
            health = self._source_health.get(source)
            if health is None:
                return 1.0

        score = 1.0

        # Latency penalty
        avg_latency = self._get_avg_latency(source)
        if avg_latency is not None:
            if avg_latency > self._latency_critical_ms:
                score -= 0.4
            elif avg_latency > self._latency_threshold_ms:
                score -= 0.2

        # Heartbeat penalty
        heartbeat_age = self.get_heartbeat_age(source)
        if heartbeat_age is not None:
            if heartbeat_age > self._heartbeat_age_critical_s:
                score -= 0.3
            elif heartbeat_age > self._heartbeat_age_warning_s:
                score -= 0.15

        # Reconnect penalty
        reconnect_count = self._get_reconnect_count(source)
        if reconnect_count >= self._reconnect_threshold:
            score -= 0.3
        elif reconnect_count > 0:
            score -= 0.1 * reconnect_count

        return max(0.0, round(score, 2))

    def get_all_health_states(self) -> dict[str, dict[str, Any]]:
        """Get a complete health report for all monitored sources.

        Returns:
            Dict of ``{source: {state, score, avg_latency_ms, heartbeat_age_s,
            reconnect_count, events_emitted}}``.
        """
        result: dict[str, dict[str, Any]] = {}
        with self._lock:
            sources = list(self._source_health.keys())

        for source in sources:
            result[source] = {
                "state": self.get_health_state(source),
                "score": self.get_health_score(source),
                "avg_latency_ms": self._get_avg_latency(source),
                "heartbeat_age_s": self.get_heartbeat_age(source),
                "reconnect_count": self._get_reconnect_count(source),
                "events_emitted": self._get_events_emitted(source),
            }
        return result

    # ------------------------------------------------------------------
    # Internal Helpers
    # ------------------------------------------------------------------

    def _get_or_create(self, source: str) -> dict[str, Any]:
        """Get or create the health tracking dict for a source."""
        if source not in self._source_health:
            self._source_health[source] = {
                "latency_samples": [],
                "last_heartbeat": None,
                "reconnects": [],
                "state": HEALTHY,
                "state_changed": datetime.now(timezone.utc),
                "events_emitted": [],
            }
        return self._source_health[source]

    def _update_state(self, source: str) -> None:
        """Update the health state for a source based on current metrics."""
        score = self.get_health_score(source)
        new_state: str

        if score < 0.4:
            new_state = CRITICAL
        elif score < 0.7:
            new_state = DEGRADED
        else:
            new_state = HEALTHY

        # Extract state transition info inside the lock, then emit outside to
        # avoid deadlock (regular Lock is not reentrant).
        old_state: str | None = None
        with self._lock:
            health = self._source_health.get(source)
            if health and health["state"] != new_state:
                old_state = health["state"]
                health["state"] = new_state
                health["state_changed"] = datetime.now(timezone.utc)

        # Emit state transition event outside the lock
        if old_state is not None:
            event_type = f"state_{new_state.lower()}"
            severity = "CRITICAL" if new_state == CRITICAL else "SEVERE"
            self._emit_if_new(
                source, event_type, severity,
                f"State transition: {old_state} → {new_state} "
                f"(score: {score:.2f})",
                {"old_state": old_state, "new_state": new_state, "score": score},
            )

    def _emit_if_new(
        self,
        source: str,
        event_type: str,
        severity: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        """Emit a health event only if no identical event already exists."""
        with self._lock:
            health = self._source_health.get(source)
            if health and event_type in health.get("events_emitted", []):
                return  # Already emitted this event type for this source

        event_id = self._engine.emit_event(event_type, severity, source, message, details)

        with self._lock:
            health = self._source_health.get(source)
            if health:
                health["events_emitted"].append(event_type)

    def _get_avg_latency(self, source: str) -> float | None:
        """Get the average latency for a source, or None."""
        with self._lock:
            health = self._source_health.get(source)
            if health is None or not health["latency_samples"]:
                return None
            return sum(health["latency_samples"]) / len(health["latency_samples"])

    def _get_reconnect_count(self, source: str) -> int:
        """Get the number of reconnects within the configured window."""
        now = datetime.now(timezone.utc)
        with self._lock:
            health = self._source_health.get(source)
            if health is None:
                return 0
            cutoff = now - timedelta(seconds=self._reconnect_window_s)
            return len([t for t in health["reconnects"] if t >= cutoff])

    def _get_events_emitted(self, source: str) -> list[str]:
        """Get the list of event types emitted for a source."""
        with self._lock:
            health = self._source_health.get(source)
            if health is None:
                return []
            return list(health.get("events_emitted", []))
