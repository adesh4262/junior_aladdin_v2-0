"""Data source adapters for Side B API.

Each adapter polls data from its respective floor/side and returns
normalized response schemas defined in ``data_contracts.py``.

Adapters are designed to be resilient:
- If a floor/side module is not available, return graceful default/error state
- Never crash the polling cycle
- Log warnings on failure, never exceptions

Reference: ROADMAP_SIDE_B Step 8.2
"""

from __future__ import annotations

from junior_aladdin.side_b_api.data_sources.floor_1_source import poll_floor_1
from junior_aladdin.side_b_api.data_sources.floor_2_source import poll_floor_2
from junior_aladdin.side_b_api.data_sources.floor_3_source import poll_floor_3
from junior_aladdin.side_b_api.data_sources.floor_4_source import poll_floor_4
from junior_aladdin.side_b_api.data_sources.floor_5_source import poll_floor_5
from junior_aladdin.side_b_api.data_sources.side_a_source import poll_side_a
from junior_aladdin.side_b_api.data_sources.side_c_source import poll_side_c

__all__ = [
    "poll_floor_1",
    "poll_floor_2",
    "poll_floor_3",
    "poll_floor_4",
    "poll_floor_5",
    "poll_side_a",
    "poll_side_c",
]
