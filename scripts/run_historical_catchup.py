from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.historical_pipeline import run_catchup


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Executa o catch-up histórico por ferramenta: Vision -> Stock -> IA -> Studio -> Hub."
    )
    parser.add_argument("--limit", type=int, default=None, help="limite por fonte em cada ferramenta")
    args = parser.parse_args()
    asyncio.run(run_catchup(ROOT, limit=args.limit))
