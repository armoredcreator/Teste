from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.config import load_config
from src.historical_database import HistoricalDatabase
from src.sync_discovery import discover_sync_candidates
from src.telegram_reader import TelegramReader


def database_path(root: Path, source_id: int) -> Path:
    return root / "batch" / "sources" / str(source_id) / "database" / "historical.db"


async def collect_source(
    reader: TelegramReader,
    root: Path,
    source_id: int,
) -> tuple[int, int]:
    title = await reader.source_title(source_id)
    mode = await reader.source_mode(source_id)
    db = HistoricalDatabase(database_path(root, source_id), source_id)
    run_id = db.start_run()
    db.set_source(title, mode)

    inserted = 0
    seen = 0
    try:
        async for candidate in discover_sync_candidates(reader, source_id):
            seen += 1
            db.record_seen(run_id)
            if db.insert_candidate(candidate):
                inserted += 1
            if seen % 250 == 0:
                db.commit()
                print(
                    f"  [{source_id}] candidatos vistos={seen} "
                    f"novos={inserted} banco={db.total()}",
                    flush=True,
                )

        db.finish_run(run_id, "COMPLETED")
        print(
            f"  [{source_id}] concluído: vistos={seen} "
            f"novos={inserted} total_banco={db.total()}",
            flush=True,
        )
        return seen, inserted
    except Exception as exc:
        db.finish_run(run_id, "FAILED", str(exc))
        raise
    finally:
        db.close()


async def main() -> None:
    root = Path(__file__).resolve().parents[1]
    config = load_config(root)
    session_dir = root / "credentials" / "telegram"
    session_dir.mkdir(parents=True, exist_ok=True)

    reader = TelegramReader(
        api_id=config.api_id,
        api_hash=config.api_hash,
        session_path=session_dir / "armoredsync",
    )

    print("=" * 72)
    print("ARMORED CREATOR — CATCH-UP HISTÓRICO / INVENTÁRIO SQLITE")
    print("=" * 72)
    print("Modo: somente leitura no Telegram; nenhum vídeo é baixado.")
    print("Destino: batch/sources/<source_id>/database/historical.db")
    print()

    try:
        await reader.connect()
        totals = 0
        inserted = 0

        for index, source_id in enumerate(config.sources, start=1):
            print(f"[{index}/3] SOURCE {source_id}")
            seen, added = await collect_source(reader, root, source_id)
            totals += seen
            inserted += added
            print()

        print("=" * 72)
        print(f"CATCH-UP COLETADO: vistos={totals} novos={inserted}")
        print("Nenhuma mídia foi baixada. Nenhuma mensagem foi modificada.")
        print("=" * 72)
    finally:
        await reader.close()


if __name__ == "__main__":
    asyncio.run(main())
