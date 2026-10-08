from __future__ import annotations

from pathlib import Path

from ..historical_database import HistoricalDatabase
from .service import ArmoredStock


class HistoricalStockRunner:
    """Drain Stock for one source; the outer script drains all sources."""

    def __init__(self, db: HistoricalDatabase, root: Path):
        self.db = db
        self.root = Path(root)

    async def drain(self, limit: int | None = None) -> dict[str, int]:
        counts = {"STOCK_READY": 0, "STOCK_PROCESSING": 0, "processed": 0}
        runner = ArmoredStock(self.db, self.root)
        while limit is None or counts["processed"] < limit:
            row = self.db.next_stock_candidate()
            if row is None:
                break
            status = await runner.process_one(row)
            counts[status] += 1
            counts["processed"] += 1
            if status == "STOCK_PROCESSING":
                break
        return counts
