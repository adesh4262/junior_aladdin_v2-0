"""Floor 2 Structuring — major/minor classifier.

Classifies data feeds and streams as ``MAJOR`` or ``MINOR`` based on
the Data Contract Registry's data class mapping.

**MAJOR** data:
- tick data, candle streams, options chain / OI snapshots, core market feeds

**MINOR** data:
- support feeds, auxiliary feeds, secondary references, slower contextual packets

Architecture rules:
- Classification applies to BOTH storage and processing priority.
- MAJOR data gets stricter validation, longer retention, and higher replay priority.
- Classification is based on ``FEED_TYPE_TO_DATA_CLASS`` in the contract registry.
"""

from __future__ import annotations

from typing import Any

from junior_aladdin.floor_2_datacenter.datacenter_contracts import (
    get_data_class_for_feed,
)
from junior_aladdin.floor_2_datacenter.datacenter_types import DataClass, StreamType
from junior_aladdin.shared.logging import get_logger

logger = get_logger("major_minor_classifier")


def classify_feed(feed_type: str) -> DataClass:
    """Classify a feed type as MAJOR or MINOR.

    Args:
        feed_type: The feed type string (e.g., ``\"spot_tick\"``).

    Returns:
        ``DataClass.MAJOR`` or ``DataClass.MINOR``.
    """
    class_str = get_data_class_for_feed(feed_type)
    return DataClass(class_str)


def classify_stream(stream_type: StreamType) -> DataClass:
    """Classify a stream type as MAJOR or MINOR.

    ``StreamType`` → default classification:
    - ``TICK_STREAM`` → MAJOR
    - ``CANDLE_STREAM`` → MAJOR
    - ``OPTIONS_SNAPSHOT`` → MAJOR
    - ``SESSION_PACKET`` → MINOR
    - ``MACRO_SUPPORT`` → MINOR

    Args:
        stream_type: The stream type enum value.

    Returns:
        ``DataClass.MAJOR`` or ``DataClass.MINOR``.
    """
    stream_to_data_class: dict[StreamType, DataClass] = {
        StreamType.TICK_STREAM: DataClass.MAJOR,
        StreamType.CANDLE_STREAM: DataClass.MAJOR,
        StreamType.OPTIONS_SNAPSHOT: DataClass.MAJOR,
        StreamType.SESSION_PACKET: DataClass.MINOR,
        StreamType.MACRO_SUPPORT: DataClass.MINOR,
    }
    return stream_to_data_class.get(stream_type, DataClass.MINOR)


def is_major(feed_type: str) -> bool:
    """Convenience: check if a feed type is MAJOR.

    Args:
        feed_type: The feed type string.

    Returns:
        ``True`` if the feed type is classified as MAJOR.
    """
    return classify_feed(feed_type) == DataClass.MAJOR


def is_minor(feed_type: str) -> bool:
    """Convenience: check if a feed type is MINOR.

    Args:
        feed_type: The feed type string.

    Returns:
        ``True`` if the feed type is classified as MINOR.
    """
    return classify_feed(feed_type) == DataClass.MINOR


def classify_structure_result(result: StructureResult) -> DataClass:
    """Classify a ``StructureResult`` based on its stream type.

    Args:
        result: A ``StructureResult`` from any builder.

    Returns:
        ``DataClass.MAJOR`` or ``DataClass.MINOR``.
    """
    return classify_stream(result.stream_type)
