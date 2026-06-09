"""ICT — Kill Zone Calculator.

Calculates active and upcoming ICT Kill Zones based on configurable IST
time windows and an input timestamp.

Kill Zones (IST = UTC+5:30):
- ASIAN:        02:30 – 09:15  (Asian session range)
- LONDON_OPEN:  12:30 – 14:30  (London Open liquidity grab)
- NY_AM_OPEN:   17:30 – 20:00  (New York AM Open)
- NY_PM_CLOSE:  22:00 – 23:00  (New York PM Close / power hour)

Each zone has a configurable buffer (kill_zone_buffer_minutes) applied to
start/end boundaries. Zones wrap around midnight — the calculator handles
this correctly so that, e.g., ASIAN (02:30–09:15) on today works, and
NY_PM_CLOSE (22:00–23:00) correctly ends the same day.

Architecture rules:
- Pure functions — no state, no external calls, no side effects.
- Timezone-aware — input timestamps treated as UTC, converted to IST.
- Same input + config → same output (deterministic).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from junior_aladdin.floor_3_calculations.f3_config import IctParameters
from junior_aladdin.floor_3_calculations.f3_types import KillZone, KillZoneType


# ── Module-level constants ──────────────────────────────────────────────────
_IST_OFFSET = timedelta(hours=5, minutes=30)  # UTC+5:30
_UTC = timezone.utc


# =============================================================================
# PUBLIC API
# =============================================================================


def get_kill_zones(
    timestamp: datetime,
    params: IctParameters | None = None,
) -> list[KillZone]:
    """Get ALL kill zones with their active status for a given timestamp.

    Evaluates every defined kill zone against the provided timestamp.
    Zones that wrap past midnight (e.g., a hypothetical 23:30–00:30 zone)
    are handled correctly — the start/end times are compared on the same
    calendar day.

    Args:
        timestamp: The reference timestamp (treated as UTC, converted to IST).
        params: ICT parameters with kill zone times and buffer.
            If ``None``, uses default ``IctParameters()``.

    Returns:
        A list of 4 ``KillZone`` objects, one per zone type, sorted
        by their start time (ASIAN → LONDON → NY_AM → NY_PM).
    """
    if params is None:
        params = IctParameters()

    local_dt = _to_ist(timestamp)
    buffer = timedelta(minutes=params.kill_zone_buffer_minutes)

    zones = _build_all_zones(local_dt.date(), params)

    result: list[KillZone] = []
    for ztype, start_ist, end_ist in zones:
        # Apply buffer: start is moved EARLIER, end is moved LATER
        buffered_start = start_ist - buffer
        buffered_end = end_ist + buffer

        is_active = buffered_start <= local_dt < buffered_end
        remaining = 0.0
        if is_active:
            remaining = (buffered_end - local_dt).total_seconds()
            remaining = max(remaining, 0.0)

        result.append(KillZone(
            kill_zone_type=ztype,
            start_time=buffered_start,
            end_time=buffered_end,
            active=is_active,
            time_remaining_s=remaining,
        ))

    return result


def get_active_kill_zones(
    timestamp: datetime,
    params: IctParameters | None = None,
) -> list[KillZone]:
    """Get currently active kill zones for a given timestamp.

    Filters the full list of kill zones to only those where
    ``active=True``.

    Args:
        timestamp: The reference timestamp (treated as UTC, converted to IST).
        params: ICT parameters with kill zone times and buffer.

    Returns:
        A list of active ``KillZone`` objects. Empty list if none active.
    """
    return [
        z for z in get_kill_zones(timestamp, params)
        if z.active
    ]


def get_next_kill_zone(
    timestamp: datetime,
    params: IctParameters | None = None,
) -> KillZone | None:
    """Get the next upcoming kill zone (not yet active, closest in time).

    If a kill zone is currently active, returns that active zone instead
    of a future one — an active zone is the \"next\" in terms of trader
    context. If multiple are active, returns the earliest-starting one.

    Args:
        timestamp: The reference timestamp (treated as UTC, converted to IST).
        params: ICT parameters with kill zone times and buffer.

    Returns:
        The next relevant ``KillZone``, or ``None`` if no zones remain
        today (after NY PM Close).
    """
    if params is None:
        params = IctParameters()

    local_dt = _to_ist(timestamp)
    buffer = timedelta(minutes=params.kill_zone_buffer_minutes)

    zones = _build_all_zones(local_dt.date(), params)

    # First pass: return the first currently active zone
    for ztype, start_ist, end_ist in zones:
        buffered_start = start_ist - buffer
        buffered_end = end_ist + buffer
        if buffered_start <= local_dt < buffered_end:
            remaining = max(0.0, (buffered_end - local_dt).total_seconds())
            return KillZone(
                kill_zone_type=ztype,
                start_time=buffered_start,
                end_time=buffered_end,
                active=True,
                time_remaining_s=remaining,
            )

    # Second pass: return the first future zone
    for ztype, start_ist, end_ist in zones:
        buffered_start = start_ist - buffer
        buffered_end = end_ist + buffer
        if local_dt < buffered_start:
            remaining = (buffered_end - local_dt).total_seconds()
            return KillZone(
                kill_zone_type=ztype,
                start_time=buffered_start,
                end_time=buffered_end,
                active=False,
                time_remaining_s=remaining,
            )

    # No more zones today
    return None


def is_kill_zone_active(
    timestamp: datetime,
    zone_type: KillZoneType,
    params: IctParameters | None = None,
) -> bool:
    """Check whether a specific kill zone type is currently active.

    Args:
        timestamp: The reference timestamp (treated as UTC, converted to IST).
        zone_type: The kill zone type to check.
        params: ICT parameters with kill zone times and buffer.

    Returns:
        ``True`` if the specified zone is active at the given timestamp.
    """
    zones = get_active_kill_zones(timestamp, params)
    return any(z.kill_zone_type == zone_type for z in zones)


# =============================================================================
# INTERNAL
# =============================================================================

_KILL_ZONE_DEFS: list[tuple[KillZoneType, str, str]] = [
    (KillZoneType.ASIAN,        "asian_range_start",    "asian_range_end"),
    (KillZoneType.LONDON_OPEN,  "london_open_start",    "london_open_end"),
    (KillZoneType.NY_AM_OPEN,   "ny_am_open_start",     "ny_am_open_end"),
    (KillZoneType.NY_PM_CLOSE,  "ny_pm_close_start",    "ny_pm_close_end"),
]


def _build_all_zones(
    reference_date: Any,
    params: IctParameters,
) -> list[tuple[KillZoneType, datetime, datetime]]:
    """Build (type, start_ist, end_ist) tuples for all zones on a date.

    Args:
        reference_date: A ``datetime.date`` or ``datetime`` whose date
            portion is used as the reference day.
        params: ICT parameters with kill zone time strings.

    Returns:
        List of ``(KillZoneType, start_datetime, end_datetime)`` tuples
        with IST-aware datetimes.
    """
    # Extract date from whatever type was passed
    if isinstance(reference_date, datetime):
        date = reference_date.date()
    else:
        date = reference_date  # assume it's already a date

    zones: list[tuple[KillZoneType, datetime, datetime]] = []
    for ztype, start_key, end_key in _KILL_ZONE_DEFS:
        start_str: str = getattr(params, start_key)
        end_str: str = getattr(params, end_key)
        start_ist = _parse_ist_time(start_str, date)
        end_ist = _parse_ist_time(end_str, date)

        # If end is <= start, it wraps to the next day
        if end_ist <= start_ist:
            end_ist += timedelta(days=1)

        zones.append((ztype, start_ist, end_ist))

    return zones


def _to_ist(dt: datetime) -> datetime:
    """Convert a datetime to IST (UTC+5:30).

    If the input is naive (no tzinfo), it is assumed to be UTC.

    Args:
        dt: The datetime to convert (UTC or timezone-aware).

    Returns:
        A naive datetime representing the same moment in IST.
    """
    if dt.tzinfo is None:
        # Assume UTC for naive datetimes
        dt = dt.replace(tzinfo=_UTC)
    return dt.astimezone(timezone(_IST_OFFSET)).replace(tzinfo=None)


def _parse_ist_time(time_str: str, date: Any) -> datetime:
    """Parse an ``\"HH:MM\"`` string into an IST datetime on the given date.

    Args:
        time_str: Time string in ``\"HH:MM\"`` 24-hour format.
        date: A ``datetime.date`` object.

    Returns:
        A naive datetime representing the given time in IST on the date.

    Raises:
        ValueError: If the time string is not in ``\"HH:MM\"`` format.
    """
    parts = time_str.split(":")
    if len(parts) != 2:
        raise ValueError(f"invalid time format {time_str!r}, expected HH:MM")
    try:
        hour = int(parts[0])
        minute = int(parts[1])
    except (ValueError, TypeError) as exc:
        raise ValueError(f"invalid time format {time_str!r}") from exc

    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError(f"time out of range {time_str!r}")

    return datetime(date.year, date.month, date.day, hour, minute)
