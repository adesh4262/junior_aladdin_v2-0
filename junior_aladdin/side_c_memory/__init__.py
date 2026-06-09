"""Junior Aladdin — Side C: Memory / Journal Layer.

Side C is the system's durable structured memory.  It stores events,
journals, and references from approved emitters (Floors 1, 2, 5 and
Side A) and exposes queryable read models for Side B consumption.

Architecture rules (LOCKED):
- Side C stores facts, does NOT create truth.
- Side C remembers, does NOT decide.
- Side C links, does NOT interpret.
- Append-first only — no mutation, no deletion.
- Approved emitters only — no arbitrary writes.
- Side B consumes through READ MODELS only, never raw stores.
"""

from junior_aladdin.shared.types import MemoryEvent

from junior_aladdin.side_c_memory.c_types import (
    DEFAULT_RETENTION_POLICIES,
    EventFamily,
    MemoryEnvelope,
    MemoryQuery,
    ReadModelSummary,
    RetentionPolicy,
)
from junior_aladdin.side_c_memory.ingest_layer import (
    ingest_event,
    set_event_router,
)
from junior_aladdin.side_c_memory.event_router import (
    get_families_for_store,
    get_routing_rule,
    list_routing_rules,
    route_event,
    set_store_callback,
)
from junior_aladdin.side_c_memory.event_store import (
    append_event,
    clear as clear_event_store,
    count_events,
    get_event,
    query_events,
)
from junior_aladdin.side_c_memory.journal_store import (
    append_journal,
    clear as clear_journal_store,
    count_journals,
    get_journal,
    query_journals,
)
from junior_aladdin.side_c_memory.reference_store import (
    clear as clear_reference_store,
    get_reference,
    lookup_by_key,
    query_references,
    store_reference,
)
from junior_aladdin.side_c_memory.query_layer import (
    get_decision_history,
    get_health_timeline,
    get_trade_history,
    query as query_cross_store,
)
from junior_aladdin.side_c_memory.read_model_builder import (
    build_blocked_actions_summary,
    build_decision_review_summary,
    build_health_timeline_summary,
    build_override_history_summary,
    build_trade_history_summary,
)
from junior_aladdin.side_c_memory.retention_manager import (
    apply_retention_policy,
    get_retention_status,
    set_retention_policy,
)

__all__ = [
    "DEFAULT_RETENTION_POLICIES",
    "EventFamily",
    "MemoryEnvelope",
    "MemoryEvent",
    "MemoryQuery",
    "ReadModelSummary",
    "RetentionPolicy",
    # ingest
    "ingest_event",
    "set_event_router",
    # router
    "get_families_for_store",
    "get_routing_rule",
    "list_routing_rules",
    "route_event",
    "set_store_callback",
    # event_store
    "append_event",
    "clear_event_store",
    "count_events",
    "get_event",
    "query_events",
    # journal_store
    "append_journal",
    "clear_journal_store",
    "count_journals",
    "get_journal",
    "query_journals",
    # reference_store
    "clear_reference_store",
    "get_reference",
    "lookup_by_key",
    "query_references",
    "store_reference",
    # query_layer
    "get_decision_history",
    "get_health_timeline",
    "get_trade_history",
    "query_cross_store",
    # read_model_builder
    "build_blocked_actions_summary",
    "build_decision_review_summary",
    "build_health_timeline_summary",
    "build_override_history_summary",
    "build_trade_history_summary",
    # retention_manager
    "apply_retention_policy",
    "get_retention_status",
    "set_retention_policy",
]
