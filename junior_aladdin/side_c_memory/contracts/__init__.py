"""Side C Memory Layer — contracts package.

Contains:
- ``emitter_registry.py`` — approved emitter definitions (Step 3.2)
- ``write_contracts.py`` — write contracts per event family (Step 3.2)
- ``read_contracts.py`` — read contracts per query type (Step 3.11)
"""

from junior_aladdin.side_c_memory.contracts.emitter_registry import (
    family_allowed_for_emitter,
    get_allowed_families,
    get_emitter_info,
    is_emitter_approved,
    list_approved_emitters,
    register_emitter,
)
from junior_aladdin.side_c_memory.contracts.read_contracts import (
    ReadContract,
    get_read_contract,
    list_query_types,
    validate_query,
)
from junior_aladdin.side_c_memory.contracts.write_contracts import (
    WriteContract,
    FieldSpec,
    get_write_contract,
    list_contract_families,
    validate_event_for_family,
)

__all__ = [
    # emitter_registry
    "family_allowed_for_emitter",
    "get_allowed_families",
    "get_emitter_info",
    "is_emitter_approved",
    "list_approved_emitters",
    "register_emitter",
    # read_contracts
    "ReadContract",
    "get_read_contract",
    "list_query_types",
    "validate_query",
    # write_contracts
    "FieldSpec",
    "WriteContract",
    "get_write_contract",
    "list_contract_families",
    "validate_event_for_family",
]
