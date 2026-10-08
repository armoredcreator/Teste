from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.config import load_config
from src.historical_database import HistoricalDatabase
from src.vision.historical import HistoricalVisionRunner


def database_path(root: Path, source_id: int) -> Path:
    return root / "batch" / "sources" / str(source_id) / "database" / "historical.db"


def run_source(root: Path, source_id: int, limit: int | None) -> dict[str, int]:
    db = HistoricalDatabase(database_path(root, source_id), source_id)
    try:
        if db.total() == 0:
            raise RuntimeError(f"Fonte {source_id} não possui inventário histórico.")

        print(f"[SOURCE {source_id}] inventário={db.total()}")
        print(f"[SOURCE {source_id}] antes={db.counts()}")
        result = HistoricalVisionRunner(db).drain(limit=limit)
        print(f"[SOURCE {source_id}] processado={result}")
        print(f"[SOURCE {source_id}] depois={db.counts()}")
        return result
    finally:
        db.close()


def main(source_number: int | None, limit: int | None) -> None:
    root = Path(__file__).resolve().parents[1]
    config = load_config(root)

    if source_number is not None:
        if source_number < 1 or source_number > len(config.sources):
            raise ValueError(f"--source deve estar entre 1 e {len(config.sources)}")
        source_ids = (config.sources[source_number - 1],)
    else:
        source_ids = config.sources

    print("=" * 72)
    print("ARMORED CREATOR — ARMOREDVISION / CATCH-UP HISTÓRICO")
    print("=" * 72)
    print("Somente Vision: nenhum vídeo é baixado e nenhuma mensagem é publicada.")
    print("Ordem: F1 -> F2 -> F3.")
    if limit is not None:
        print(f"Limite por fonte: {limit}")
    print()

    totals = {"VISION_ACCEPTED": 0, "WAITING_VISION": 0, "VISION_PROCESSING": 0, "processed": 0}
    for source_id in source_ids:
        result = run_source(root, source_id, limit)
        for key in totals:
            totals[key] += result.get(key, 0)
        print()

    print("=" * 72)
    print(f"TOTAL VISION: {totals}")
    print("=" * 72)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=int, choices=(1, 2, 3))
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()
    main(args.source, args.limit)
