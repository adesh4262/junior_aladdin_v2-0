"""Tests for Floor 5 — DecisionSnapshotWriter (Step 5.18)."""

from __future__ import annotations

from datetime import datetime

from junior_aladdin.floor_5_captain.captain_types import CaptainMood
from junior_aladdin.floor_5_captain.decision_snapshot_writer import (
    DecisionSnapshotWriter,
    SnapContext,
)
from junior_aladdin.shared.types import CaptainDecision, DecisionSnapshot, DecisionType, TradeClass


# ── Fixtures ───────────────────────────────────────────────────────────────


def make_writer() -> DecisionSnapshotWriter:
    return DecisionSnapshotWriter()


def make_context(
    story: str = "TREND_UP regime",
    reason: str = "Strong confluence, BUY signal",
    conviction: float = 80.0,
    mood: CaptainMood = CaptainMood.AGGRESSIVE,
) -> SnapContext:
    return SnapContext(
        market_story_summary=story,
        narrative_timeline_excerpt=["Gap up at open", "Liquidity sweep 19500"],
        heads_summary={
            "smc": {"bias": "BULLISH", "confidence": 0.8, "state": "READY"},
            "ict": {"bias": "BULLISH", "confidence": 0.7, "state": "READY"},
        },
        armed_plan_reference="plan-uuid-123",
        conviction_score=conviction,
        invalidation={"level": 19400.0, "type": "price"},
        decision_reason=reason,
        silence_reason="",
        session_context={"phase": "GOLDEN_MORNING", "regime": "TREND_UP"},
        capital_context={"limit": 25000.0, "mode": "PAPER"},
        mood=mood,
    )


def make_captain_decision() -> CaptainDecision:
    return CaptainDecision(
        decision=DecisionType.TRADE,
        action="BUY",
        option_side="CE",
        selected_strike="19500",
        trade_class=TradeClass.CONTINUATION,
        permission_score=80.0,
        conviction_score=75.0,
        no_trade_score=20.0,
        entry_plan={"zone": "FVG_19500"},
        invalidation_level=19400.0,
        stop_loss_plan={"sl_price": 19450.0},
        target_plan={"target_price": 19600.0},
        reason_summary="BUY CE 19500 (CONTINUATION) — Strong trend",
        snapshot_id="",
        timestamp=datetime.utcnow(),
    )


# ── 1. Write Snapshot ─────────────────────────────────────────────────────


def test_1_write_snapshot_basic():
    """Write a snapshot returns a valid DecisionSnapshot."""
    writer = make_writer()
    ctx = make_context()
    snap = writer.write_snapshot(ctx)
    assert snap is not None
    assert snap.snapshot_id != ""
    assert snap.market_story_summary == "TREND_UP regime"
    assert snap.conviction_score == 80.0
    assert snap.mood == CaptainMood.AGGRESSIVE


def test_2_write_snapshot_stores():
    """Written snapshot is retrievable by ID."""
    writer = make_writer()
    ctx = make_context()
    snap = writer.write_snapshot(ctx)
    retrieved = writer.get_snapshot(snap.snapshot_id)
    assert retrieved is not None
    assert retrieved.snapshot_id == snap.snapshot_id
    assert retrieved.decision_reason == "Strong confluence, BUY signal"


def test_3_write_multiple_snapshots():
    """Multiple snapshots are all stored independently."""
    writer = make_writer()
    s1 = writer.write_snapshot(make_context(reason="First", conviction=50.0))
    s2 = writer.write_snapshot(make_context(reason="Second", conviction=80.0))
    assert writer.get_snapshot_count() == 2
    assert s1.snapshot_id != s2.snapshot_id


# ── 2. SnapContext Factory ────────────────────────────────────────────────


def test_4_from_captain_decision():
    """SnapContext factory builds from CaptainDecision."""
    cd = make_captain_decision()
    ctx = SnapContext.from_captain_decision(
        captain_decision=cd,
        market_story_summary="Strong uptrend",
        mood=CaptainMood.PATIENT,
    )
    assert ctx.market_story_summary == "Strong uptrend"
    assert ctx.conviction_score == 75.0
    assert ctx.decision_reason == "BUY CE 19500 (CONTINUATION) — Strong trend"
    assert ctx.mood == CaptainMood.PATIENT
    assert ctx.session_context["action"] == "BUY"


def test_5_from_captain_decision_with_timeline():
    """Factory includes timeline excerpt."""
    cd = make_captain_decision()
    timeline = ["Event 1", "Event 2", "Event 3"]
    ctx = SnapContext.from_captain_decision(cd, narrative_timeline_excerpt=timeline)
    assert ctx.narrative_timeline_excerpt == timeline


def test_6_from_captain_decision_with_heads():
    """Factory includes heads summary."""
    cd = make_captain_decision()
    heads = {"smc": {"bias": "BULLISH"}, "technical": {"bias": "BULLISH"}}
    ctx = SnapContext.from_captain_decision(cd, heads_summary=heads)
    assert ctx.heads_summary == heads


