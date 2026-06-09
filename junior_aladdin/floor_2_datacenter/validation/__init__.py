"""Validation pipeline — duplicate, timestamp, continuity, schema, and corruption validators.

Exports:
- :func:`validate_duplicate` — Check if packet_id already exists in store.
- :func:`validate_timestamp` — Check timestamp validity and ordering.
- :func:`validate_continuity` — Check for gaps in packet sequence.
- :func:`validate_schema` — Check raw data against feed contract schema.
- :func:`validate_corruption` — Check for NaN, Inf, None, type mismatches.
- :class:`ValidationRouter` — Route packets through applicable validators
  by ``ValidationTier`` (A=5, B=4, C=2).
"""

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
from junior_aladdin.floor_2_datacenter.validation.validation_router import (
    ValidationRouter,
)

__all__ = [
    "validate_continuity",
    "validate_corruption",
    "validate_duplicate",
    "validate_schema",
    "validate_timestamp",
    "ValidationRouter",
]
