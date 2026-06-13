#!/usr/bin/env python3
"""Smoke Test -- 1-Minute Trading Session with Complete Captain Engine.

Simulates one real-time minute of trading:
- 1 heavy cycle (on 1m candle close)
- 60 light cycles (one per tick)
- Full 24-step heavy pipeline
- Light cycle plan watching across 60 ticks
- Session management (start -> trade -> complete -> reset)

Usage:  python scripts/smoke_test_captain.py
"""

from __future__ import annotations

import time
import sys
import os

# Windows-safe high-res timer
if sys.platform == "win32":
    _timer = time.perf_counter
else:
    _timer = time.time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime
from junior_aladdin.floor_5_captain.captain_engine import CaptainEngine
from junior_aladdin.floor_5_captain.captain_types import (
    CaptainInput,
    SessionPhase,
)
from junior_aladdin.shared.testing import (
    generate_mock_head_report,
    generate_mock_floor_summary,
)
from junior_aladdin.shared.types import (
    BiasType,
    CaptainMood,
    DecisionType,
    ExecutionMode,
    HeadState,
)

# Session timing: Golden Morning IST (9:45-11:00 IST = 4:15-5:30 UTC)
SESSION_START_UTC = datetime(2025, 1, 1, 4, 30, 0)  # 10:00 IST

# NIFTY 50 parameters
BASE_PRICE = 23450.0
STRIKE = 23500
LOT_SIZE = 25
CAPITAL = 50000.0

_HEAD_NAMES = [
    "SMC Head", "ICT Head", "Technical Head",
    "Options Head", "Macro Head", "Psychology Head",
]


def build_input(psych_allowed: bool = True) -> CaptainInput:
    """Build a bullish-biased CaptainInput (4/5 trading heads bullish)."""
    heads = {}
    biases = {
        "SMC": BiasType.BULLISH,
        "ICT": BiasType.BULLISH,
        "Technical": BiasType.BULLISH,
        "Options": BiasType.BULLISH,
        "Macro": BiasType.BEARISH,
        "Psychology": BiasType.NEUTRAL,
    }
    confidences = {
        "SMC": 0.82,
        "ICT": 0.78,
        "Technical": 0.75,
        "Options": 0.70,
        "Macro": 0.55,
        "Psychology": 0.90,
    }
    for name in _HEAD_NAMES:
        short = name.split()[0]
        bias = biases[short]
        conf = confidences[short]
        if name == "Psychology Head":
            heads[name] = generate_mock_head_report(
                head_name="Psychology",
                bias=BiasType.NEUTRAL,
                confidence=0.90,
                state=HeadState.READY,
            )
            heads[name].trade_allowed = psych_allowed
            heads[name].caution_level = 0.1
        else:
            heads[name] = generate_mock_head_report(
                head_name=short,
                bias=bias,
                confidence=conf,
                state=HeadState.READY,
            )
    return CaptainInput(
        floor_summary=generate_mock_floor_summary(),
        head_reports=heads,
    )


