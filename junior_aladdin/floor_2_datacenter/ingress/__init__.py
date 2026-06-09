"""Ingress sub-system — accepts Floor 1 packets, normalizes envelopes, monitors ingress.

Exports:
- :func:`build_source_envelope` — Normalise Floor 1 5-family payload into
  ``Floor2IngestPayload`` with ingest metadata.
- :class:`IngressMonitor` — Track ingress metrics (counts, rates, errors)
  and detect flow anomalies (drop/surge).
- :class:`RawIngestRouter` — Orchestrate the full ingest pipeline:
  validate → normalize → record metrics → route to downstream.
"""

from junior_aladdin.floor_2_datacenter.ingress.ingress_monitor import IngressMonitor
from junior_aladdin.floor_2_datacenter.ingress.raw_ingest_router import RawIngestRouter
from junior_aladdin.floor_2_datacenter.ingress.source_envelope_builder import (
    build_source_envelope,
)

__all__ = [
    "build_source_envelope",
    "IngressMonitor",
    "RawIngestRouter",
]
