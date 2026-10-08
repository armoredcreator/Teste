from __future__ import annotations

import argparse
import asyncio

from src.config import load_config
from src.historical_executor import HistoricalExecutor, ROOT


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the historical Vision stage in source order."
    )
    parser.add_argument(
        "--source",
        type=int,
        choices=(1, 2, 3),
        help="Run only the selected configured source. Without this flag, run all sources in order.",
    )
    return parser.parse_args()


async def main() -> None:
    config = load_config(ROOT)
    args = parse_args()

    if args.source is not None:
        source_id = config.sources[args.source - 1]
        print(f"\n=== VISION CATCH-UP / SOURCE {source_id} ===", flush=True)
        executor = HistoricalExecutor(source_id)
        await executor.run_vision_batch()
        return

    # Source order is deliberate: the next source is not opened until the
    # complete Vision stage of the current source has drained.
    for source_id in config.sources:
        print(f"\n=== VISION CATCH-UP / SOURCE {source_id} ===", flush=True)
        executor = HistoricalExecutor(source_id)
        await executor.run_vision_batch()


if __name__ == "__main__":
    asyncio.run(main())
