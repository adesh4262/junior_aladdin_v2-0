"""Feed adapters for Floor 1.

Each adapter handles a specific data feed type:
  - SpotFeedAdapter: NIFTY 50 LTP/OHLC ticks
  - OptionsFeedAdapter: Option chain, OI, premium snapshots
  - VixFeedAdapter: India VIX ticks
  - MacroFeedAdapter: FII/DII, global cues (stub)
  - CalendarFeedAdapter: Holiday/expiry/event (stub)

Feed adapters do ONLY identity tagging + routing classification.
They do NOT validate, clean, or transform data beyond adding feed_type tags.
The actual PacketEnvelope wrapping happens in the ingress_router.

Floor 1 rule: ONLY imports from shared/. No floor_2+ imports.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any, Callable

from junior_aladdin.shared.logging import get_logger

logger = get_logger("feed_adapters")

# Type alias for feed data callbacks
FeedCallback = Callable[[dict[str, Any]], None]


# ------------------------------------------------------------------
# Base adapter
# ------------------------------------------------------------------


class BaseFeedAdapter(ABC):
    """Abstract base for all feed adapters.

    Each adapter assigns its feed_type identity and routes data via callbacks.
    """

    def __init__(self) -> None:
        self._callbacks: list[FeedCallback] = []
        self._feed_type: str = "unknown"

    @property
    def feed_type(self) -> str:
        """Return the feed type identifier."""
        return self._feed_type

    def subscribe(self, callback: FeedCallback) -> None:
        """Register a callback to receive envelope-ready data dicts."""
        if callback not in self._callbacks:
            self._callbacks.append(callback)

    def _notify(self, data: dict[str, Any]) -> None:
        """Notify all registered callbacks with envelope-ready data."""
        data["feed_type"] = self._feed_type
        for cb in self._callbacks:
            try:
                cb(data)
            except Exception:
                logger.error(
                    "Feed callback failed",
                    extra={"feed_type": self._feed_type, "error": "exception in callback"},
                )

    @abstractmethod
    def handle_data(self, raw_data: dict[str, Any]) -> dict[str, Any]:
        """Transform raw source data into an envelope-ready dict.

        Must add feed_type to the returned dict.
        Must NOT validate, clean, or interpret market data.
        """
        ...


# ------------------------------------------------------------------
# Spot feed adapter
# ------------------------------------------------------------------


class SpotFeedAdapter(BaseFeedAdapter):
    """NIFTY 50 spot tick adapter.

    Handles LTP, OHLC, volume, depth data from the spot market.
    """

    def __init__(self) -> None:
        super().__init__()
        self._feed_type = "spot_tick"

    def handle_data(self, raw_data: dict[str, Any]) -> dict[str, Any]:
        """Tag spot tick data as envelope-ready.

        Preserves all original fields. Adds feed_type tag.
        """
        result = {
            "feed_type": self._feed_type,
            **raw_data,
        }
        return result

    def on_tick(self, data: dict[str, Any]) -> dict[str, Any]:
        """Process an incoming tick and notify callbacks.

        Args:
            data: Raw tick data from the source adapter.

        Returns:
            Envelope-ready dict with feed_type tagging.
        """
        result = self.handle_data(data)
        self._notify(result)
        return result


# ------------------------------------------------------------------
# Options feed adapter
# ------------------------------------------------------------------


class OptionsFeedAdapter(BaseFeedAdapter):
    """Options chain snapshot adapter.

    Handles option chain data: OI, premium, IV, greeks at configurable intervals.
    """

    def __init__(self) -> None:
        super().__init__()
        self._feed_type = "options_snapshot"

    def handle_data(self, raw_data: dict[str, Any]) -> dict[str, Any]:
        """Tag options snapshot as envelope-ready."""
        result = {
            "feed_type": self._feed_type,
            **raw_data,
        }
        return result

    def on_snapshot(self, data: dict[str, Any]) -> dict[str, Any]:
        """Process an incoming options snapshot and notify callbacks."""
        result = self.handle_data(data)
        self._notify(result)
        return result


# ------------------------------------------------------------------
# VIX feed adapter
# ------------------------------------------------------------------


class VixFeedAdapter(BaseFeedAdapter):
    """India VIX tick adapter."""

    def __init__(self) -> None:
        super().__init__()
        self._feed_type = "vix_tick"

    def handle_data(self, raw_data: dict[str, Any]) -> dict[str, Any]:
        """Tag VIX tick data as envelope-ready."""
        result = {
            "feed_type": self._feed_type,
            **raw_data,
        }
        return result

    def on_tick(self, data: dict[str, Any]) -> dict[str, Any]:
        """Process an incoming VIX tick and notify callbacks."""
        result = self.handle_data(data)
        self._notify(result)
        return result


# ------------------------------------------------------------------
# Macro feed adapter (STUB)
# ------------------------------------------------------------------


class MacroFeedAdapter(BaseFeedAdapter):
    """Macro data adapter — STUB initially.

    Will receive FII/DII data and global cues.
    Currently returns mock/empty data gracefully.
    """

    def __init__(self) -> None:
        super().__init__()
        self._feed_type = "macro_data"

    def handle_data(self, raw_data: dict[str, Any] | None = None) -> dict[str, Any]:
        """Process macro data — stub implementation.

        If no data is provided, returns a minimal envelope-ready dict
        with a stub flag.
        """
        data = raw_data or {}
        result = {
            "feed_type": self._feed_type,
            "stub": True,
            **data,
        }
        return result

    def on_macro_update(self, data: dict[str, Any] | None = None) -> dict[str, Any]:
        """Process a macro data update and notify callbacks."""
        result = self.handle_data(data)
        self._notify(result)
        return result


# ------------------------------------------------------------------
# Calendar feed adapter (STUB)
# ------------------------------------------------------------------


class CalendarFeedAdapter(BaseFeedAdapter):
    """Calendar event adapter — STUB initially.

    Handles holiday/expiry/event data.
    Can receive input both from manual ingress and derived sources.
    """

    def __init__(self) -> None:
        super().__init__()
        self._feed_type = "calendar_event"

    def handle_data(self, raw_data: dict[str, Any] | None = None) -> dict[str, Any]:
        """Process calendar data — stub implementation.

        Expects data with optional keys: holiday, expiry, event_type, date.
        Returns minmal envelope-ready dict with stub flag if no data.
        """
        data = raw_data or {}
        result = {
            "feed_type": self._feed_type,
            "stub": True,
            **data,
        }
        return result

    def on_calendar_event(self, data: dict[str, Any] | None = None) -> dict[str, Any]:
        """Process a calendar event and notify callbacks."""
        result = self.handle_data(data)
        self._notify(result)
        return result
