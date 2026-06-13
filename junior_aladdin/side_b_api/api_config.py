"""Side B API configuration.

Defines runtime settings for the Side B API server:
port, CORS origins, HOT/WARM/COLD refresh intervals, cache limits,
and feature flags.

Reference: ROADMAP_SIDE_B Step 8.1
"""

from __future__ import annotations

from __future__ import annotations

from dataclasses import dataclass, field


# ──────────────────────────────────────────────
#  Refresh Tiers (milliseconds)
# ──────────────────────────────────────────────
HOT_REFRESH_MS: int = 500       # positions, prices, alerts, execution state
WARM_REFRESH_MS: int = 3000     # head reports, captain state, floor summary
COLD_REFRESH_MS: int = 30000    # reference data, logs, history (or on-demand)


# ──────────────────────────────────────────────
#  Server defaults
# ──────────────────────────────────────────────
DEFAULT_PORT: int = 8080
DEFAULT_HOST: str = "127.0.0.1"
CORS_ORIGINS: list[str] = ["http://localhost:8080", "http://127.0.0.1:8080"]


# ──────────────────────────────────────────────
#  Session cache
# ──────────────────────────────────────────────
MAX_CACHE_ENTRIES: int = 5000
AUTH_ENABLED: bool = False         # single operator on localhost — can add later


@dataclass(frozen=True)
class APIConfig:
    """Immutable API configuration bag.

    All values can be overridden via environment variables in the future.
    """
    port: int = DEFAULT_PORT
    host: str = DEFAULT_HOST
    cors_origins: list[str] = field(default_factory=lambda: list(CORS_ORIGINS))
    hot_refresh_ms: int = HOT_REFRESH_MS
    warm_refresh_ms: int = WARM_REFRESH_MS
    cold_refresh_ms: int = COLD_REFRESH_MS
    max_cache_entries: int = MAX_CACHE_ENTRIES
    auth_enabled: bool = AUTH_ENABLED

    # Convenience properties (seconds)
    @property
    def hot_refresh_s(self) -> float:
        return self.hot_refresh_ms / 1000.0

    @property
    def warm_refresh_s(self) -> float:
        return self.warm_refresh_ms / 1000.0

    @property
    def cold_refresh_s(self) -> float:
        return self.cold_refresh_ms / 1000.0


# Singleton default — modules can import this directly
DEFAULT_CONFIG: APIConfig = APIConfig()
