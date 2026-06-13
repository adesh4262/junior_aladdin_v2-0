#!/usr/bin/env python
"""Junior Aladdin — Seed Test Data Generator.

Generates sample test data files for development and testing.
Outputs JSON files to data/ directory.

Usage:
    python scripts/seed_test_data.py          # generate all data
    python scripts/seed_test_data.py --count 120  # generate 120 candles
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Ensure project root is in path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from junior_aladdin.shared.testing import (
    generate_mock_tick_stream,
    seed_1min_candles,
    generate_mock_floor2_handoff,
)


def save_json(filename: str, data: object) -> Path:
    """Save data as JSON to the data/ directory."""
    data_dir = Path("data")
    data_dir.mkdir(parents=True, exist_ok=True)
    filepath = data_dir / filename
    with open(filepath, "w") as f:
        json.dump(data, f, indent=2, default=str)
    print(f"  ✓ {filepath} ({len(json.dumps(data, default=str))} bytes)")
    return filepath


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate seed test data.")
    parser.add_argument(
        "--count", type=int, default=60,
        help="Number of candles/ticks to generate (default: 60)",
    )
    args = parser.parse_args()

    print(f"Generating seed test data ({args.count} samples)…\n")

    # Tick stream
    ticks = generate_mock_tick_stream(count=args.count)
    save_json("seed_ticks.json", ticks)

    # 1-minute candles
    candles = seed_1min_candles(count=args.count)
    save_json("seed_candles_1m.json", candles)

    # Floor 2 handoff
    handoff = generate_mock_floor2_handoff()
    save_json("seed_floor2_handoff.json", handoff)

    print("\nDone. Use this data for testing Floor 2/3/4 pipelines.")


if __name__ == "__main__":
    main()
