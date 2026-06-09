"""Floor 2 Ingress — ingress monitor.

Tracks ingress metrics (packet counts, error counts, rates) and detects
simple anomalies such as sudden drops or surges in packet flow.

Architecture rules:
- Metrics are FACTUAL — counts, rates, and thresholds only.
- Anomaly detection flags unusual patterns but does NOT interpret them.
- No intelligence, no opinion, no trading signal generation.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from threading import Lock
from typing import Any

from junior_aladdin.shared.logging import get_logger

logger = get_logger("ingress_monitor")


class IngressMonitor:
    """Tracks ingress metrics and detects simple flow anomalies.

    Thread-safe. Tracks:
    - Total packet count
    - Packet count per source
    - Packet count per feed_type
    - Error count
    - Packet rate (packets / recent window)
    - Anomaly flags (sudden drop, sudden surge)

    Typical usage::

        monitor = IngressMonitor()
        monitor.record_ingest(source="angel_one", feed_type="spot_tick")
        monitor.record_ingest(source="angel_one", feed_type="spot_tick")
        print(monitor.packet_count(source="angel_one"))  # 2
        print(monitor.anomalies_detected())  # list of anomaly flags
    """

    def __init__(self, rate_window_s: float = 60.0, surge_threshold: float = 3.0,
                 drop_threshold: float = 0.1) -> None:
        """Initialise the monitor.

        Args:
            rate_window_s: Time window in seconds for rate calculation.
            surge_threshold: Multiplier above baseline to flag a surge.
            drop_threshold: Fraction of baseline below which to flag a drop.
        """
        self._lock = Lock()

        # Counters
        self._total_packets: int = 0
        self._by_source: dict[str, int] = defaultdict(int)
        self._by_feed_type: dict[str, int] = defaultdict(int)
        self._errors: int = 0

        # Timestamps for rate calculation (sliding window)
        self._timestamps: list[datetime] = []

        # Window configuration
        self._rate_window_s = rate_window_s
        self._surge_threshold = surge_threshold
        self._drop_threshold = drop_threshold

        # Baseline tracking (for anomaly detection)
        self._baseline_rate: float | None = None
        self._baseline_sample_count: int = 0
        self._baseline_samples_needed: int = 100  # packets before baseline stabilises

        # Anomaly flag list
        self._anomalies: list[dict[str, Any]] = []

        # Start time
        self._start_time: datetime = datetime.now(timezone.utc)

        logger.info(
            "IngressMonitor initialised",
            extra={
                "rate_window_s": rate_window_s,
                "surge_threshold": surge_threshold,
                "drop_threshold": drop_threshold,
            },
        )

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------

    def record_ingest(self, source: str, feed_type: str) -> None:
        """Record a successfully ingested packet.

        Args:
            source: Source name (e.g., ``\"angel_one\"``).
            feed_type: Feed type (e.g., ``\"spot_tick\"``).
        """
        now = datetime.now(timezone.utc)

        with self._lock:
            self._total_packets += 1
            self._by_source[source] += 1
            self._by_feed_type[feed_type] += 1
            self._timestamps.append(now)
            self._prune_timestamps(now)

            # Update baseline after enough samples
            if self._baseline_sample_count < self._baseline_samples_needed:
                self._baseline_sample_count += 1
                if self._baseline_sample_count >= self._baseline_samples_needed:
                    self._baseline_rate = self._compute_rate(now)
                    logger.info(
                        "Baseline rate stabilised",
                        extra={"baseline_rate": self._baseline_rate},
                    )

    def record_error(self, source: str | None = None, feed_type: str | None = None,
                     error_message: str | None = None) -> None:
        """Record an ingress error.

        Args:
            source: Optional source name associated with the error.
            feed_type: Optional feed type associated with the error.
            error_message: Optional error description.
        """
        with self._lock:
            self._errors += 1

        logger.warning(
            "Ingress error recorded",
            extra={
                "source": source,
                "feed_type": feed_type,
                "error": error_message,
            },
        )

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def packet_count(self, source: str | None = None,
                     feed_type: str | None = None) -> int:
        """Return the packet count, optionally filtered by source or feed_type.

        Args:
            source: If provided, count only packets from this source.
            feed_type: If provided, count only packets of this feed type.

        Returns:
            Packet count matching the filters.
        """
        with self._lock:
            if source is not None:
                return self._by_source.get(source, 0)
            if feed_type is not None:
                return self._by_feed_type.get(feed_type, 0)
            return self._total_packets

    def error_count(self) -> int:
        """Return the total number of recorded errors."""
        with self._lock:
            return self._errors

    @property
    def total_packets(self) -> int:
        """Total packets ingested since monitor start."""
        with self._lock:
            return self._total_packets

    @property
    def uptime_s(self) -> float:
        """Seconds since this monitor was created."""
        return (datetime.now(timezone.utc) - self._start_time).total_seconds()

    def current_rate(self) -> float:
        """Compute the current ingest rate (packets / second) over the window.

        Returns:
            Packets per second in the current rate window.
        """
        now = datetime.now(timezone.utc)
        with self._lock:
            self._prune_timestamps(now)
            return self._compute_rate(now)

    def _compute_rate(self, now: datetime) -> float:
        """Compute rate from pruned timestamps."""
        if not self._timestamps:
            return 0.0
        elapsed = (now - self._timestamps[0]).total_seconds()
        if elapsed <= 0:
            return 0.0
        return len(self._timestamps) / elapsed

    def _prune_timestamps(self, now: datetime) -> None:
        """Remove timestamps outside the rate window."""
        cutoff = now - timedelta(seconds=self._rate_window_s)
        while self._timestamps and self._timestamps[0] < cutoff:
            self._timestamps.pop(0)

    # ------------------------------------------------------------------
    # Anomaly detection
    # ------------------------------------------------------------------

    def check_anomalies(self) -> list[dict[str, Any]]:
        """Check for flow anomalies and return any new flags.

        Detects:
        - **Sudden drop**: Current rate < ``drop_threshold * baseline``
        - **Sudden surge**: Current rate > ``surge_threshold * baseline``

        Returns:
            List of anomaly dicts with ``type``, ``message``, ``current_rate``,
            ``baseline_rate``, and ``timestamp``.
        """
        now = datetime.now(timezone.utc)
        new_flags: list[dict[str, Any]] = []

        with self._lock:
            if self._baseline_rate is None or self._total_packets == 0:
                return new_flags  # not enough data yet

            self._prune_timestamps(now)
            current = self._compute_rate(now)

        if self._baseline_rate <= 0:
            return new_flags

        ratio = current / self._baseline_rate

        if ratio < self._drop_threshold:
            flag = {
                "type": "SUDDEN_DROP",
                "description": (
                    f"Ingest rate dropped from {self._baseline_rate:.2f} pkt/s "
                    f"to {current:.2f} pkt/s (ratio={ratio:.2f})"
                ),
                "current_rate": round(current, 4),
                "baseline_rate": round(self._baseline_rate, 4),
                "ratio": round(ratio, 4),
                "timestamp": now.isoformat(),
            }
            with self._lock:
                self._anomalies.append(flag)
            new_flags.append(flag)
            logger.warning("Anomaly detected: SUDDEN_DROP", extra=flag)

        elif ratio > self._surge_threshold:
            flag = {
                "type": "SUDDEN_SURGE",
                "description": (
                    f"Ingest rate surged from {self._baseline_rate:.2f} pkt/s "
                    f"to {current:.2f} pkt/s (ratio={ratio:.2f})"
                ),
                "current_rate": round(current, 4),
                "baseline_rate": round(self._baseline_rate, 4),
                "ratio": round(ratio, 4),
                "timestamp": now.isoformat(),
            }
            with self._lock:
                self._anomalies.append(flag)
            new_flags.append(flag)
            logger.warning("Anomaly detected: SUDDEN_SURGE", extra=flag)

        return new_flags

    def anomalies_detected(self) -> list[dict[str, Any]]:
        """Return all anomalies detected so far."""
        with self._lock:
            return list(self._anomalies)

    def clear_anomalies(self) -> None:
        """Clear all recorded anomalies."""
        with self._lock:
            self._anomalies.clear()
