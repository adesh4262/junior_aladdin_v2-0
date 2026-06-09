"""Technical — Volume Profile Calculator.

Calculates Volume Profile Visible Range (VPVR) from OHLCV data over a
specified lookback period. Produces the Point of Control (POC), Value
Area High (VAH), and Value Area Low (VAL).

Volume Profile divides the total price range into equal-sized price
buckets (rows), assigns each candle's volume to the buckets it touches,
then identifies:
- Point of Control (POC): Price bucket with the highest volume.
- Value Area: Buckets around the POC that contain 70% of total volume.
- Value Area High (VAH): Highest price in the value area.
- Value Area Low (VAL): Lowest price in the value area.

Architecture rules:
- Pure function — no state, no external calls, no side effects.
- Deterministic — same candles + period → same profile.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from junior_aladdin.floor_3_calculations.f3_types import VolumeProfile


# ── Module-level constants ──────────────────────────────────────────────────
_DEFAULT_PERIOD: int = 30
_DEFAULT_BUCKET_COUNT: int = 50  # Number of price buckets/rows
_VA_TARGET: float = 0.70  # Value area target: 70% of total volume


# =============================================================================
# PUBLIC API
# =============================================================================


def calculate_volume_profile(
    candles: list[dict[str, Any]],
    period: int = _DEFAULT_PERIOD,
    bucket_count: int = _DEFAULT_BUCKET_COUNT,
) -> VolumeProfile:
    """Calculate Volume Profile for a set of candles.

    Divides the overall price range into equal-sized buckets, distributes
    candle volumes across those buckets, and identifies POC, VAH, and VAL.

    Args:
        candles: List of OHLCV candle dicts with ``\"high\"``, ``\"low\"``,
            ``\"volume\"``, and ``\"timestamp\"`` keys. Must have at least
            ``period`` candles.
        period: Lookback period. Default 30.
        bucket_count: Number of price buckets/rows to use. Default 50.

    Returns:
        A ``VolumeProfile`` object with POC, VAH, VAL, and volume stats.
        Returns an empty profile (all zeros) if insufficient data.

    Raises:
        ValueError: If ``period < 5`` or ``bucket_count < 5``.
    """
    if period < 5:
        raise ValueError(f"period must be >= 5, got {period}")
    if bucket_count < 5:
        raise ValueError(f"bucket_count must be >= 5, got {bucket_count}")

    if len(candles) < period:
        return VolumeProfile(timestamp=datetime.min)

    # Use only the most recent `period` candles
    window = candles[-period:]

    # Extract valid candles (must have high, low, volume, timestamp)
    valid: list[dict[str, Any]] = []
    latest_ts = datetime.min
    for c in window:
        ts = c.get("timestamp")
        if not isinstance(ts, datetime):
            continue
        high = c.get("high")
        low = c.get("low")
        vol = c.get("volume", 0)
        if any(v is None or not isinstance(v, (int, float)) for v in (high, low)):
            continue
        if not vol or not isinstance(vol, (int, float)):
            vol = 0
        valid.append({
            "high": float(high) if high else 0,
            "low": float(low) if low else 0,
            "volume": int(vol) if vol else 0,
            "timestamp": ts,
        })
        latest_ts = ts

    if len(valid) < period // 2:  # Need at least half the period worth of valid data
        return VolumeProfile(timestamp=latest_ts)

    # Find overall price range
    overall_high = max(c["high"] for c in valid)
    overall_low = min(c["low"] for c in valid)
    price_range = overall_high - overall_low

    if price_range <= 0:
        # All candles at same price — POC is that price
        total_vol = sum(c["volume"] for c in valid)
        return VolumeProfile(
            timestamp=latest_ts,
            poc=overall_high,
            vah=overall_high,
            val=overall_low,
            value_area_volume=total_vol,
            total_volume=total_vol,
        )

    # Create price buckets
    bucket_size = price_range / bucket_count
    # Each bucket tracks: (low_price, high_price, volume)
    buckets: list[dict[str, Any]] = []
    for i in range(bucket_count):
        b_low = overall_low + i * bucket_size
        b_high = b_low + bucket_size
        buckets.append({
            "low": b_low,
            "high": b_high,
            "volume": 0,
        })

    # Distribute candle volume across buckets
    total_volume = 0
    for c in valid:
        vol = c["volume"]
        if vol <= 0:
            continue

        c_high = c["high"]
        c_low = c["low"]

        # Find which buckets this candle touches
        first_bucket = max(0, int((c_low - overall_low) / bucket_size))
        last_bucket = min(bucket_count - 1, int((c_high - overall_low) / bucket_size))

        if first_bucket == last_bucket:
            # Candle fits entirely in one bucket
            buckets[first_bucket]["volume"] += vol
        else:
            # Candle spans multiple buckets — distribute volume proportionally
            span = c_high - c_low
            if span > 0:
                vol_per_unit = vol / span
                for b_idx in range(first_bucket, last_bucket + 1):
                    b_low = buckets[b_idx]["low"]
                    b_high = buckets[b_idx]["high"]
                    overlap = min(c_high, b_high) - max(c_low, b_low)
                    if overlap > 0:
                        buckets[b_idx]["volume"] += int(vol_per_unit * overlap)
            else:
                # Zero-width candle, assign to its bucket
                buckets[first_bucket]["volume"] += vol

        total_volume += vol

    # Find POC: bucket with highest volume
    poc_idx = max(range(bucket_count), key=lambda i: buckets[i]["volume"])
    poc = (buckets[poc_idx]["low"] + buckets[poc_idx]["high"]) / 2

    # Calculate Value Area: expand from POC until 70% volume is included
    va_volume_target = int(total_volume * _VA_TARGET)
    va_volume = buckets[poc_idx]["volume"]
    va_low_idx = poc_idx
    va_high_idx = poc_idx

    # Expand outward step by step, picking the higher-volume adjacent bucket
    while va_volume < va_volume_target:
        left_vol = buckets[va_low_idx - 1]["volume"] if va_low_idx > 0 else -1
        right_vol = buckets[va_high_idx + 1]["volume"] if va_high_idx < bucket_count - 1 else -1

        if left_vol < 0 and right_vol < 0:
            break  # No more buckets to expand into

        if left_vol >= right_vol:
            va_low_idx -= 1
            va_volume += left_vol
        else:
            va_high_idx += 1
            va_volume += right_vol

    vah = buckets[va_high_idx]["high"]
    val = buckets[va_low_idx]["low"]

    return VolumeProfile(
        timestamp=latest_ts,
        poc=round(poc, 2),
        vah=round(vah, 2),
        val=round(val, 2),
        value_area_volume=va_volume,
        total_volume=total_volume,
    )


def calculate_poc(candles: list[dict[str, Any]], period: int = _DEFAULT_PERIOD) -> float | None:
    """Quick helper to get just the Point of Control price.

    A convenience wrapper around ``calculate_volume_profile``.

    Args:
        candles: List of OHLCV candles.
        period: Lookback period. Default 30.

    Returns:
        The POC price, or ``None`` if insufficient data.
    """
    profile = calculate_volume_profile(candles, period=period)
    if profile.total_volume == 0:
        return None
    return profile.poc
