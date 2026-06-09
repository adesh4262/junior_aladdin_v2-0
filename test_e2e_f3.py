"""Floor 3 End-to-End Integration Test.

Flow: Floor 2 Packets → f3_ingress → CalculationInput
      → f3_orchestrator.handle_calculation_cycle → EngineRunReports + Signals
      → f3_output_builder.build_output → OutputContract
      → f3_validator.validate_output → ValidationResult

Tests all 5 market phases, valid/invalid packets, replay mode,
and full cycle with all 3 domain engines.
"""

import sys
sys.path.insert(0, ".")

from datetime import datetime, timedelta, timezone
from junior_aladdin.shared.types import PacketEnvelope, FreshnessTag, DataHealth
from junior_aladdin.floor_3_calculations.f3_types import (
    MarketPhase,
    CalculationDomain,
    EngineRunReport,
    EngineStatus,
)
from junior_aladdin.floor_3_calculations.f3_ingress import consume_floor2_output
from junior_aladdin.floor_3_calculations.f3_orchestrator import (
    handle_calculation_cycle,
)
from junior_aladdin.floor_3_calculations.f3_output_builder import build_output
from junior_aladdin.floor_3_calculations.f3_validator import validate_output

UTC = timezone.utc
passed = 0
failed = 0


def check(name, condition, detail=""):
    global passed, failed
    if condition:
        passed += 1
        print(f"  [PASS] {name}")
    else:
        failed += 1
        msg = f"  [FAIL] {name}"
        if detail:
            msg += f" -- {detail}"
        print(msg)


def build_candles(count=50):
    """Build realistic candle data."""
    c = []
    for i in range(count):
        h, m = 9 + (15 + i) // 60, (15 + i) % 60
        trend = 0.3
        noise = (i % 5) * 0.2
        base = 100 + i * trend
        c.append({
            "high": base + 1.0 + noise,
            "low": base - 1.0 - noise,
            "close": base + 0.3 + noise * 0.5,
            "volume": 2000 + (i % 10) * 200,
            "timestamp": datetime(2024, 1, 15, h, m, tzinfo=UTC),
        })
    return c


def make_packet(packet_id, freshness=None, health=None, ts=None, data=None,
                feed="candle_stream", source="floor_2"):
    """Helper to create a PacketEnvelope for testing."""
    now = datetime.now(UTC)
    payload = {}
    if freshness:
        payload["freshness_tag"] = freshness
    if health:
        payload["data_health"] = health
    if ts:
        payload["timestamp"] = ts
    payload["data"] = data or {"candles": build_candles(10)}
    payload["symbol"] = "NIFTY"
    payload["market_phase"] = "OPEN"
    return PacketEnvelope(
        source=source, feed_type=feed, connection_id="c1",
        packet_id=packet_id, routing_id="r1", received_at=now,
        payload=payload,
    )


