from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.config import load_config
from src.historical_database import HistoricalDatabase
from src.stock.historical import HistoricalStockRunner


def database_path(root: Path, source_id: int) -> Path:
    return root / "batch" / "sources" / str(source_id) / "database" / "historical.db"


async def main(source_number: int | None, limit: int | None) -> None:
    root = Path(__file__).resolve().parents[1]
    config = load_config(root)
    source_ids = (config.sources[source_number - 1],) if source_number else config.sources
    totals = {"STOCK_READY": 0, "STOCK_PROCESSING": 0, "processed": 0}
    print("=" * 72)
    print("ARMORED CREATOR — ARMOREDSTOCK / CATCH-UP HISTÓRICO")
    print("=" * 72)
    print("Vision-approved only. Ordem: F1 -> F2 -> F3.")
    for source_id in source_ids:
        db = HistoricalDatabase(database_path(root, source_id), source_id)
        try:
            result = await HistoricalStockRunner(db, root).drain(limit)
            print(f"[SOURCE {source_id}] {result}")
            for key in totals:
                totals[key] += result.get(key, 0)
        finally:
            db.close()
    print(f"TOTAL STOCK: {totals}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=int, choices=(1, 2, 3))
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()
    asyncio.run(main(args.source, args.limit))
