"""Floor 2 Validation — validation router.

Routes a packet through the applicable validators based on its
``ValidationTier``, then returns an ``AggregateValidation`` result.

Validation tier → validator mapping:
    **Tier A** (very strong): all 5 validators
    - duplicate, timestamp, continuity, schema, corruption

    **Tier B** (strong): 4 validators (skip corruption)
    - duplicate, timestamp, continuity, schema

    **Tier C** (medium/basic): 2 validators
    - schema, timestamp

Architecture rules:
- Dynamic validation per feed type — not all data gets the same depth.
- Validation is FACTUAL: PASS/FAIL/FLAG with process confidence scores.
- No intelligence, no opinion, no trading signal generation.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from junior_aladdin.floor_2_datacenter.datacenter_contracts import (
    get_validation_tier_for_feed,
)
from junior_aladdin.floor_2_datacenter.datacenter_types import (
    AggregateValidation,
    ValidationDecision,
    ValidationResult,
    ValidationTier,
)
from junior_aladdin.floor_2_datacenter.raw.normalized_raw_store import (
    NormalizedRawStore,
)
from junior_aladdin.floor_2_datacenter.validation.continuity_validator import (
    validate_continuity,
)
from junior_aladdin.floor_2_datacenter.validation.corruption_validator import (
    validate_corruption,
)
from junior_aladdin.floor_2_datacenter.validation.duplicate_validator import (
    validate_duplicate,
)
from junior_aladdin.floor_2_datacenter.validation.schema_validator import (
    validate_schema,
)
from junior_aladdin.floor_2_datacenter.validation.timestamp_validator import (
    validate_timestamp,
)
from junior_aladdin.shared.logging import get_logger

logger = get_logger("validation_router")


class ValidationRouter:
    """Routes packets through applicable validators based on validation tier.

    Maintains per-source+feed-type state (last timestamp) for continuity
    and timestamp ordering checks.

    Typical usage::

        router = ValidationRouter(normalized_store)
        result = router.validate(record)
        if result.decision == ValidationDecision.PASS:
            # proceed to cleaning
    """

    def __init__(
        self,
        normalized_store: NormalizedRawStore,
    ) -> None:
        """Initialise the validation router.

        Args:
            normalized_store: The normalised raw store for duplicate checks.
        """
        self._store = normalized_store
        # Key: (source, feed_type) -> last received_at for continuity checks
        self._last_timestamps: dict[tuple[str, str], datetime] = {}

    # ------------------------------------------------------------------
    # Core API
    # ------------------------------------------------------------------

    def validate(self, record: dict[str, Any]) -> AggregateValidation:
        """Run all applicable validators for a packet's feed type.

        Args:
            record: The packet record dict (from ``NormalizedRawStore.get()``
                or similar).

        Returns:
            An ``AggregateValidation`` containing:
            - ``tier``: The validation tier used.
            - ``decision``: ``PASS`` / ``FAIL`` / ``FLAG``.
            - ``results``: List of individual ``ValidationResult``.
            - ``validation_confidence``: Proportion of validators that passed.
        """
        feed_type = record.get("feed_type", "unknown")
        source = record.get("source", "unknown")
        tier_str = get_validation_tier_for_feed(feed_type)
        tier = ValidationTier(tier_str)

        # Determine which validators to run
        validators = self._get_validators_for_tier(tier)

        results: list[ValidationResult] = []
        key = (source, feed_type)
        last_ts = self._last_timestamps.get(key)

        for validator_name in validators:
            result = self._run_validator(validator_name, record, last_ts)
            results.append(result)

            # Update last timestamp after timestamp validation.
            # Use MAX to avoid regressing on out-of-order packets.
            if validator_name == "timestamp" and result.passed:
                envelope = record.get("minimal_source_envelope", {})
                received_at_raw = envelope.get("received_at")
                if received_at_raw:
                    if isinstance(received_at_raw, str):
                        try:
                            parsed = datetime.fromisoformat(received_at_raw)
                            if parsed.tzinfo is None:
                                parsed = parsed.replace(tzinfo=timezone.utc)
                            if key in self._last_timestamps:
                                self._last_timestamps[key] = max(parsed, self._last_timestamps[key])
                            else:
                                self._last_timestamps[key] = parsed
                        except (ValueError, TypeError):
                            pass
                    elif isinstance(received_at_raw, datetime):
                        if received_at_raw.tzinfo is None:
                            received_at_raw = received_at_raw.replace(tzinfo=timezone.utc)
                        if key in self._last_timestamps:
                            self._last_timestamps[key] = max(received_at_raw, self._last_timestamps[key])
                        else:
                            self._last_timestamps[key] = received_at_raw

        # Aggregate decision
        decision, confidence = self._aggregate(results)

        return AggregateValidation(
            tier=tier,
            decision=decision,
            results=results,
            validation_confidence=confidence,
        )

    def get_last_timestamp(self, source: str, feed_type: str) -> datetime | None:
        """Get the last known timestamp for a source+feed_type pair."""
        return self._last_timestamps.get((source, feed_type))

    def reset_state(self) -> None:
        """Reset all tracked state (last timestamps)."""
        self._last_timestamps.clear()
        logger.info("ValidationRouter state reset")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _get_validators_for_tier(tier: ValidationTier) -> list[str]:
        """Return the list of validator names for a given tier."""
        if tier == ValidationTier.A:
            return ["duplicate", "timestamp", "continuity", "schema", "corruption"]
        elif tier == ValidationTier.B:
            return ["duplicate", "timestamp", "continuity", "schema"]
        else:  # Tier C
            return ["schema", "timestamp"]

    def _run_validator(
        self,
        name: str,
        record: dict[str, Any],
        last_timestamp: datetime | None,
    ) -> ValidationResult:
        """Run a single validator by name."""
        if name == "duplicate":
            return validate_duplicate(record, self._store)
        elif name == "timestamp":
            return validate_timestamp(record, last_timestamp)
        elif name == "continuity":
            feed_type = record.get("feed_type", "unknown")
            return validate_continuity(record, last_timestamp, feed_type)
        elif name == "schema":
            return validate_schema(record)
        elif name == "corruption":
            return validate_corruption(record)
        else:
            return ValidationResult(
                validator_name=name,
                passed=True,
                details={"error": f"Unknown validator: {name}"},
                confidence=0.0,
            )

    @staticmethod
    def _aggregate(
        results: list[ValidationResult],
    ) -> tuple[ValidationDecision, float]:
        """Aggregate individual results into a single decision.

        Rules:
        - If ANY validator FAILED (``passed=False``) → ``FAIL``.
        - If ALL passed → ``PASS``.
        - ``FLAG`` is reserved for future use (e.g., a validator passes
          but notes something worth reviewing).

        Returns:
            Tuple of ``(decision, validation_confidence)``.
        """
        if not results:
            return ValidationDecision.PASS, 1.0

        passed_count = sum(1 for r in results if r.passed)
        confidence = passed_count / len(results)

        has_failure = any(not r.passed for r in results)

        if has_failure:
            return ValidationDecision.FAIL, confidence

        return ValidationDecision.PASS, confidence
