"""Junior Aladdin — Central Trading Calendar.

SINGLE SOURCE OF TRUTH for time-related market intelligence.
Every floor/side queries THIS module for calendar context.

Provides:
- IST timezone handling (UTC+5:30)
- NSE holiday calendar
- Weekly/Monthly expiry detection
- High-impact economic events (FOMC, Budget, RBI)
- Market open/close hours
- Session awareness (pre-open, open, lunch, closing, post-close)
- Countdown to next event / expiry

Architecture rules:
- Pure functions — no state, no side effects.
- Static event lists — updated once per year.
- Any floor can import and query this module directly.
- Floor 3 Macro domain wraps this into CalculatedSignals.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from enum import Enum
from typing import Any


# =============================================================================
# CONSTANTS
# =============================================================================

# India Standard Time (UTC +5:30)
IST = timezone(timedelta(hours=5, minutes=30))

# NSE Market hours (IST)
MARKET_OPEN_TIME = time(9, 15)    # 9:15 AM IST
MARKET_CLOSE_TIME = time(15, 30)  # 3:30 PM IST
PRE_OPEN_START = time(9, 0)       # 9:00 AM IST
POST_CLOSE_END = time(16, 0)      # 4:00 PM IST (buffer after close)


class EventType(Enum):
    """Classification of calendar events by impact level."""
    HOLIDAY = "HOLIDAY"            # Market closed
    EXPIRY = "EXPIRY"              # Weekly/Monthly expiry
    ECONOMIC_HIGH = "ECONOMIC_HIGH"  # Budget, RBI policy, FOMC
    ECONOMIC_MED = "ECONOMIC_MED"    # CPI, IIP, GDP data
    CORPORATE = "CORPORATE"          # Result season, IPO
    ROLLOVER = "ROLLOVER"            # F&O rollover week
    SETTLEMENT = "SETTLEMENT"       # Monthly settlement


class SessionState(Enum):
    """Current market session state."""
    PRE_MARKET = "PRE_MARKET"       # Before 9:00 AM
    PRE_OPEN = "PRE_OPEN"           # 9:00 - 9:15 AM
    OPEN = "OPEN"                    # 9:15 AM - 12:00 PM
    LUNCH = "LUNCH"                  # 12:00 - 1:00 PM
    CLOSING = "CLOSING"             # 1:00 - 3:30 PM
    POST_CLOSE = "POST_CLOSE"       # After 3:30 PM
    CLOSED = "CLOSED"               # Holiday / Weekend


# =============================================================================
# DATA CLASSES
# =============================================================================


@dataclass
class CalendarEvent:
    """A single calendar event entry.

    Fields:
        date: The date of the event.
        event_type: Classification of the event.
        name: Human-readable event name.
        description: Optional detailed description.
        risk_level: Optional risk level (0.0–1.0) for Captain context.
    """
    date: date
    event_type: EventType
    name: str
    description: str = ""
    risk_level: float = 0.0


@dataclass
class MarketSession:
    """Current market session information.

    Fields:
        session_state: Current session state.
        is_market_open: Whether the market is currently open for trading.
        is_holiday_today: Whether today is a trading holiday.
        is_expiry_today: Whether today is an expiry day.
        is_expiry_week: Whether we are in expiry week (Thu-Mon).
        is_rollover_week: Whether we are in rollover week.
        next_event: Name of the next upcoming event.
        next_event_date: Date of the next event.
        days_to_next_event: Days until the next event.
        time_to_market_open: Seconds until market opens (0 if open).
        time_to_market_close: Seconds until market closes (0 if closed).
        events_today: List of events happening today.
    """
    session_state: SessionState
    is_market_open: bool
    is_holiday_today: bool
    is_expiry_today: bool
    is_expiry_week: bool
    is_rollover_week: bool
    next_event: str = ""
    next_event_date: str = ""
    days_to_next_event: int = 999
    time_to_market_open: float = 0.0
    time_to_market_close: float = 0.0
    events_today: list[dict[str, Any]] = field(default_factory=list)


# =============================================================================
# EVENT DATA — NSE HOLIDAYS 2026 (India)
# =============================================================================

# NSE Trading Holidays 2026
NSE_HOLIDAYS_2026: list[date] = [
    date(2026, 1, 26),   # Republic Day
    date(2026, 2, 28),   # Maha Shivaratri
    date(2026, 3, 13),   # Holi
    date(2026, 3, 31),   # Id-ul-Fitr
    date(2026, 4, 14),   # Dr. Babasaheb Ambedkar Jayanti
    date(2026, 5, 1),    # Maharashtra Day
    date(2026, 8, 15),   # Independence Day
    date(2026, 8, 19),   # Ganesh Chaturthi
    date(2026, 9, 7),    # Id-ul-Zuha (Bakrid)
    date(2026, 10, 2),   # Mahatma Gandhi Jayanti
    date(2026, 10, 22),  # Dasara
    date(2026, 11, 9),   # Diwali / Laxmi Puja
    date(2026, 11, 10),  # Diwali Balipratipada
    date(2026, 11, 26),  # Guru Nanak Jayanti
    date(2026, 12, 25),  # Christmas
]

# High-impact economic events 2026 (approximate dates — update as announced)
ECONOMIC_EVENTS_2026: list[CalendarEvent] = [
    # Union Budget (typically Feb 1)
    CalendarEvent(date(2026, 2, 1), EventType.ECONOMIC_HIGH, "Union Budget",
                  "Annual Union Budget presentation", risk_level=0.8),
    # RBI Monetary Policy (bi-monthly — approximate months)
    CalendarEvent(date(2026, 2, 7), EventType.ECONOMIC_HIGH, "RBI Policy",
                  "RBI Monetary Policy announcement", risk_level=0.6),
    CalendarEvent(date(2026, 4, 6), EventType.ECONOMIC_HIGH, "RBI Policy",
                  "RBI Monetary Policy announcement", risk_level=0.6),
    CalendarEvent(date(2026, 6, 5), EventType.ECONOMIC_HIGH, "RBI Policy",
                  "RBI Monetary Policy announcement", risk_level=0.6),
    CalendarEvent(date(2026, 8, 7), EventType.ECONOMIC_HIGH, "RBI Policy",
                  "RBI Monetary Policy announcement", risk_level=0.6),
    CalendarEvent(date(2026, 10, 5), EventType.ECONOMIC_HIGH, "RBI Policy",
                  "RBI Monetary Policy announcement", risk_level=0.6),
    CalendarEvent(date(2026, 12, 5), EventType.ECONOMIC_HIGH, "RBI Policy",
                  "RBI Monetary Policy announcement", risk_level=0.6),
    # FOMC (approximate months)
    CalendarEvent(date(2026, 1, 28), EventType.ECONOMIC_HIGH, "FOMC Meeting",
                  "US Federal Reserve policy decision", risk_level=0.7),
    CalendarEvent(date(2026, 3, 18), EventType.ECONOMIC_HIGH, "FOMC Meeting",
                  "US Federal Reserve policy decision", risk_level=0.7),
    CalendarEvent(date(2026, 5, 6), EventType.ECONOMIC_HIGH, "FOMC Meeting",
                  "US Federal Reserve policy decision", risk_level=0.7),
    CalendarEvent(date(2026, 6, 17), EventType.ECONOMIC_HIGH, "FOMC Meeting",
                  "US Federal Reserve policy decision", risk_level=0.7),
    CalendarEvent(date(2026, 7, 29), EventType.ECONOMIC_HIGH, "FOMC Meeting",
                  "US Federal Reserve policy decision", risk_level=0.7),
    CalendarEvent(date(2026, 9, 16), EventType.ECONOMIC_HIGH, "FOMC Meeting",
                  "US Federal Reserve policy decision", risk_level=0.7),
    CalendarEvent(date(2026, 11, 5), EventType.ECONOMIC_HIGH, "FOMC Meeting",
                  "US Federal Reserve policy decision", risk_level=0.7),
    CalendarEvent(date(2026, 12, 16), EventType.ECONOMIC_HIGH, "FOMC Meeting",
                  "US Federal Reserve policy decision", risk_level=0.7),
]

# NSE F&O expiry — typically THURSDAY of each week for weekly contracts
# Monthly expiry is last Thursday of the month
# If Thursday is a holiday, expiry moves to Wednesday

WEEKLY_EXPIRY_DAY = 3  # Thursday (Monday=0, Sunday=6)
MONTHLY_EXPIRY_DATES_2026: list[date] = [
    date(2026, 1, 29), date(2026, 2, 26), date(2026, 3, 26),
    date(2026, 4, 30), date(2026, 5, 28), date(2026, 6, 25),
    date(2026, 7, 30), date(2026, 8, 27), date(2026, 9, 24),
    date(2026, 10, 29), date(2026, 11, 26), date(2026, 12, 31),
]


# =============================================================================
# PUBLIC API
# =============================================================================


def get_today() -> date:
    """Get today's date in IST timezone.

    Returns:
        Today's date in IST.
    """
    return datetime.now(IST).date()


def get_now() -> datetime:
    """Get current datetime in IST timezone.

    Returns:
        Current datetime in IST.
    """
    return datetime.now(IST)


def is_weekend(check_date: date | None = None) -> bool:
    """Check if a date falls on a weekend.

    Args:
        check_date: Date to check. Uses today if None.

    Returns:
        True if the date is Saturday or Sunday.
    """
    d = check_date or get_today()
    return d.weekday() >= 5  # Saturday=5, Sunday=6


def is_holiday(check_date: date | None = None) -> bool:
    """Check if a date is an NSE trading holiday.

    Args:
        check_date: Date to check. Uses today if None.

    Returns:
        True if the date is a holiday.
    """
    d = check_date or get_today()
    return d in NSE_HOLIDAYS_2026


def is_market_open(check_datetime: datetime | None = None) -> bool:
    """Check if the market is currently open for trading.

    Market hours: 9:15 AM to 3:30 PM IST, Monday-Friday,
    excluding NSE holidays.

    Args:
        check_datetime: Datetime to check. Uses current IST time if None.

    Returns:
        True if the market is open for trading.
    """
    dt = check_datetime or get_now()
    d = dt.date()

    # Weekends and holidays — market closed
    if is_weekend(d) or is_holiday(d):
        return False

    # Check market hours (9:15 AM - 3:30 PM IST)
    t = dt.time()
    return MARKET_OPEN_TIME <= t <= MARKET_CLOSE_TIME


def get_expiry_dates(year: int = 2026) -> list[date]:
    """Get all weekly expiry dates for the year.

    Weekly Nifty expiry is every Thursday.
    If Thursday is a holiday, expiry is Wednesday.
    Monthly expiry is last Thursday of the month.

    Args:
        year: The year to calculate expiry dates for.

    Returns:
        List of expiry dates (weekly + monthly).
    """
    if year == 2026:
        # Use pre-defined monthly dates + calculate weekly
        monthly_set = set(MONTHLY_EXPIRY_DATES_2026)
        all_expiries: list[date] = []

        # Start from first Thursday of January
        jan1 = date(year, 1, 1)
        days_until_thu = (WEEKLY_EXPIRY_DAY - jan1.weekday()) % 7
        first_thu = jan1 + timedelta(days=days_until_thu)

        # Generate all Thursdays
        current = first_thu
        while current.year == year:
            # If Thursday is a holiday, previous day (Wednesday) is expiry
            if current in NSE_HOLIDAYS_2026:
                expiry = current - timedelta(days=1)
            else:
                expiry = current

            all_expiries.append(expiry)

            # Also add monthly expiry if different from weekly
            # AND if it's not a holiday (holiday expiry already moved above)
            if current in monthly_set and current != expiry:
                monthly_actual = current
                # Skip if monthly expiry itself is a holiday
                if monthly_actual not in all_expiries and not is_holiday(monthly_actual):
                    all_expiries.append(monthly_actual)

            current += timedelta(days=7)

        return sorted(set(all_expiries))

    # Generic calculation for other years
    monthly_set = set()
    for m in range(1, 13):
        # Last day of month
        if m == 12:
            last_day = date(year, 12, 31)
        else:
            last_day = date(year, m + 1, 1) - timedelta(days=1)
        # Find last Thursday
        days_back = (last_day.weekday() - WEEKLY_EXPIRY_DAY) % 7
        last_thu = last_day - timedelta(days=days_back)
        monthly_set.add(last_thu)

    jan1 = date(year, 1, 1)
    days_until_thu = (WEEKLY_EXPIRY_DAY - jan1.weekday()) % 7
    first_thu = jan1 + timedelta(days=days_until_thu)

    all_expiries: list[date] = []
    current = first_thu
    while current.year == year:
        if current in NSE_HOLIDAYS_2026:
            expiry = current - timedelta(days=1)
        else:
            expiry = current
        all_expiries.append(expiry)
        if current in monthly_set and current != expiry:
            monthly_actual = current
            if monthly_actual not in all_expiries:
                all_expiries.append(monthly_actual)
        current += timedelta(days=7)

    return sorted(set(all_expiries))


def is_expiry_day(check_date: date | None = None) -> bool:
    """Check if a date is an expiry day.

    Args:
        check_date: Date to check. Uses today if None.

    Returns:
        True if the date is an expiry day.
    """
    d = check_date or get_today()
    return d in get_expiry_dates(d.year)


def is_monthly_expiry(check_date: date | None = None) -> bool:
    """Check if a date is a MONTHLY expiry day.

    Args:
        check_date: Date to check. Uses today if None.

    Returns:
        True if the date is a monthly expiry.
    """
    d = check_date or get_today()
    return d in MONTHLY_EXPIRY_DATES_2026


def is_expiry_week(check_date: date | None = None) -> bool:
    """Check if we are in expiry week.

    Expiry week = Thursday to Monday (before and after expiry).
    High volatility / gamma effects expected.

    Args:
        check_date: Date to check. Uses today if None.

    Returns:
        True if within expiry week range.
    """
    d = check_date or get_today()
    expiries = get_expiry_dates(d.year)

    for ex in expiries:
        # Expiry week: Mon-Thursday (or Wed if holiday)
        week_start = ex - timedelta(days=3)  # Monday before expiry
        week_end = ex + timedelta(days=1)     # Friday after expiry
        if week_start <= d <= week_end:
            return True

    return False


def is_rollover_week(check_date: date | None = None) -> bool:
    """Check if we are in F&O rollover week.

    Rollover week = last 5 trading days before monthly expiry.
    Higher volumes, increased volatility expected.

    Args:
        check_date: Date to check. Uses today if None.

    Returns:
        True if within rollover week.
    """
    d = check_date or get_today()

    for monthly_expiry in MONTHLY_EXPIRY_DATES_2026:
        # Rollover week: 5 trading days before monthly expiry
        rollover_start = monthly_expiry - timedelta(days=7)
        # Skip weekends and holidays
        check = rollover_start
        trading_days = 0
        while check <= monthly_expiry:
            if not is_weekend(check) and not is_holiday(check):
                trading_days += 1
            check += timedelta(days=1)

        if d >= rollover_start and d <= monthly_expiry and trading_days <= 7:
            return True

    return False


def get_session_state(check_datetime: datetime | None = None) -> SessionState:
    """Determine current market session state.

    Args:
        check_datetime: Datetime to check. Uses current IST time if None.

    Returns:
        Current SessionState.
    """
    dt = check_datetime or get_now()
    d = dt.date()
    t = dt.time()

    # Weekend or holiday = CLOSED
    if is_weekend(d) or is_holiday(d):
        return SessionState.CLOSED

    # Determine session by time
    if t < PRE_OPEN_START:
        return SessionState.PRE_MARKET
    elif PRE_OPEN_START <= t < MARKET_OPEN_TIME:
        return SessionState.PRE_OPEN
    elif MARKET_OPEN_TIME <= t < time(12, 0):
        return SessionState.OPEN
    elif time(12, 0) <= t < time(13, 0):
        return SessionState.LUNCH
    elif time(13, 0) <= t <= MARKET_CLOSE_TIME:
        return SessionState.CLOSING
    elif MARKET_CLOSE_TIME < t <= POST_CLOSE_END:
        return SessionState.POST_CLOSE
    else:
        return SessionState.CLOSED


def get_events_for_date(event_date: date | None = None) -> list[CalendarEvent]:
    """Get all calendar events for a specific date.

    Includes: holidays, expiry, economic events, corporate events.

    Args:
        event_date: Date to query. Uses today if None.

    Returns:
        List of CalendarEvent objects for the specified date.
    """
    d = event_date or get_today()
    events: list[CalendarEvent] = []

    # Check if holiday
    if d in NSE_HOLIDAYS_2026:
        # Find the holiday name
        holiday_names: dict[date, str] = {
            date(2026, 1, 26): "Republic Day",
            date(2026, 2, 28): "Maha Shivaratri",
            date(2026, 3, 13): "Holi",
            date(2026, 3, 31): "Id-ul-Fitr",
            date(2026, 4, 14): "Dr. Babasaheb Ambedkar Jayanti",
            date(2026, 5, 1): "Maharashtra Day",
            date(2026, 8, 15): "Independence Day",
            date(2026, 8, 19): "Ganesh Chaturthi",
            date(2026, 9, 7): "Id-ul-Zuha (Bakrid)",
            date(2026, 10, 2): "Mahatma Gandhi Jayanti",
            date(2026, 10, 22): "Dasara",
            date(2026, 11, 9): "Diwali / Laxmi Puja",
            date(2026, 11, 10): "Diwali Balipratipada",
            date(2026, 11, 26): "Guru Nanak Jayanti",
            date(2026, 12, 25): "Christmas",
        }
        name = holiday_names.get(d, "NSE Holiday")
        events.append(CalendarEvent(d, EventType.HOLIDAY, name,
                                    "NSE trading holiday — market closed", risk_level=1.0))

    # Check if expiry
    if d in get_expiry_dates(d.year):
        is_monthly = d in MONTHLY_EXPIRY_DATES_2026
        name = f"{'Monthly' if is_monthly else 'Weekly'} Expiry"
        evt_type = EventType.EXPIRY
        risk = 0.5 if is_monthly else 0.3
        events.append(CalendarEvent(d, evt_type, name,
                                    f"{'Monthly' if is_monthly else 'Weekly'} F&O expiry day",
                                    risk_level=risk))

    # Check economic events
    all_economic = ECONOMIC_EVENTS_2026 + _get_corporate_events_2026()
    for ev in all_economic:
        if ev.date == d:
            events.append(ev)

    # Sort by risk level (highest first)
    events.sort(key=lambda e: e.risk_level, reverse=True)
    return events


def get_next_event(check_date: date | None = None) -> CalendarEvent | None:
    """Get the next upcoming calendar event.

    Args:
        check_date: Starting date. Uses today if None.

    Returns:
        The next CalendarEvent, or None if no upcoming events.
    """
    d = check_date or get_today()

    # Get all upcoming events within next 90 days
    all_events = _get_all_events_for_range(d, d + timedelta(days=90))

    # Filter past events and sort
    future = sorted(
        [e for e in all_events if e.date > d],
        key=lambda e: e.date,
    )

    return future[0] if future else None


def get_market_session(check_datetime: datetime | None = None) -> MarketSession:
    """Get complete market session information.

    This is the MAIN query function — use this to get everything at once.

    Args:
        check_datetime: Datetime to check. Uses current IST time if None.

    Returns:
        MarketSession with all relevant session data.
    """
    dt = check_datetime or get_now()
    d = dt.date()
    t = dt.time()

    session_state = get_session_state(dt)
    holiday_today = is_holiday(d)
    weekend_today = is_weekend(d)
    market_open = is_market_open(dt)
    expiry_today = is_expiry_day(d)
    expiry_week = is_expiry_week(d)
    rollover_week = is_rollover_week(d)

    # Events today
    events_today_list = get_events_for_date(d)
    events_today_dicts = [
        {"name": e.name, "type": e.event_type.value, "risk": e.risk_level}
        for e in events_today_list
    ]

    # Next event
    next_ev = get_next_event(d)
    next_event_name = next_ev.name if next_ev else ""
    next_event_date = next_ev.date.isoformat() if next_ev else ""
    days_to_next = (next_ev.date - d).days if next_ev else 999

    # Time to market events
    if market_open or holiday_today or weekend_today:
        time_to_open = 0.0
        time_to_close = 0.0
        if market_open:
            close_dt = dt.replace(hour=15, minute=30, second=0, microsecond=0)
            time_to_close = max(0.0, (close_dt - dt).total_seconds())
    else:
        # Calculate time to next market open
        next_open = _get_next_market_open(dt)
        time_to_open = (next_open - dt).total_seconds() if next_open else 0.0
        time_to_close = 0.0

    return MarketSession(
        session_state=session_state,
        is_market_open=market_open,
        is_holiday_today=holiday_today or weekend_today,
        is_expiry_today=expiry_today,
        is_expiry_week=expiry_week,
        is_rollover_week=rollover_week,
        next_event=next_event_name,
        next_event_date=next_event_date,
        days_to_next_event=days_to_next,
        time_to_market_open=time_to_open,
        time_to_market_close=time_to_close,
        events_today=events_today_dicts,
    )


def format_market_session(session: MarketSession) -> str:
    """Format a MarketSession into a human-readable summary string.

    Args:
        session: The MarketSession to format.

    Returns:
        A formatted string summarising the market session.
    """
    parts: list[str] = [
        f"Session: {session.session_state.value}",
        f"Open: {'YES' if session.is_market_open else 'NO'}",
    ]

    if session.is_holiday_today:
        parts.append("⚠️ HOLIDAY — Market Closed")
    if session.is_expiry_today:
        parts.append("📅 EXPIRY DAY")
    if session.is_expiry_week:
        parts.append("📅 Expiry Week")
    if session.is_rollover_week:
        parts.append("🔄 Rollover Week")

    if session.events_today:
        for ev in session.events_today:
            parts.append(f"📌 {ev['name']} (risk: {ev['risk']:.1f})")

    if session.next_event:
        parts.append(f"Next: {session.next_event} on {session.next_event_date} "
                     f"({session.days_to_next_event}d away)")

    if not session.is_market_open and not session.is_holiday_today:
        mins_to_open = int(session.time_to_market_open / 60)
        if mins_to_open > 0:
            parts.append(f"Opens in ~{mins_to_open}m")

    return " | ".join(parts)


# =============================================================================
# INTERNAL HELPERS
# =============================================================================


def _get_corporate_events_2026() -> list[CalendarEvent]:
    """Get approximate corporate result season dates.

    Returns:
        List of corporate event CalendarEvents.
    """
    # Approximate result seasons: Jan, Apr, Jul, Oct
    return [
        CalendarEvent(date(2026, 1, 15), EventType.CORPORATE, "Q3 Results Season",
                      "Corporate Q3 FY26 earnings season", risk_level=0.2),
        CalendarEvent(date(2026, 4, 15), EventType.CORPORATE, "Q4 Results Season",
                      "Corporate Q4 FY26 earnings season", risk_level=0.3),
        CalendarEvent(date(2026, 7, 15), EventType.CORPORATE, "Q1 Results Season",
                      "Corporate Q1 FY27 earnings season", risk_level=0.2),
        CalendarEvent(date(2026, 10, 15), EventType.CORPORATE, "Q2 Results Season",
                      "Corporate Q2 FY27 earnings season", risk_level=0.2),
    ]


def _get_all_events_for_range(
    start: date, end: date,
) -> list[CalendarEvent]:
    """Get all calendar events within a date range.

    Args:
        start: Start date (inclusive).
        end: End date (inclusive).

    Returns:
        List of CalendarEvent objects in the range.
    """
    events: list[CalendarEvent] = []
    current = start

    while current <= end:
        events.extend(get_events_for_date(current))
        current += timedelta(days=1)

    return events


def _get_next_market_open(from_datetime: datetime) -> datetime | None:
    """Find the next datetime when the market will open.

    Args:
        from_datetime: Starting datetime.

    Returns:
        Datetime of the next market open (IST), or None.
    """
    current = from_datetime

    # Check up to 7 days ahead
    for _ in range(7):
        current += timedelta(minutes=1)
        if is_market_open(current):
            # Snap to market open time
            return current.replace(
                hour=MARKET_OPEN_TIME.hour,
                minute=MARKET_OPEN_TIME.minute,
                second=0, microsecond=0,
            )

    return None