# ── 3. Retrieval ──────────────────────────────────────────────────────────


def test_7_get_snapshot_not_found():
    """Unknown snapshot ID returns None."""
    writer = make_writer()
    assert writer.get_snapshot("nonexistent-uuid") is None


def test_8_get_session_snapshots():
    """get_session_snapshots returns all snapshots."""
    writer = make_writer()
    writer.write_snapshot(make_context(reason="First"))
    writer.write_snapshot(make_context(reason="Second"))
    writer.write_snapshot(make_context(reason="Third"))
    all_snaps = writer.get_session_snapshots()
    assert len(all_snaps) == 3


def test_9_get_latest_snapshot():
    """Latest snapshot is the most recent."""
    writer = make_writer()
    writer.write_snapshot(make_context(reason="First", conviction=50.0))
    snap2 = writer.write_snapshot(make_context(reason="Second", conviction=80.0))
    latest = writer.get_latest_snapshot()
    assert latest is not None
    assert latest.snapshot_id == snap2.snapshot_id


def test_10_get_latest_snapshot_empty():
    """No snapshots → latest is None."""
    writer = make_writer()
    assert writer.get_latest_snapshot() is None


# ── 4. Session Management ─────────────────────────────────────────────────


def test_11_clear_session():
    """Clear removes all snapshots."""
    writer = make_writer()
    writer.write_snapshot(make_context())
    writer.clear_session()
    assert writer.get_snapshot_count() == 0
    assert not writer.has_snapshots()


def test_12_has_snapshots():
    """has_snapshots returns correct state."""
    writer = make_writer()
    assert not writer.has_snapshots()
    writer.write_snapshot(make_context())
    assert writer.has_snapshots()


def test_13_get_snapshot_count():
    """Count matches number of snapshots written."""
    writer = make_writer()
    assert writer.get_snapshot_count() == 0
    writer.write_snapshot(make_context())
    assert writer.get_snapshot_count() == 1
    writer.write_snapshot(make_context())
    assert writer.get_snapshot_count() == 2


# ── 5. Snapshot Contents ──────────────────────────────────────────────────


def test_14_snapshot_contains_all_fields():
    """Snapshot has all mandatory fields populated."""
    writer = make_writer()
    ctx = make_context(
        story="RANGE market",
        reason="Options pressure, sell signal",
        conviction=65.0,
        mood=CaptainMood.PATIENT,
    )
    snap = writer.write_snapshot(ctx)
    assert snap.market_story_summary == "RANGE market"
    assert len(snap.narrative_timeline_excerpt) == 2
    assert "smc" in snap.heads_summary
    assert snap.armed_plan_reference == "plan-uuid-123"
    assert snap.conviction_score == 65.0
    assert snap.invalidation["level"] == 19400.0
    assert snap.decision_reason == "Options pressure, sell signal"
    assert snap.session_context["phase"] == "GOLDEN_MORNING"
    assert snap.capital_context["limit"] == 25000.0
    assert snap.mood == CaptainMood.PATIENT


def test_15_snapshot_has_timestamp():
    """Snapshot has a valid timestamp."""
    writer = make_writer()
    snap = writer.write_snapshot(make_context())
    assert snap.timestamp is not None
    assert isinstance(snap.timestamp, datetime)


# ── 6. Edge Cases ─────────────────────────────────────────────────────────


def test_16_edge_empty_context():
    """Empty context produces valid snapshot with defaults."""
    writer = make_writer()
    ctx = SnapContext()
    snap = writer.write_snapshot(ctx)
    assert snap.snapshot_id != ""
    assert snap.market_story_summary == ""
    assert snap.conviction_score == 0.0
    assert snap.mood == CaptainMood.OBSERVER


def test_17_edge_clear_then_write():
    """After clear, new snapshots work correctly."""
    writer = make_writer()
    writer.write_snapshot(make_context())
    writer.clear_session()
    snap = writer.write_snapshot(make_context(reason="After reset"))
    assert writer.get_snapshot_count() == 1
    assert snap.decision_reason == "After reset"


def test_18_edge_snap_id_is_unique():
    """Each snapshot has a unique ID."""
    writer = make_writer()
    ids = set()
    for _ in range(10):
        snap = writer.write_snapshot(make_context())
        ids.add(snap.snapshot_id)
    assert len(ids) == 10


def test_19_edge_snapshots_preserved_independently():
    """Snapshots don't overwrite each other."""
    writer = make_writer()
    s1 = writer.write_snapshot(make_context(reason="First", conviction=50.0))
    s2 = writer.write_snapshot(make_context(reason="Second", conviction=80.0))
    r1 = writer.get_snapshot(s1.snapshot_id)
    r2 = writer.get_snapshot(s2.snapshot_id)
    assert r1.conviction_score == 50.0
    assert r2.conviction_score == 80.0
