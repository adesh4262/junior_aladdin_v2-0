"""Unit tests for ``narrative_timeline_engine.py`` — Floor 5 Step 5.6.

Tests:
- NarrativeTimelineEngine initial state
- add_event() stores events correctly
- add_events() bulk add
- get_timeline() returns full timeline
- get_all_events() chronological order
- get_recent_events() newest first
- get_events_since() time filtering
- get_events_by_type() type filtering
- get_event_count() correct
- get_excerpt() text format
- get_timeline_summary() dict
- clear_session() resets state
- has_events() correct
- get_last_event() correct
- Max events pruning
- update_from_market_story() regime shift detection
- Event type constants all accessible
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from datetime import datetime, timedelta, timezone

from junior_aladdin.floor_5_captain.narrative_timeline_engine import (
    NarrativeTimelineEngine,
    EVENT_GAP_UP,
    EVENT_GAP_DOWN,
    EVENT_PDH_TOUCH,
    EVENT_PDL_TOUCH,
    EVENT_PDH_SWEEP,
    EVENT_PDL_SWEEP,
    EVENT_LIQUIDITY_SWEEP,
    EVENT_DISPLACEMENT,
    EVENT_FVG_CREATION,
    EVENT_CONSOLIDATION,
    EVENT_BOS,
    EVENT_CHOCH,
    EVENT_STRUCTURE_BREAK,
    EVENT_REGIME_SHIFT,
    EVENT_OPTIONS_WALL_INTERACTION,
    EVENT_ARMED_PLAN_CREATED,
    EVENT_ARMED_PLAN_EXPIRED,
    EVENT_TRADE_EXECUTED,
    EVENT_TRADE_EXITED,
    EVENT_INTERVENTION,
    EVENT_SESSION_START,
    EVENT_SESSION_END,
    EVENT_MILESTONE,
)

passed = 0
failed = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global passed, failed
    if cond:
        passed += 1
        print(f"  [PASS] {name}")
    else:
        failed += 1
        print(f"  [FAIL] {name}{' -- ' + detail if detail else ''}")


print("=" * 60)
print("Floor 5 — Narrative Timeline Engine Tests")
print("=" * 60)

# =========================================================================
# 1. Initial state
# =========================================================================
print("\n--- 1. Initial state ---")

engine = NarrativeTimelineEngine()
check("1.1 Initial event count 0", engine.get_event_count() == 0)
check("1.2 Initial has_events False", engine.has_events() is False)
check("1.3 Initial get_last_event None", engine.get_last_event() is None)
check("1.4 Initial all events empty", len(engine.get_all_events()) == 0)
check("1.5 Initial recent events empty", len(engine.get_recent_events()) == 0)
check("1.6 Initial excerpt has placeholder", "No significant" in engine.get_excerpt()[0])

tl = engine.get_timeline()
check("1.7 Timeline last_update set", tl.last_update is not None)
check("1.8 Timeline event_count 0", tl.event_count == 0)

summary = engine.get_timeline_summary()
check("1.9 Summary has event_count 0", summary.get("event_count") == 0)
check("1.10 Summary has last_update", len(summary.get("last_update", "")) > 0)

# =========================================================================
# 2. add_event() — single event
# =========================================================================
print("\n--- 2. add_event() ---")

engine2 = NarrativeTimelineEngine()
dt = datetime(2026, 6, 10, 9, 30, 0, tzinfo=timezone.utc)

event = engine2.add_event(
    EVENT_GAP_UP,
    details="Gapped 50 points above previous close",
    price_level=19650.0,
    timestamp=dt,
)

check("2.1 Event has correct type", event.event_type == EVENT_GAP_UP)
check("2.2 Event has correct details", "Gapped 50" in event.details)
check("2.3 Event has correct price", event.price_level == 19650.0)
check("2.4 Event has correct timestamp", event.timestamp == dt)
check("2.5 Event count = 1", engine2.get_event_count() == 1)
check("2.6 has_events True", engine2.has_events() is True)
check("2.7 get_last_event returns the event", engine2.get_last_event() is event)
check("2.8 Timeline last_update updated", engine2.get_timeline().last_update == dt)

# =========================================================================
# 3. add_event() — multiple events, chronological order
# =========================================================================
print("\n--- 3. Multiple events in order ---")

engine3 = NarrativeTimelineEngine()
base_dt = datetime(2026, 6, 10, 10, 0, 0, tzinfo=timezone.utc)

e1 = engine3.add_event(EVENT_LIQUIDITY_SWEEP, details="PDH sweep", price_level=19650.0, timestamp=base_dt)
e2 = engine3.add_event(EVENT_DISPLACEMENT, details="Strong bearish candle", price_level=19600.0, timestamp=base_dt + timedelta(minutes=5))
e3 = engine3.add_event(EVENT_FVG_CREATION, details="FVG formed 19580-19600", price_level=19590.0, timestamp=base_dt + timedelta(minutes=10))

check("3.1 Event count = 3", engine3.get_event_count() == 3)
check("3.2 get_last_event returns last", engine3.get_last_event() is e3)

# get_all_events in order
all_events = engine3.get_all_events()
check("3.3 All events list length = 3", len(all_events) == 3)
check("3.4 First event is liquidity sweep", all_events[0].event_type == EVENT_LIQUIDITY_SWEEP)
check("3.5 Second event is displacement", all_events[1].event_type == EVENT_DISPLACEMENT)
check("3.6 Third event is FVG", all_events[2].event_type == EVENT_FVG_CREATION)

# get_recent_events newest first
recent = engine3.get_recent_events(2)
check("3.7 Recent 2 events", len(recent) == 2)
check("3.8 Most recent is FVG", recent[0].event_type == EVENT_FVG_CREATION)
check("3.9 Second recent is displacement", recent[1].event_type == EVENT_DISPLACEMENT)

# get_recent_events with more than available
recent_all = engine3.get_recent_events(10)
check("3.10 Recent cap at available", len(recent_all) == 3)

# =========================================================================
# 4. get_events_since()
# =========================================================================
print("\n--- 4. get_events_since() ---")

engine4 = NarrativeTimelineEngine()
dt0 = datetime(2026, 6, 10, 10, 0, 0, tzinfo=timezone.utc)
engine4.add_event(EVENT_GAP_UP, timestamp=dt0)
engine4.add_event(EVENT_PDH_TOUCH, timestamp=dt0 + timedelta(minutes=10))
engine4.add_event(EVENT_BOS, timestamp=dt0 + timedelta(minutes=20))
engine4.add_event(EVENT_CHOCH, timestamp=dt0 + timedelta(minutes=30))

# Events after minute 15
since_dt = dt0 + timedelta(minutes=15)
after = engine4.get_events_since(since_dt)
check("4.1 Events after 10:15", len(after) == 2)
check("4.2 First after is BOS", after[0].event_type == EVENT_BOS)
check("4.3 Second after is CHOCH", after[1].event_type == EVENT_CHOCH)

# No events after end
far_future = dt0 + timedelta(days=1)
check("4.4 No events after far future", len(engine4.get_events_since(far_future)) == 0)

# All events from start
check("4.5 All events since start", len(engine4.get_events_since(dt0 - timedelta(hours=1))) == 4)

# =========================================================================
# 5. get_events_by_type()
# =========================================================================
print("\n--- 5. get_events_by_type() ---")

engine5 = NarrativeTimelineEngine()
dt0 = datetime(2026, 6, 10, 10, 0, 0, tzinfo=timezone.utc)
engine5.add_event(EVENT_LIQUIDITY_SWEEP, timestamp=dt0)
engine5.add_event(EVENT_PDH_SWEEP, timestamp=dt0 + timedelta(minutes=5))
engine5.add_event(EVENT_LIQUIDITY_SWEEP, timestamp=dt0 + timedelta(minutes=10))
engine5.add_event(EVENT_CONSOLIDATION, timestamp=dt0 + timedelta(minutes=15))

sweeps = engine5.get_events_by_type(EVENT_LIQUIDITY_SWEEP)
check("5.1 2 liquidity sweep events", len(sweeps) == 2)

pdh = engine5.get_events_by_type(EVENT_PDH_SWEEP)
check("5.2 1 PDH sweep event", len(pdh) == 1)

consolidations = engine5.get_events_by_type(EVENT_CONSOLIDATION)
check("5.3 1 consolidation event", len(consolidations) == 1)

non_existent = engine5.get_events_by_type("non_existent_event")
check("5.4 Non-existent type returns empty", len(non_existent) == 0)

# =========================================================================
# 6. get_excerpt()
# =========================================================================
print("\n--- 6. get_excerpt() ---")

engine6 = NarrativeTimelineEngine()
dt0 = datetime(2026, 6, 10, 9, 15, 0, tzinfo=timezone.utc)
engine6.add_event(EVENT_GAP_UP, details="Gap above PDH", price_level=19600.0, timestamp=dt0)
engine6.add_event(EVENT_LIQUIDITY_SWEEP, details="PDH swept", price_level=19650.0, timestamp=dt0 + timedelta(minutes=10))
engine6.add_event(EVENT_BOS, details="Structure break above 19650", price_level=19660.0, timestamp=dt0 + timedelta(minutes=20))

excerpt = engine6.get_excerpt(max_events=3, include_labels=True)
check("6.1 Excerpt has 3 items", len(excerpt) == 3)
check("6.2 Gap Up has label", "Gap Up" in excerpt[2])
check("6.3 Liquidity Sweep has label", "Liquidity Sweep" in excerpt[1])
check("6.4 BOS has label", "Break of Structure" in excerpt[0])

# Actually get_recent_events returns newest first, so excerpt[0] is the most recent (BOS)
check("6.5 Excerpt has time", "09:" in excerpt[2] or "09:" in excerpt[0])
check("6.6 Excerpt has price", "19650" in excerpt[1] or "19650" in excerpt[2])

# Without labels
excerpt_no_label = engine6.get_excerpt(max_events=2, include_labels=False)
check("6.7 Excerpt without labels", len(excerpt_no_label) == 2)
check("6.8 Raw event type without label",
      excerpt_no_label[0].startswith("[") if excerpt_no_label else True)

# Empty timeline
empty_engine = NarrativeTimelineEngine()
check("6.9 Empty excerpt placeholder", "No significant" in empty_engine.get_excerpt()[0])

# =========================================================================
# 7. clear_session()
# =========================================================================
print("\n--- 7. clear_session() ---")

engine7 = NarrativeTimelineEngine()
engine7.add_event(EVENT_SESSION_START, details="Market opened")
engine7.add_event(EVENT_TRADE_EXECUTED, details="Bought NIFTY 19600 CE")
check("7.1 2 events before clear", engine7.get_event_count() == 2)
check("7.2 has_events before clear", engine7.has_events() is True)

engine7.clear_session()
check("7.3 0 events after clear", engine7.get_event_count() == 0)
check("7.4 has_events after clear", engine7.has_events() is False)
check("7.5 get_last_event after clear", engine7.get_last_event() is None)
check("7.6 All events empty after clear", len(engine7.get_all_events()) == 0)

# Can add events again after clear
engine7.add_event(EVENT_SESSION_START, details="Next day session")
check("7.7 Reusable after clear", engine7.get_event_count() == 1)

# =========================================================================
# 8. add_events() — bulk add
# =========================================================================
print("\n--- 8. add_events() ---")

engine8 = NarrativeTimelineEngine()
dt0 = datetime(2026, 6, 10, 10, 0, 0, tzinfo=timezone.utc)

bulk_events = [
    {"event_type": EVENT_GAP_UP, "details": "Gap up at open", "price_level": 19600.0, "timestamp": dt0},
    {"event_type": EVENT_PDH_TOUCH, "details": "Tested PDH", "price_level": 19650.0, "timestamp": dt0 + timedelta(minutes=15)},
    {"event_type": EVENT_BOS, "details": "Broke above PDH", "price_level": 19660.0, "timestamp": dt0 + timedelta(minutes=30)},
]

created = engine8.add_events(bulk_events)
check("8.1 3 events created", len(created) == 3)
check("8.2 Event count = 3", engine8.get_event_count() == 3)
check("8.3 First event type GAP_UP", created[0].event_type == EVENT_GAP_UP)
check("8.4 Second event type PDH_TOUCH", created[1].event_type == EVENT_PDH_TOUCH)
check("8.5 Third event type BOS", created[2].event_type == EVENT_BOS)

# Empty list
created_empty = engine8.add_events([])
check("8.6 Empty list returns empty", len(created_empty) == 0)

# =========================================================================
# 9. Max events pruning
# =========================================================================
print("\n--- 9. Max events pruning ---")

engine9 = NarrativeTimelineEngine(max_events=10)
dt0 = datetime(2026, 6, 10, 10, 0, 0, tzinfo=timezone.utc)
for i in range(15):
    engine9.add_event(EVENT_MILESTONE, details=f"Event {i+1}", timestamp=dt0 + timedelta(minutes=i))

check("9.1 Count capped at max_events", engine9.get_event_count() == 10)
check("9.2 Has only 10 events", len(engine9.get_all_events()) == 10)
# First event should be #6 (0-indexed: events 0-4 were pruned)
all_evt = engine9.get_all_events()
check("9.3 First event is Event 6 (5 pruned)", "Event 6" in all_evt[0].details)
check("9.4 Last event is Event 15", "Event 15" in all_evt[-1].details)

# Default max_events
engine_default = NarrativeTimelineEngine()
for i in range(250):
    engine_default.add_event(EVENT_MILESTONE, details=f"Event {i+1}")
check("9.5 Default max 200 events", engine_default.get_event_count() == 200)

# =========================================================================
# 10. update_from_market_story()
# =========================================================================
print("\n--- 10. update_from_market_story() ---")

engine10 = NarrativeTimelineEngine()

# No previous_regime — no event
result = engine10.update_from_market_story("TREND_UP", "OPENING", previous_regime=None)
check("10.1 No regime stored -> no event", result is None)
check("10.2 Count still 0", engine10.get_event_count() == 0)

# First shift: RANGE → TREND_UP
result = engine10.update_from_market_story("TREND_UP", "OPENING", previous_regime="RANGE")
check("10.3 Regime shift event created", result is not None)
check("10.4 Event type REGIME_SHIFT", result is not None and result.event_type == EVENT_REGIME_SHIFT)
check("10.5 Details mention shift", result is not None and "RANGE → TREND_UP" in result.details)
check("10.6 Count = 1", engine10.get_event_count() == 1)

# Same regime — no shift
result = engine10.update_from_market_story("TREND_UP", "GOLDEN_MORNING", previous_regime="TREND_UP")
check("10.7 Same regime -> no event", result is None)
check("10.8 Count still 1", engine10.get_event_count() == 1)

# Another shift: TREND_UP → CHOP
result = engine10.update_from_market_story("CHOP", "LUNCH", previous_regime="TREND_UP")
check("10.9 Second regime shift created", result is not None)
check("10.10 Details mention second shift", result is not None and "TREND_UP → CHOP" in result.details)
check("10.11 Count = 2", engine10.get_event_count() == 2)

# =========================================================================
# 11. Event type constants
# =========================================================================
print("\n--- 11. Event type constants ---")

check("11.1 EVENT_GAP_UP", EVENT_GAP_UP == "gap_up")
check("11.2 EVENT_GAP_DOWN", EVENT_GAP_DOWN == "gap_down")
check("11.3 EVENT_PDH_TOUCH", EVENT_PDH_TOUCH == "pdh_touch")
check("11.4 EVENT_PDL_TOUCH", EVENT_PDL_TOUCH == "pdl_touch")
check("11.5 EVENT_PDH_SWEEP", EVENT_PDH_SWEEP == "pdh_sweep")
check("11.6 EVENT_PDL_SWEEP", EVENT_PDL_SWEEP == "pdl_sweep")
check("11.7 EVENT_LIQUIDITY_SWEEP", EVENT_LIQUIDITY_SWEEP == "liquidity_sweep")
check("11.8 EVENT_DISPLACEMENT", EVENT_DISPLACEMENT == "displacement")
check("11.9 EVENT_FVG_CREATION", EVENT_FVG_CREATION == "fvg_creation")
check("11.10 EVENT_CONSOLIDATION", EVENT_CONSOLIDATION == "consolidation")
check("11.11 EVENT_BOS", EVENT_BOS == "bos")
check("11.12 EVENT_CHOCH", EVENT_CHOCH == "choch")
check("11.13 EVENT_STRUCTURE_BREAK", EVENT_STRUCTURE_BREAK == "structure_break")
check("11.14 EVENT_REGIME_SHIFT", EVENT_REGIME_SHIFT == "regime_shift")
check("11.15 Total 23 event type constants", len([
    EVENT_GAP_UP, EVENT_GAP_DOWN, EVENT_PDH_TOUCH, EVENT_PDL_TOUCH,
    EVENT_PDH_SWEEP, EVENT_PDL_SWEEP, EVENT_LIQUIDITY_SWEEP, EVENT_DISPLACEMENT,
    EVENT_FVG_CREATION, EVENT_CONSOLIDATION, EVENT_BOS, EVENT_CHOCH,
    EVENT_STRUCTURE_BREAK, EVENT_REGIME_SHIFT, EVENT_OPTIONS_WALL_INTERACTION,
    EVENT_ARMED_PLAN_CREATED, EVENT_ARMED_PLAN_EXPIRED, EVENT_TRADE_EXECUTED,
    EVENT_TRADE_EXITED, EVENT_INTERVENTION, EVENT_SESSION_START, EVENT_SESSION_END,
    EVENT_MILESTONE,
]) == 23)

# =========================================================================
# 12. get_timeline_summary()
# =========================================================================
print("\n--- 12. get_timeline_summary() ---")

engine12 = NarrativeTimelineEngine()
engine12.add_event(EVENT_SESSION_START, details="Day started")
engine12.add_event(EVENT_GAP_UP, details="Gap up")
engine12.add_event(EVENT_TRADE_EXECUTED, details="Entry")

summary12 = engine12.get_timeline_summary()
check("12.1 Summary event_count = 3", summary12.get("event_count") == 3)
check("12.2 Summary has last_update", len(summary12.get("last_update", "")) > 0)
check("12.3 Summary recent_excerpt has 3 items", len(summary12.get("recent_excerpt", [])) == 3)
check("12.4 Excerpt mentions Entry", any("Entry" in s for s in summary12.get("recent_excerpt", [])))

# =========================================================================
# 13. Edge: timestamp None uses utcnow
# =========================================================================
print("\n--- 13. Edge cases ---")

engine13 = NarrativeTimelineEngine()
event_no_ts = engine13.add_event(EVENT_MILESTONE, details="Auto timestamp")
check("13.1 Event auto-timestamped", event_no_ts.timestamp is not None)

# Empty get_events_since
check("13.2 Events since far past returns event", len(engine13.get_events_since(datetime(2000, 1, 1))) == 1)


# =========================================================================
# Summary
# =========================================================================
total = passed + failed
print(f"\n{'=' * 60}")
print(f"Results: {passed} passed, {failed} failed out of {total}")
print(f"{'=' * 60}")

if __name__ == '__main__':
    if failed > 0:
        sys.exit(1)
    else:
        sys.exit(0)