def main():
    global passed, failed

    print("=" * 55)
    print("FLOOR 3 END-TO-END INTEGRATION TEST")
    print("=" * 55)

    now = datetime.now(UTC)
    candles = build_candles(50)

    # ════════════════════════════════════════════════════════════
    # PHASE 1: INGRESS
    # ════════════════════════════════════════════════════════════
    print("\n--- Phase 1: Ingress ---")

    # 1a: Valid packet
    valid_packet = make_packet("p1", FreshnessTag.FRESH, DataHealth.GOOD, now, {"candles": candles})
    result = consume_floor2_output([valid_packet])
    check("Valid packet accepted", len(result.accepted) == 1 and result.rejected_count == 0)

    # 1b: Invalid - missing freshness
    bad_fresh = make_packet("p2", health=DataHealth.GOOD, ts=now, data={"candles": candles})
    result2 = consume_floor2_output([bad_fresh])
    check("No freshness rejected", result2.rejected_count == 1 and len(result2.accepted) == 0)

    # 1c: Invalid - missing health
    bad_health = make_packet("p3", FreshnessTag.FRESH, ts=now, data={"candles": candles})
    result3 = consume_floor2_output([bad_health])
    check("No health rejected", result3.rejected_count == 1 and len(result3.accepted) == 0)

    # 1d: Old timestamp (live mode) -> reject
    old_ts = now - timedelta(seconds=2000)
    old_packet = make_packet("p4", FreshnessTag.FRESH, DataHealth.GOOD, old_ts, {"candles": candles})
    result4 = consume_floor2_output([old_packet])
    check("Old TS rejected (live)", result4.rejected_count == 1)

    # 1e: Old timestamp (replay mode) -> accept
    result5 = consume_floor2_output([old_packet], replay_mode=True)
    check("Old TS accepted (replay)", len(result5.accepted) == 1 and result5.rejected_count == 0)

    # 1f: Raw feed type -> reject
    raw_packet = make_packet("p5", FreshnessTag.FRESH, DataHealth.GOOD, now,
                             {"candles": candles}, feed="raw_ticks", source="floor_1")
    result6 = consume_floor2_output([raw_packet])
    check("Raw feed rejected", result6.rejected_count == 1)

    # 1g: Empty batch -> 0 accepted
    result7 = consume_floor2_output([])
    check("Empty batch accepted=0", len(result7.accepted) == 0 and result7.rejected_count == 0)

    # 1h: Mixed batch (2 valid + 1 invalid)
    result8 = consume_floor2_output([valid_packet, bad_fresh, valid_packet])
    check("Mixed batch: 2 accepted", len(result8.accepted) == 2)
    check("Mixed batch: 1 rejected", result8.rejected_count == 1)

    # Get a CalculationInput from the first valid result for Phase 2
    calc_input = result.accepted[0]
    check("CalcInput has packet_envelope_id", bool(calc_input.packet_envelope_id))
    check("CalcInput has market_phase", calc_input.market_phase == MarketPhase.OPEN)
    check("CalcInput has candles", "candles" in calc_input.data)

    # ════════════════════════════════════════════════════════════
    # PHASE 2: ORCHESTRATE — all market phases
    # ════════════════════════════════════════════════════════════
    print("\n--- Phase 2: Orchestrate ---")

    from junior_aladdin.floor_3_calculations.f3_types import CalculationInput

    phase_results = {}
    for phase in [MarketPhase.PRE_OPEN, MarketPhase.OPEN, MarketPhase.LUNCH,
                  MarketPhase.CLOSING, MarketPhase.POST_CLOSE]:
        inp = CalculationInput(
            packet_envelope_id=f"e2e_{phase.value}",
            market_phase=phase,
            symbol="NIFTY",
            timestamp=now,
            data={"candles": candles},
        )
        oc = handle_calculation_cycle(inp)
        phase_results[phase.value] = oc

    # Check expected domain counts per phase
    poc = phase_results["PRE_OPEN"]
    check("PRE_OPEN: 2 engines", len(poc.engine_reports) == 2, str(len(poc.engine_reports)))
    check("PRE_OPEN: signals > 0", len(poc.signals) > 0, str(len(poc.signals)))

    open_ = phase_results["OPEN"]
    check("OPEN: 3 engines", len(open_.engine_reports) == 3, str(len(open_.engine_reports)))
    check("OPEN: signals > 0", len(open_.signals) > 0, str(len(open_.signals)))

    lunch = phase_results["LUNCH"]
    check("LUNCH: 3 engines", len(lunch.engine_reports) == 3)
    check("LUNCH: signals > 0", len(lunch.signals) > 0)

    closing = phase_results["CLOSING"]
    check("CLOSING: 2 engines", len(closing.engine_reports) == 2, str(len(closing.engine_reports)))
    check("CLOSING: signals > 0", len(closing.signals) > 0)

    pc = phase_results["POST_CLOSE"]
    check("POST_CLOSE: 0 engines", len(pc.engine_reports) == 0)
    check("POST_CLOSE: 0 signals", len(pc.signals) == 0)
    check("POST_CLOSE: summary present", pc.floor_summary is not None)

    # Verify OPEN has more signals than PRE_OPEN (Technical adds more)
    check("OPEN signals > PRE_OPEN signals",
          len(open_.signals) > len(poc.signals),
          f"OPEN={len(open_.signals)} PRE_OPEN={len(poc.signals)}")

    # Check engine statuses are COMPLETE
    for phase_name, oc in phase_results.items():
        for r in oc.engine_reports:
            check(f"{phase_name}: {r.engine_name} COMPLETE",
                  r.status == EngineStatus.COMPLETE, str(r.status.value))

    # ════════════════════════════════════════════════════════════
    # PHASE 3: OUTPUT BUILDER
    # ════════════════════════════════════════════════════════════
    print("\n--- Phase 3: Output Builder ---")

    # Use OPEN phase results
    oc_open = phase_results["OPEN"]
    ob = build_output(
        signals=oc_open.signals,
        engine_reports=oc_open.engine_reports,
    )
    check("OutputContract built", ob is not None)
    check("OC signals match", len(ob.signals) == len(oc_open.signals))
    check("OC reports match", len(ob.engine_reports) == len(oc_open.engine_reports))
    check("OC has Floor3Summary", ob.floor_summary is not None)
    check("OC signals_count correct", ob.floor_summary.signals_count == len(oc_open.signals))

    # Check summary details
    fs = ob.floor_summary
    check("Summary has domain_summaries", len(fs.domain_summaries) >= 3)
    check("Summary has engine_statuses", bool(fs.engine_statuses))
    check("Summary data_health = GOOD", fs.data_health == DataHealth.GOOD)

    # Check individual signal properties
    if ob.signals:
        sig = ob.signals[0]
        check("Signal has signal_id", len(sig.signal_id) == 32)
        check("Signal has indicator_type", bool(sig.indicator_type))
        check("Signal has domain", sig.domain in (
            CalculationDomain.SMC, CalculationDomain.ICT, CalculationDomain.TECHNICAL))
        check("Signal has calculation_log", sig.calculation_log is not None)
        if sig.calculation_log:
            check("Signal log has input_hash", bool(sig.calculation_log.input_hash))

    # ════════════════════════════════════════════════════════════
    # PHASE 4: VALIDATOR
    # ════════════════════════════════════════════════════════════
    print("\n--- Phase 4: Validator ---")

    vr = validate_output(ob)
    check("Validation: no HALT errors",
          len(vr.halt_errors) == 0, f"got {len(vr.halt_errors)}")
    check("Validation: valid=True", vr.valid)
    check("Validation: total_checks > 0", vr.total_checks > 0,
          str(vr.total_checks))

    # Check summary
    vs = vr.summary()
    check("Validation summary: valid=True", vs["valid"])
    check("Validation summary: 0 halts", vs["halt_count"] == 0)

    # Also validate with replay mode (should still pass)
    signal_ids = {s.signal_id for s in ob.signals}
    input_hashes = set()
    for s in ob.signals:
        if s.calculation_log:
            input_hashes.add(s.calculation_log.input_hash)
    vr2 = validate_output(ob, replay_mode=True,
                           expected_signal_ids=signal_ids,
                           expected_input_hashes=input_hashes)
    check("Replay validation: no HALT",
          len(vr2.halt_errors) == 0, f"got {len(vr2.halt_errors)}")
    check("Replay validation: valid=True", vr2.valid)

    # Validate with WRONG expected IDs (should fail)
    vr3 = validate_output(ob, replay_mode=True,
                           expected_signal_ids={"nonexistent"},
                           expected_input_hashes={"nohash"})
    check("Replay mismatch: HALTs > 0",
          len(vr3.halt_errors) > 0, f"got {len(vr3.halt_errors)}")

    # Validate empty output (zero signals is valid)
    from junior_aladdin.floor_3_calculations.f3_contracts import OutputContract
    from junior_aladdin.floor_3_calculations.f3_types import Floor3Summary
    empty_oc = OutputContract(
        signals=[],
        engine_reports=[],
        floor_summary=Floor3Summary(
            domain_summaries={"reason": "no-op"},
            signals_count=0,
            engine_statuses={},
            data_health=DataHealth.GOOD,
        ),
    )
    vr4 = validate_output(empty_oc)
    check("Empty OC: no HALT", len(vr4.halt_errors) == 0, f"got {len(vr4.halt_errors)}")

    # ════════════════════════════════════════════════════════════
    # SUMMARY
    # ════════════════════════════════════════════════════════════
    print(f"\n{'=' * 55}")
    print(f"RESULTS: {passed} passed, {failed} failed out of {passed + failed} tests")
    if failed == 0:
        print("ALL FLOOR 3 E2E INTEGRATION TESTS PASSED")
    else:
        print("SOME TESTS FAILED - check logs above")
    print(f"{'=' * 55}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
