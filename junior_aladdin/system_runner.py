"""Junior Aladdin V2.0 — System Runner.

THE MAIN LOOP that connects the entire LIVE trading pipeline:
    Angel One → Floor 1 → Floor 2 → Floor 3 → Floor 4 → Floor 5 → Side A

This is THE MISSING PIECE identified by BRUTAL_DEEP_SCAN FINDING #1.

Architecture:
    - Runs as the main process
    - Shares ComponentRegistry singletons with Side B API server
    - Market hours: Angel One WebSocket → tick processing → pipeline
    - Non-market hours: idle, waiting for market open
    - Graceful shutdown on SIGINT/SIGTERM

Usage:
    # From project root:
    python -m junior_aladdin.system_runner

    # Or with specific mode:
    python -m junior_aladdin.system_runner --mode PAPER --capital 50000

Reference: BRUTAL_DEEP_SCAN_ANALYSIS.txt — The Missing Piece
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import signal
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from junior_aladdin.shared.component_registry import get_registry
from junior_aladdin.shared.system_config import get_system_config
from junior_aladdin.shared.types import ExecutionMode

log = logging.getLogger(__name__)


# =============================================================================
# Constants
# =============================================================================

# Market hours IST (UTC+5:30)
MARKET_OPEN_HOUR = 9
MARKET_OPEN_MIN = 15
MARKET_CLOSE_HOUR = 15
MARKET_CLOSE_MIN = 30

# 1-minute candle = 60 seconds
CANDLE_DURATION_S = 60

# Max candles kept in history buffer for Floor 3 engines
# Engines need historical data: RSI=14p, MA=20p+, SMC structure=~20 candles
CANDLE_BUFFER_MAX = 100

# Poll intervals (seconds)
HEALTH_CHECK_INTERVAL_S = 5  # How often to check connection health
CYCLE_CHECK_INTERVAL_S = 0.5  # How often to check for new candle


# =============================================================================
# Trading Calendar helper (lightweight IST check)
# =============================================================================


def _now_ist() -> datetime:
    """Get current time in IST (UTC+5:30)."""
    return datetime.now(timezone.utc).astimezone(
        timezone(timedelta(hours=5, minutes=30))
    )


def _is_market_hours(dt: datetime | None = None) -> bool:
    """Check if market is currently open (9:15 AM - 3:30 PM IST, Mon-Fri)."""
    if dt is None:
        dt = _now_ist()

    # Weekend check
    if dt.weekday() >= 5:  # Saturday=5, Sunday=6
        return False

    # Time check
    hour = dt.hour
    minute = dt.minute
    total_mins = hour * 60 + minute
    open_mins = MARKET_OPEN_HOUR * 60 + MARKET_OPEN_MIN  # 9:15 = 555
    close_mins = MARKET_CLOSE_HOUR * 60 + MARKET_CLOSE_MIN  # 15:30 = 930

    return open_mins <= total_mins <= close_mins


def _seconds_until_next_candle_close(dt: datetime | None = None) -> float:
    """Seconds until the current 1-minute candle closes."""
    if dt is None:
        dt = _now_ist()
    seconds_into_minute = dt.second + dt.microsecond / 1_000_000
    return CANDLE_DURATION_S - seconds_into_minute


def _get_candle_index(dt: datetime | None = None) -> int:
    """Get the current 1-minute candle index since market open."""
    if dt is None:
        dt = _now_ist()
    open_mins = MARKET_OPEN_HOUR * 60 + MARKET_OPEN_MIN
    current_mins = dt.hour * 60 + dt.minute
    elapsed_mins = max(0, current_mins - open_mins)
    return elapsed_mins  # Each minute = 1 candle index


# =============================================================================
# SystemRunner
# =============================================================================


class SystemRunner:
    """Main system loop — connects the entire LIVE trading pipeline.

    The runner coordinates:
    1. Floor 1: Angel One connection + WebSocket subscription
    2. Floor 2: Raw data receipt and validation (via Floor 2 handoff)
    3. Floor 3: Calculation engines (on candle close)
    4. Floor 4: Department Heads (on candle close)
    5. Floor 5: Captain decision (on candle close)
    6. Side A: Execution orchestrator (receives Captain decisions)

    On each 1-minute candle close:
        Floor 2(validate) → Floor 3(calculate) → Floor 4(heads)
        → Floor 5(Captain decide) → Side A(execute)

    On every tick (light cycle):
        Floor 5(Captain light cycle — plan watching, thesis review)
    """

    def __init__(self) -> None:
        self._registry = get_registry()
        self._config = get_system_config()

        # Core components
        self._captain = self._registry.get_captain_engine()
        self._orchestrator = self._registry.get_orchestrator()
        self._auth = self._registry.get_auth_manager()

        # Floor 1 connection
        self._source_health = self._registry.get_source_health_monitor()
        self._router = self._registry.get_ingress_router()

        # Floor 4
        self._floor_summary_builder = self._registry.get_floor_summary_builder()

        # Cached Floor 4 head instances (reused across cycles for HeadMemory persistence)
        self._heads: list[Any] = []

        # Runtime state
        self._running = False
        self._last_candle_index: int = -1
        self._session_started = False

        # Current price tracking (updated by tick handler)
        self._current_price: float = 0.0
        self._current_atm_strike: float = 19500.0  # Default for NIFTY

        # 1-minute candle accumulator (built from WebSocket ticks)
        self._candle_open: float = 0.0
        self._candle_high: float = 0.0
        self._candle_low: float = 0.0
        self._candle_close: float = 0.0
        self._candle_volume: int = 0
        self._candle_initialized: bool = False

        # Candle history buffer — keeps last 100 1m candles for Floor 3 engines
        # Engines need historical data (RSI needs 14, MA needs 20+, SMC needs ~20)
        self._candle_buffer: list[dict[str, Any]] = []

    # ── Public API ──────────────────────────────────────────────────────

    def start(self, mode: str = "ALERT", capital: float | None = None) -> None:
        """Start the system runner.

        This is the main entry point. It:
        1. Sets the execution mode
        2. Attempts Angel One login
        3. Enters the main loop (market hours → pipeline, non-market → idle)

        Args:
            mode: Initial execution mode (ALERT / PAPER / REAL).
            capital: Initial capital limit (optional).
        """
        log.info("=" * 60)
        log.info("  JUNIOR ALADDIN V2.0 — SYSTEM RUNNER STARTING")
        log.info("=" * 60)

        # Set mode from SystemConfig (or argument)
        try:
            exec_mode = ExecutionMode(mode.upper())
            self._config.set_mode(exec_mode, reason="System startup")
            log.info("Execution mode: %s", exec_mode.value)
        except Exception:
            log.warning("Invalid mode: %s, using ALERT", mode)

        # Set capital if provided
        if capital is not None and capital > 0:
            self._config.set_capital_limit(capital, reason="System startup")
            log.info("Capital limit: ₹%.2f", capital)

        # Try Angel One login
        self._try_angel_one_login()

        # Start the main loop
        self._running = True
        self._main_loop()

    def stop(self) -> None:
        """Stop the system runner gracefully."""
        log.info("System Runner stopping ...")
        self._running = False
        self._router.stop_routing()
        self._auth.logout()
        self._registry.shutdown()
        log.info("System Runner stopped")

    def is_running(self) -> bool:
        """Check if the runner is currently active."""
        return self._running

    # ── Main Loop ───────────────────────────────────────────────────────

    def _main_loop(self) -> None:
        """The core loop — runs until stop() is called.

        Market hours:
            - Every tick: light cycle (Captain plan watching)
            - Every 1m candle close: heavy cycle (full pipeline)
            - Updates current price from market

        Non-market hours:
            - Sleeps 5s between checks
            - Starts session when market opens
        """
        log.info("Entering main loop (checking every %.1fs)", CYCLE_CHECK_INTERVAL_S)

        try:
            while self._running:
                now = _now_ist()
                market_open = _is_market_hours(now)

                if market_open:
                    self._on_market_tick(now)
                else:
                    self._on_idle(now)

                time.sleep(CYCLE_CHECK_INTERVAL_S)

        except KeyboardInterrupt:
            log.info("Keyboard interrupt received")
        except Exception:
            log.exception("Fatal error in main loop")
        finally:
            self.stop()

    def _on_market_tick(self, now: datetime) -> None:
        """Process a market tick.

        Called every CYCLE_CHECK_INTERVAL_S during market hours.

        1. Start session on first tick
        2. Check for candle close
        3. Run light cycle
        """
        # Start session if not started
        if not self._session_started:
            self._start_session(now)

        candle_index = _get_candle_index(now)

        # Check for 1-minute candle close
        if candle_index != self._last_candle_index:
            self._on_candle_close(now, candle_index)

        # Light cycle (every tick)
        self._run_light_cycle()

    def _on_candle_close(self, now: datetime, candle_index: int) -> None:
        """Process a 1-minute candle close — run HEAVY CYCLE.

        Full pipeline:
            Floor 2 → Floor 3 (calculate) → Floor 4 (heads refresh)
            → Floor 5 (Captain) → Side A (execution)
        """
        self._last_candle_index = candle_index

        try:
            # ── Build candle from accumulated ticks ────────────────
            from junior_aladdin.floor_3_calculations.f3_types import (
                CalculationInput,
                MarketPhase,
            )

            # Determine market phase based on IST time
            market_phase = MarketPhase.OPEN
            hour = now.hour
            if hour < 9 or (hour == 9 and now.minute < 15):
                market_phase = MarketPhase.PRE_OPEN
            elif hour >= 15 and now.minute >= 30:
                market_phase = MarketPhase.CLOSING
            elif hour >= 16:
                market_phase = MarketPhase.POST_CLOSE

            # Build candle data from accumulated ticks
            candle_data = {}
            if self._candle_initialized:
                candle_data = {
                    "open": self._candle_open,
                    "high": self._candle_high,
                    "low": self._candle_low,
                    "close": self._candle_close,
                    "volume": self._candle_volume,
                    "timestamp": now.isoformat(),
                }

            # Append to candle history buffer (max 100 candles)
            if candle_data:
                self._candle_buffer.append(candle_data)
                if len(self._candle_buffer) > CANDLE_BUFFER_MAX:
                    self._candle_buffer = self._candle_buffer[-CANDLE_BUFFER_MAX:]

            # Pass FULL buffer to Floor 3 so engines have historical data
            candles_for_f3 = list(self._candle_buffer) if self._candle_buffer else []

            log.info(
                "Candle %d closed — running heavy cycle (buffer: %d candles)",
                candle_index, len(candles_for_f3),
            )

            calc_input = CalculationInput(
                packet_envelope_id=f"candle_{candle_index}",
                market_phase=market_phase,
                symbol="NIFTY",
                timestamp=now,
                data={
                    "current_price": self._current_price,
                    "candles": candles_for_f3,
                    "candle_index": candle_index,
                },
            )

            # Reset candle accumulator for next 1-minute candle
            self._candle_initialized = False
            self._candle_open = 0.0
            self._candle_high = 0.0
            self._candle_low = 0.0
            self._candle_close = 0.0
            self._candle_volume = 0

            f3_orchestrator = self._registry.get_f3_orchestrator()
            output_contract = f3_orchestrator(calc_input)

            # Log Floor 3 results
            if output_contract and output_contract.floor_summary:
                fs = output_contract.floor_summary
                log.info(
                    "Floor 3 complete — %d signal(s) across %d engine(s) | data_health=%s",
                    fs.signals_count,
                    len(fs.engine_statuses),
                    fs.data_health.value,
                )

            # ── Step 2: Floor 4 — Refresh Department Heads ──────────
            head_reports, floor_summary = self._refresh_floor_4_heads(output_contract)

            log.info(
                "Floor 4 complete — %d head report(s)",
                len(head_reports),
            )

            # ── Step 3: Floor 5 — Captain Heavy Cycle ──────────────
            from junior_aladdin.floor_5_captain.captain_types import CaptainInput

            captain_input = CaptainInput(
                floor_summary=floor_summary or CaptainInput().floor_summary,
                head_reports=head_reports,
                system_context={
                    "mode": self._config.get_mode().value,
                    "capital_limit": self._config.get_capital_limit(),
                },
            )

            mode = self._config.get_mode()
            capital = self._config.get_capital_limit() or 0.0

            output = self._captain.heavy_cycle(
                captain_input=captain_input,
                current_price=self._current_price,
                current_mode=mode,
                capital_available=capital,
                candle_index=candle_index,
                atm_strike=self._current_atm_strike,
            )

            # Log captain state
            if output.captain_state is not None:
                cs = output.captain_state
                log.info(
                    "🚀 Captain: mood=%s | decision=%s | conviction=%s",
                    cs.mood.value,
                    cs.decision_state.value if hasattr(cs.decision_state, 'value') else cs.decision_state,
                    cs.conviction_band.value if hasattr(cs.conviction_band, 'value') else cs.conviction_band,
                )

            # ── Step 4: Side A — Forward Captain decision ───────────
            if output.decision is not None:
                # Update orchestrator mode from SystemConfig
                if mode != self._orchestrator.get_execution_mode():
                    self._orchestrator.set_execution_mode(mode)

                # Update capital
                if capital > 0:
                    try:
                        self._orchestrator._mode_router._check_capital = lambda: (
                            self._config.get_capital_limit() or 0.0
                        )
                    except Exception:
                        pass

                # Send decision to orchestrator if TRADE
                if output.has_trade and output.decision is not None:
                    import copy
                    from junior_aladdin.shared.types import CaptainDecision

                    decision = output.decision
                    result = self._orchestrator.receive_decision(
                        decision=decision,
                        system_context={
                            "mode": mode.value,
                            "capital_available": capital,
                        },
                    )
                    if result.accepted:
                        log.info(
                            "TRADE ACCEPTED — %s %s %s (order: %s)",
                            decision.action,
                            decision.option_side,
                            decision.selected_strike,
                            result.order_id or "ALERT_ONLY",
                        )
                    else:
                        log.info(
                            "TRADE REJECTED — %s (reason: %s)",
                            decision.action,
                            result.rejection_reason,
                        )

        except Exception:
            log.exception("Heavy cycle failed at candle %d", candle_index)

    def _run_light_cycle(self) -> None:
        """Run a light cycle tick (Captain plan watching + thesis review)."""
        try:
            self._captain.light_cycle(
                current_price=self._current_price,
                candle_index=self._last_candle_index,
            )
        except Exception:
            log.debug("Light cycle failed (non-fatal)", exc_info=True)

    def _on_idle(self, now: datetime) -> None:
        """Process idle time (market closed).

        Resets session state for next market open.
        """
        if self._session_started:
            log.info("Market closed — session ended at %s", now.strftime("%H:%M:%S IST"))
            self._session_started = False
            self._last_candle_index = -1

    # ── Session Management ─────────────────────────────────────────────

    def _start_session(self, now: datetime) -> None:
        """Start a new trading session."""
        log.info(
            "🚀 Trading session started — %s",
            now.strftime("%Y-%m-%d %H:%M:%S IST"),
        )
        self._session_started = True
        self._last_candle_index = -1

        # Reset Captain engine for new session
        self._captain.start_session()

        # Start routing — this registers data callbacks on the AngelOneAdapter
        # so WebSocket ticks flow through: Adapter → IngressRouter → FeedAdapter
        # → PacketEnvelope → Floor2 handoff
        self._router.start_routing()

        # Register a direct price tracker on the AngelOneAdapter
        # so SystemRunner._current_price is updated in real-time
        # AND candles are accumulated for Floor 3
        try:
            adapter = self._registry.get_angel_one_adapter()

            def _track_price(source_name: str, feed_type: str, data: dict) -> None:
                """Update current price + build candles from incoming spot ticks.

                Builds candles ONLY from the NIFTY index token (26000) to avoid
                mixing prices from different securities (RELIANCE, TCS, etc.).
                """
                if feed_type != "spot_tick":
                    return

                # Only use NIFTY index token for price tracking + candle building
                token = str(data.get("token", ""))
                if token != "26000":
                    return

                ltp = data.get("last_price") or data.get("lt") or data.get("ltp") or 0.0
                price = float(ltp) if ltp else 0.0
                if price <= 0:
                    return

                # 1. Update SystemRunner state
                self._current_price = price
                self._current_atm_strike = round(price / 100.0) * 100

                # 2. Push LTP to the shared health monitor so API can read it
                try:
                    self._source_health.update_ltp(price)
                except Exception:
                    pass

                # 3. Build 1-minute candle (NIFTY index only)
                if not self._candle_initialized:
                    self._candle_open = price
                    self._candle_high = price
                    self._candle_low = price
                    self._candle_close = price
                    self._candle_volume = data.get("volume", 1)
                    self._candle_initialized = True
                else:
                    self._candle_high = max(self._candle_high, price)
                    self._candle_low = min(self._candle_low, price) if self._candle_low > 0 else price
                    self._candle_close = price
                    vol = data.get("volume", 1)
                    if vol > 0:
                        self._candle_volume += vol

            adapter.on_data(_track_price)
            log.info("Price tracker + candle accumulator registered on AngelOneAdapter")
        except Exception:
            log.warning("Price tracker registration skipped", exc_info=True)

    # ── Floor 4 Head Refresh ───────────────────────────────────────────

    def _ensure_heads_initialized(self) -> None:
        """Lazy-initialize the 6 head instances (cached for memory persistence)."""
        if not self._heads:
            from junior_aladdin.floor_4_heads.smc_head import SMCHead
            from junior_aladdin.floor_4_heads.ict_head import ICTHead
            from junior_aladdin.floor_4_heads.technical_head import TechnicalHead
            from junior_aladdin.floor_4_heads.options_head import OptionsHead
            from junior_aladdin.floor_4_heads.macro_head import MacroHead
            from junior_aladdin.floor_4_heads.psychology_head import PsychologyHead

            self._heads = [
                SMCHead(),
                ICTHead(),
                TechnicalHead(),
                OptionsHead(),
                MacroHead(),
                PsychologyHead(),
            ]
            log.info("6 Floor 4 head instances created (cached)")

    def _refresh_floor_4_heads(
        self,
        output_contract: Any | None = None,
    ) -> tuple[dict[str, Any], Any | None]:
        """Refresh all 6 Department Heads and return reports.

        Uses cached head instances (initialized once in __init__) so
        HeadMemory (last_refresh_time, last_bias, etc.) persists across
        candle cycles.

        Always calls ALL 6 heads even with 0 signals from Floor 3.
        Heads return NO_SETUP/UNCERTAIN reports instead of being skipped.

        Args:
            output_contract: The OutputContract from Floor 3 calculation cycle.

        Returns:
            Tuple of ``(reports, floor_summary)`` where:
            - reports: dict mapping head_name → HeadReport
            - floor_summary: FloorSummary or None
        """
        if output_contract is None:
            log.info("Floor 4 heads: no Floor 3 output available — skipping")
            return {}, None

        signal_count = len(output_contract.signals) if output_contract.signals else 0

        try:
            self._ensure_heads_initialized()
            now = _now_ist()
            reports: dict[str, Any] = {}

            for head in self._heads:
                try:
                    report = head.refresh(output_contract, current_time=now)
                    reports[head.head_name] = report
                except Exception:
                    log.warning(
                        "Head %s refresh failed",
                        head.head_name,
                        exc_info=True,
                    )

            # Build FloorSummary (returned separately, NOT mixed into reports dict)
            summary = None
            if reports:
                summary = self._floor_summary_builder.build(reports, timestamp=now)

            log.info(
                "Floor 4 heads: %d/%d reports generated (Floor 3 signals: %d)",
                len(reports), len(self._heads), signal_count,
            )

            return reports, summary

        except Exception:
            log.warning("Floor 4 head refresh failed", exc_info=True)
            return {}, None

    # ── Angel One Connection ───────────────────────────────────────────

    def _try_angel_one_login(self) -> bool:
        """Attempt full Angel One connection — REST auth + WebSocket.

        1. Gets the shared AngelOneAdapter (with auth + health monitor)
        2. Calls adapter.connect() which:
           a. Calls AuthManager.login() for REST authentication
           b. Establishes SmartAPI WebSocket for live tick data
           c. Subscribes to NIFTY 50 tokens
        3. Subscribes the "spot_tick" feed so data flows through the pipeline

        Returns:
            True if full connection (REST + WebSocket) succeeded.
            False if credentials missing or connection failed.
        """
        creds = self._config.get_angel_one_credentials()
        if not creds["client_id"]:
            log.warning(
                "Angel One credentials not configured. "
                "Set ANGEL_ONE_CLIENT_ID, ANGEL_ONE_API_KEY, ANGEL_ONE_PIN in .env "
                "or config/*.yaml"
            )
            return False

        try:
            # Get the shared AngelOneAdapter (wired with auth + health)
            adapter = self._registry.get_angel_one_adapter()

            # This does: REST login → WebSocket connect → NIFTY 50 subscribe
            adapter.connect()

            # Subscribe to spot_tick feed so data flows through the pipeline
            # (IngressRouter registers its data callbacks during start_routing)
            adapter.subscribe_feeds(["spot_tick"])

            log.info(
                "✅ Angel One fully connected — client=%s | WebSocket=%s | Feeds=[spot_tick]",
                creds["client_id"][:4] + "****",
                "ACTIVE",
            )
            return True

        except Exception:
            log.warning(
                "Angel One connection failed. System will run with Paper broker only.",
                exc_info=True,
            )
            return False


# =============================================================================
# CLI Entry Point
# =============================================================================


def main() -> None:
    """Run the System Runner with command-line arguments.

    Usage:
        python -m junior_aladdin.system_runner
        python -m junior_aladdin.system_runner --mode PAPER --capital 50000
    """
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    parser = argparse.ArgumentParser(
        description="Junior Aladdin V2.0 — System Runner",
    )
    parser.add_argument(
        "--mode",
        type=str,
        default="ALERT",
        choices=["ALERT", "PAPER", "REAL"],
        help="Execution mode (default: ALERT)",
    )
    parser.add_argument(
        "--capital",
        type=float,
        default=None,
        help="Capital limit in INR",
    )
    parser.add_argument(
        "--api-server",
        action="store_true",
        default=True,
        help="Also start the Side B API server (default: True)",
    )

    args = parser.parse_args()

    log.info("=" * 60)
    log.info("  JUNIOR ALADDIN V2.0")
    log.info("  Mode: %s | Capital: %s", args.mode, args.capital or "Not set")
    log.info("  API Server: %s", "enabled" if args.api_server else "disabled")
    log.info("=" * 60)

    # Create and start the runner
    runner = SystemRunner()

    # ── Start API server in a daemon thread (same process, shared singletons) ──
    if args.api_server:
        try:
            import uvicorn
            api_thread = threading.Thread(
                target=uvicorn.run,
                kwargs={
                    "app": "junior_aladdin.side_b_api.api_server:app",
                    "host": "127.0.0.1",
                    "port": 8080,
                    "reload": False,
                    "log_level": "info",
                    "access_log": True,
                },
                daemon=True,
                name="api-server",
            )
            api_thread.start()
            log.info("Side B API server started on http://127.0.0.1:8080 (in-process)")
        except ImportError:
            log.warning("uvicorn not installed — API server disabled")
        except Exception as exc:
            log.warning("API server failed to start: %s", exc)

    # Handle graceful shutdown
    shutdown_requested = False

    def _signal_handler(sig: int, _frame: Any) -> None:
        nonlocal shutdown_requested
        if shutdown_requested:
            log.warning("Forced exit")
            sys.exit(1)
        shutdown_requested = True
        log.info("Shutdown requested (press Ctrl+C again to force)")
        runner.stop()

    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    # Start the main loop (blocking)
    runner.start(mode=args.mode, capital=args.capital)


if __name__ == "__main__":
    main()