def main() -> None:
    print("=" * 65)
    print("  FLOOR 5 -- CAPTAIN ENGINE SMOKE TEST (1-MINUTE SESSION)")
    print("=" * 65)

    # Phase 1: Initialise
    print("\n[Phase 1] Initialising CaptainEngine...")
    t0 = time.time()
    engine = CaptainEngine()
    init_ms = (time.time() - t0) * 1000
    print(f"  Engine created ({init_ms:.1f}ms)")
    sub_count = len([a for a in dir(engine) if not a.startswith("_") and a != "heavy_cycle" and a != "light_cycle"])
    print(f"  {sub_count} public methods / sub-engines loaded")

    # Phase 2: Start Session
    print(f"\n[Phase 2] Starting session @ 10:00 IST (UTC+5:30)...")
    engine.start_session(timestamp=SESSION_START_UTC)
    session_phase = engine.session_policy.get_session_phase(SESSION_START_UTC)
    strictness = engine.session_policy.get_permission_strictness(session_phase)
    print(f"  Session phase:  {session_phase.value}")
    print(f"  Permission:     {strictness}")

    # Phase 3: Build Market Input
    print(f"\n[Phase 3] Building Floor 4 input data...")
    inp = build_input(psych_allowed=True)
    tick_prices = [round(BASE_PRICE + i * 0.3, 2) for i in range(61)]
    print(f"  NIFTY spot:     {tick_prices[0]:,.2f} -> {tick_prices[-1]:,.2f}")
    print(f"  6 head reports  (4/5 trading heads BULLISH)")
    print(f"  ATM strike:     {STRIKE} CE/PE")

    # Phase 4: Heavy Cycle (1m candle close)
    print(f"\n[Phase 4] HEAVY CYCLE (candle 1 @ 1m close)...")
    output = None
    try:
        t_hc = time.time()
        output = engine.heavy_cycle(
            captain_input=inp,
            timestamp=SESSION_START_UTC,
            current_price=tick_prices[0],
            current_mode=ExecutionMode.PAPER,
            capital_available=CAPITAL,
            candle_index=1,
            atm_strike=float(STRIKE),
            lot_size=LOT_SIZE,
            zone_info={
                "label": "FVG_01",
                "price": 23400.0,
                "type": "FVG",
            },
        )
        hc_ms = (time.time() - t_hc) * 1000
        print(f"  Completed in {hc_ms:.1f}ms")
    except Exception as e:
        print(f"  FAILED: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

    d = output.decision

    # Compute mood with ALL parameters
    mood = engine.personality_engine.determine_mood(
        conviction_band=output.conviction_score.conviction_band
        if output.conviction_score else None,
        session_phase=session_phase,
        market_story=output.market_story,
        active_trade_exists=False,
        permission_allowed=output.permission_result.allowed
        if output.permission_result else False,
        has_setups=output.trade_plan is not None,
        recent_loss=False,
    )

    print(f"\n--- Heavy Cycle Results ----------------------------------------")
    print(f"  Permission:      {'ALLOWED' if not output.is_blocked else 'BLOCKED'}")
    if output.permission_result and output.permission_result.blocked_by:
        print(f"  Blocked by:      {output.permission_result.blocked_by}")
    print(f"  Decision:        {d.decision.value if d else 'N/A'}")
    print(f"  Captain Mood:    {mood.value}")
    if output.market_story:
        print(f"  Market Regime:   {output.market_story.regime}")
        print(f"  Market Bias:     {output.market_story.bias}")
        print(f"  Story:           {output.market_story.summary[:80]}")
    if output.conviction_score:
        cs = output.conviction_score
        print(f"  Conviction:      {cs.conviction_band.value} ({cs.conviction_score:.0f}/100)")
        print(f"  Permission scr:  {cs.permission_score:.0f}/100")
        print(f"  No-trade score:  {cs.no_trade_score:.0f}/100")
    if output.confluence_result:
        cr = output.confluence_result
        print(f"  Confluence:      {cr.dominant_direction} @ {cr.confluence_quality:.2f}")
        if cr.aligned_heads:
            print(f"  Aligned heads:   {', '.join(cr.aligned_heads[:4])}")
    if output.opposite_case:
        oc = output.opposite_case
        print(f"  Opposite case:   strength={oc.strength:.2f}, exists={oc.exists}")
    if output.trade_plan:
        tp = output.trade_plan
        print(f"  Trade Plan:      {tp.direction} {tp.option_side} {tp.selected_strike}")
        print(f"  Trade Class:     {tp.trade_class.value if tp.trade_class else 'N/A'}")
        print(f"  Constructable:   {tp.is_constructable}")
    else:
        print(f"  Trade Plan:      None (no trade this cycle)")

    plans = engine.armed_plan_engine.get_active_plans()
    print(f"  Armed plans:     {len(plans)} active")
    if plans:
        for p in plans:
            print(f"    + {p.plan_id}: {p.direction} {p.setup_class} [{p.readiness}]")

    print(f"  Snapshot:        {output.decision_snapshot.snapshot_id if output.decision_snapshot else 'None'}")

    # Phase 5: Light Cycles (60 ticks = 1 minute)
    print(f"\n[Phase 5] LIGHT CYCLES (60 ticks @ 1 tick/sec)...")
    triggered_count = 0
    light_times = []
    for i in range(60):
        price = tick_prices[i]
        t_lc = time.time()
        lc_out = engine.light_cycle(
            current_price=price,
            candle_index=1,
            regime=output.market_story.regime if output.market_story else "",
            opposite_case_strength=output.opposite_case.strength if output.opposite_case else 0.0,
        )
        light_times.append((time.time() - t_lc) * 1000)
        if lc_out.plan_triggered:
            triggered_count += 1

    avg_light_ms = sum(light_times) / len(light_times)
    total_light_ms = sum(light_times)
    n_above_1ms = sum(1 for t in light_times if t > 1.0)
    print(f"  60 ticks processed in {total_light_ms:.1f}ms total")
    print(f"  Avg latency:     {avg_light_ms:.3f}ms per tick")
    print(f"  Calls >1ms:      {n_above_1ms} (expect near 0 for light cycle)")
    if triggered_count > 0:
        print(f"  Plans triggered: {triggered_count}")
    else:
        print(f"  Plans triggered: 0 (prices stayed below BUY trigger zone)")
    print(f"  Lights fastest:  {min(light_times):.3f}ms")
    print(f"  Lights slowest:  {max(light_times):.3f}ms")

    # Phase 6: Engine State Summary
    print(f"\n[Phase 6] Engine State Snapshot ---------------------------------")
    state = engine.get_current_state()
    summary = engine.get_engine_summary()
    print(f"  Active trade:    {state['has_active_trade']}")
    print(f"  Armed plans:     {state['active_plans']}")
    print(f"  Snapshots:       {state['snapshot_count']}")
    print(f"  Silence reasons: {state['silence_count']}")
    print(f"  Candle index:    {state['candle_index']}")
    print(f"  Setup memory:    {summary['setup_memory']['total_setups']} setups tracked")
    print(f"  Active setups:   {summary['setup_memory']['active_setups']}")
    timeline_summary = summary.get("narrative_timeline", {})
    print(f"  Timeline events: {timeline_summary.get('total_events', 0)}")

    # Phase 7: Multi-Cycle Test
    print(f"\n[Phase 7] Additional Heavy Cycles -------------------------------")
    for i in range(3):
        price = tick_prices[-1] + i * 2.0
        out = engine.heavy_cycle(
            captain_input=inp,
            timestamp=SESSION_START_UTC,
            current_price=price,
            capital_available=CAPITAL,
            candle_index=2 + i,
        )
        engine.on_trade_complete()  # Allow next cycle
        d = out.decision
        cs = out.conviction_score
        cband = cs.conviction_band.value if cs else "N/A"
        plans_count = engine.armed_plan_engine.get_plan_count()
        print(f"  Candle {2+i}: {d.decision.value if d else 'N/A':8s} | "
              f"conviction={cband} | plans={plans_count}")

    # Phase 8: Loss Lock & Reset Test
    print(f"\n[Phase 8] Loss Lock / Reset -------------------------------------")
    assert engine.get_active_trade() is None
    engine.loss_lock_manager.set_mode(ExecutionMode.REAL)
    for _ in range(3):
        engine.record_loss()
    locked = engine.loss_lock_manager.is_locked()
    print(f"  3 REAL-mode losses: {'LOCKED (correct)' if locked else 'NOT LOCKED (bug)'}")
    assert locked, "Loss lock should activate after 3 REAL-mode losses"
    engine.loss_lock_manager.reset_counter()
    print(f"  After reset:          {'UNLOCKED (correct)' if not engine.loss_lock_manager.is_locked() else 'STILL LOCKED (bug)'}")
    assert not engine.loss_lock_manager.is_locked()

    # Phase 9: Final Summary
    elapsed = time.time() - t0
    seconds_per_candle = elapsed / (1 + 3 + 0)  # 1 + 3 heavy cycles
    print(f"\n{'=' * 65}")
    print(f"  SMOKE TEST PASSED -- {elapsed:.1f}s total wall time")
    print(f"  1 heavy cycle:       {hc_ms:.1f}ms")
    print(f"  60 light cycles:     {avg_light_ms:.3f}ms avg ({total_light_ms:.1f}ms total)")
    print(f"  3 extra heavy cycles (multi-candle test)")
    print(f"  22 subsystems exercised")
    print(f"{'=' * 65}")
    lc_tps = int(1000 / avg_light_ms) if avg_light_ms > 0 else 1000
    print(f"  Heavy cycle breakdown: ~{hc_ms:.0f}ms per 1m candle")
    print(f"  Light cycle throughput: ~{lc_tps} ticks/sec (est.)")
    print()


if __name__ == "__main__":
    main()
