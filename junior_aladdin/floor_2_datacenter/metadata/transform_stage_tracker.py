"""Floor 2 Metadata — transform stage tracker.

Tracks ``TransformStage`` progression for each packet as it moves through
the Floor 2 pipeline:

    RAW → VALIDATED → CLEANED → STRUCTURED

The tracker updates the ``NormalizedRawStore`` record and maintains a
``StageHistory`` for each packet so later operators can investigate
whether a packet got stuck at any stage.

Architecture rules:
- Stages are strictly ordered — a packet cannot skip a stage.
- If a packet fails validation, it may remain at RAW (not advanced).
- ``stuck`` detection: if a packet hasn't advanced in a configurable
  timeout, it's flagged as stuck.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from threading import Lock
from typing import Any

from junior_aladdin.floor_2_datacenter.datacenter_types import (
    StageHistory,
    TransformStage,
)
from junior_aladdin.floor_2_datacenter.raw.normalized_raw_store import (
    NormalizedRawStore,
)
from junior_aladdin.shared.logging import get_logger

logger = get_logger("transform_stage_tracker")

# Default timeout before a packet is flagged as stuck (seconds)
DEFAULT_STUCK_TIMEOUT_S: float = 300.0  # 5 minutes


class TransformStageTracker:
    """Tracks transform stage progression for packets.

    Typical usage::

        tracker = TransformStageTracker(normalized_store)
        tracker.advance("pkt_001", TransformStage.VALIDATED)
        tracker.advance("pkt_001", TransformStage.CLEANED)
        history = tracker.get_history("pkt_001")
        stuck = tracker.find_stuck_packets()
    """

    def __init__(
        self,
        normalized_store: NormalizedRawStore,
        stuck_timeout_s: float = DEFAULT_STUCK_TIMEOUT_S,
    ) -> None:
        """Initialise the tracker.

        Args:
            normalized_store: The raw store to update.
            stuck_timeout_s: Seconds after which a non-advancing packet
                is flagged as stuck.
        """
        self._store = normalized_store
        self._stuck_timeout_s = stuck_timeout_s
        self._lock = Lock()
        # packet_id -> StageHistory
        self._stage_history: dict[str, StageHistory] = {}
        # Valid stage progression order
        self._stage_order: list[TransformStage] = [
            TransformStage.RAW,
            TransformStage.VALIDATED,
            TransformStage.CLEANED,
            TransformStage.STRUCTURED,
        ]

    # ------------------------------------------------------------------
    # Core API
    # ------------------------------------------------------------------

    def advance(self, packet_id: str, stage: TransformStage) -> bool:
        """Advance a packet to the next transform stage.

        Updates both the ``NormalizedRawStore`` record and the internal
        ``StageHistory`` tracker.

        Args:
            packet_id: The unique packet identifier.
            stage: The target stage to advance to.

        Returns:
            ``True`` if the stage was advanced, ``False`` if the packet
            wasn't found or the stage is out of order.
        """
        # ── Validate stage order ──────────────────────────────────────
        if stage not in self._stage_order:
            logger.warning(
                "Invalid transform stage",
                extra={"packet_id": packet_id, "stage": str(stage)},
            )
            return False

        # Check that the stage is not regressing or skipping
        current = self._get_current_stage(packet_id)
        if current is not None:
            current_idx = self._stage_order.index(current)
            target_idx = self._stage_order.index(stage)
            if target_idx < current_idx:
                logger.warning(
                    "Cannot regress transform stage",
                    extra={
                        "packet_id": packet_id,
                        "current": current.value,
                        "target": stage.value,
                    },
                )
                return False
            if target_idx > current_idx + 1:
                logger.warning(
                    "Cannot skip transform stage",
                    extra={
                        "packet_id": packet_id,
                        "current": current.value,
                        "target": stage.value,
                    },
                )
                return False

        # ── Update the normalized store ──────────────────────────────
        store_updated = self._store.update_transform_stage(packet_id, stage)

        if not store_updated:
            return False

        # ── Update stage history ──────────────────────────────────────
        now = datetime.now(timezone.utc)
        with self._lock:
            history = self._stage_history.get(packet_id) or StageHistory(
                packet_id=packet_id,
            )
            if history.raw_at is None:
                history.raw_at = now
            if stage == TransformStage.VALIDATED:
                history.validated_at = now
            elif stage == TransformStage.CLEANED:
                history.cleaned_at = now
            elif stage == TransformStage.STRUCTURED:
                history.structured_at = now
            history.stuck = False  # Reset stuck flag on successful advance
            self._stage_history[packet_id] = history

        logger.debug(
            "Transform stage advanced",
            extra={
                "packet_id": packet_id,
                "stage": stage.value,
            },
        )
        return True

    def get_history(self, packet_id: str) -> StageHistory | None:
        """Get the ``StageHistory`` for a packet.

        Args:
            packet_id: The unique packet identifier.

        Returns:
            The ``StageHistory``, or ``None`` if the packet has no history.
        """
        with self._lock:
            return self._stage_history.get(packet_id)

    def get_current_stage(self, packet_id: str) -> TransformStage | None:
        """Get the current transform stage for a packet.

        Args:
            packet_id: The unique packet identifier.

        Returns:
            The current ``TransformStage``, or ``None`` if not found.
        """
        return self._get_current_stage(packet_id)

    def find_stuck_packets(self) -> list[dict[str, Any]]:
        """Find packets that haven't advanced in the stuck timeout.

        Returns:
            List of dicts with ``packet_id``, ``stage``, ``last_updated``,
            and ``stuck_for_s``.
        """
        now = datetime.now(timezone.utc)
        stuck: list[dict[str, Any]] = []

        with self._lock:
            for packet_id, history in self._stage_history.items():
                last_advanced = self._get_last_advanced(history)
                if last_advanced is None:
                    continue

                elapsed_s = (now - last_advanced).total_seconds()
                if elapsed_s > self._stuck_timeout_s:
                    # Only mark as stuck if not already at STRUCTURED (terminal)
                    current = self._get_current_stage(packet_id)
                    if current and current != TransformStage.STRUCTURED:
                        stuck.append({
                            "packet_id": packet_id,
                            "stage": current.value if current else "UNKNOWN",
                            "last_updated": last_advanced.isoformat(),
                            "stuck_for_s": round(elapsed_s, 1),
                        })
                        history.stuck = True

        if stuck:
            logger.warning(
                "Stuck packets detected",
                extra={"count": len(stuck)},
            )

        return stuck

    def reset(self, packet_id: str) -> bool:
        """Reset a packet's stage history (back to RAW).

        Args:
            packet_id: The unique packet identifier.

        Returns:
            ``True`` if reset, ``False`` if not found.
        """
        with self._lock:
            if packet_id not in self._stage_history:
                return False
            self._stage_history[packet_id] = StageHistory(
                packet_id=packet_id,
                raw_at=datetime.now(timezone.utc),
            )

        return self._store.update_transform_stage(packet_id, TransformStage.RAW)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_current_stage(self, packet_id: str) -> TransformStage | None:
        """Get the current stage from the normalized store record."""
        record = self._store.get(packet_id)
        if record is None:
            return None
        stage_str = record.get("transform_stage")
        if stage_str is None:
            return None
        try:
            return TransformStage(stage_str)
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _get_last_advanced(history: StageHistory) -> datetime | None:
        """Get the most recent advancement timestamp from history."""
        candidates = [
            history.structured_at,
            history.cleaned_at,
            history.validated_at,
            history.raw_at,
        ]
        # Filter None and return the most recent
        valid = [t for t in candidates if t is not None]
        return max(valid) if valid else None
