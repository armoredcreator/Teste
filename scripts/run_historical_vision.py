from __future__ import annotations

import asyncio

from src.config import load_config
from src.historical_executor import HistoricalExecutor, ROOT


async def main() -> None:
    config = load_config(ROOT)

    # Source order is deliberate: the next source is not opened until the
    # complete Vision stage of the current source has drained.
    for source_id in config.sources:
        print(f"\n=== VISION CATCH-UP / SOURCE {source_id} ===", flush=True)
        executor = HistoricalExecutor(source_id)
        await executor.run_vision_batch()


if __name__ == "__main__":
    asyncio.run(main())
