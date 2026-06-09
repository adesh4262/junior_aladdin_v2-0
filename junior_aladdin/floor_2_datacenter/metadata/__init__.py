"""Metadata side-channel — quality facts, traceability, transform stage tracking.

SIDE C: Metadata side-channel sub-system (Step 2.7).

Provides packet-level metadata (size, source, timing), source lineage,
transform stage progression, quality facts from pipeline results, and
retention summaries.
"""

from junior_aladdin.floor_2_datacenter.metadata.packet_metadata_builder import (
    build_packet_metadata,
    build_packet_metadata_batch,
)
from junior_aladdin.floor_2_datacenter.metadata.quality_fact_builder import (
    build_quality_facts,
)
from junior_aladdin.floor_2_datacenter.metadata.retention_metadata_builder import (
    build_feed_storage_report,
    build_retention_summary,
)
from junior_aladdin.floor_2_datacenter.metadata.source_trace_builder import (
    build_source_trace,
    build_source_trace_batch,
)
from junior_aladdin.floor_2_datacenter.metadata.transform_stage_tracker import (
    TransformStageTracker,
)

__all__ = [
    "TransformStageTracker",
    "build_feed_storage_report",
    "build_packet_metadata",
    "build_packet_metadata_batch",
    "build_quality_facts",
    "build_retention_summary",
    "build_source_trace",
    "build_source_trace_batch",
]
